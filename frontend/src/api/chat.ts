// Chat messages, saved by the backend (app/api/conversations.py). SMA-25, SMA-30.
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'

import type { AgentAction } from '@/api/actions'
import { ApiError, apiPost, csrfHeader, toApiError } from '@/api/client'
import { LIST_KEY } from '@/api/conversations'
import { SseSplitter } from '@/lib/sse'

/** What the chat page sends. Without conversation_id, a new conversation is started. */
export type ChatRequest = {
  message: string
  conversation_id?: string
  model?: string
  allow_fallback?: boolean // SMA-26: false = only the chosen model may answer
  general?: boolean // SMA-49, study chats: "Answer from general knowledge"
}

/** One source a study answer cites (SMA-49). Same fields as the backend's CitationOut. */
export type Citation = {
  n: number // the number in the answer: [1]
  chunk_id: string
  document_id: string
  filename: string
  page: number | null // null for TXT / MD
  text: string // the chunk the answer came from
}

/** One tool the AI used for an answer (SMA-42). Same fields as the backend's ToolCallOut. */
export type ToolCallOut = {
  name: string // e.g. "create_task"
  arguments: Record<string, unknown> | string // a string only if the AI sent broken JSON
  result: string // what the tool sent back to the AI (shortened)
  is_error: boolean
  duration_ms: number
  held?: boolean // SMA-43: not run, waiting for your confirmation
}

/** Same fields as the backend's ChatReply. */
export type ChatReply = {
  conversation_id: string
  message_id: string // the saved answer's id: "Save as note" links to it (SMA-32)
  reply: string
  provider: string
  model: string
  mode: 'general' | 'tool' | 'grounded' // 'tool': used tools (SMA-42); 'grounded': documents (SMA-49)
  tool_calls: ToolCallOut[]
  actions: AgentAction[] // SMA-43: cards to confirm, creates to undo
  citations: Citation[] // SMA-49: empty on a grounded answer = not found
  fallback_used: boolean
  fallback_reason: string | null
  tokens_in: number
  tokens_out: number
  stopped?: boolean // SMA-62: the Stop button was pressed; `reply` is what arrived
}

/** Same fields as the backend's ConversationOut (only what we use so far). */
type Conversation = { id: string }

/** The answer while it is being written (SMA-62): its text so far and the tools used. */
export type LiveAnswer = { text: string; toolCalls: ToolCallOut[] }

/**
 * A streamed answer failed (SMA-62). messageId: the part that arrived WAS saved (cut off
 * halfway), so the chat should be reloaded, not the question given back to retry.
 */
export class StreamError extends ApiError {
  readonly messageId: string | null
  readonly conversationId: string

  constructor(code: string, message: string, messageId: string | null, conversationId: string) {
    super(503, code, message)
    this.name = 'StreamError'
    this.messageId = messageId
    this.conversationId = conversationId
  }
}

type StreamHandlers = { onToken: (text: string) => void; onTool: (call: ToolCallOut) => void }

/**
 * Send a message and read the answer as it is written (Server-Sent Events, SMA-62):
 * `token` pieces, `tool` steps, then `done` (the saved answer) or `error`.
 * If the server answers with plain JSON instead, that is the answer (as before SMA-62).
 */
export async function streamMessage(
  conversationId: string,
  body: Omit<ChatRequest, 'conversation_id'>,
  handlers: StreamHandlers,
): Promise<ChatReply> {
  const response = await fetch(`/api/conversations/${conversationId}/messages`, {
    method: 'POST',
    headers: {
      Accept: 'text/event-stream, application/json',
      'Content-Type': 'application/json',
      ...csrfHeader(),
    },
    body: JSON.stringify(body),
  })
  if (!response.ok) throw await toApiError(response) // checked before streaming: 404, 400...
  if (!response.headers.get('Content-Type')?.includes('text/event-stream') || !response.body) {
    return (await response.json()) as ChatReply
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  const splitter = new SseSplitter()
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    for (const { event, data } of splitter.push(decoder.decode(value, { stream: true }))) {
      const payload = JSON.parse(data)
      if (event === 'token') handlers.onToken(payload.text)
      else if (event === 'tool') handlers.onTool(payload as ToolCallOut)
      else if (event === 'done') return payload as ChatReply
      else if (event === 'error') {
        const { code, message } = payload.error
        throw new StreamError(code, message, payload.message_id ?? null, conversationId)
      }
    }
  }
  throw new ApiError(502, 'error', 'The answer ended without a result.')
}

/**
 * useMutation: for actions that change something (useQuery is for reading).
 * onConversationCreated: called as soon as a new conversation exists, BEFORE the AI
 * answers, so a failed answer can be retried in the same conversation.
 * SMA-62: `live` is the answer while it streams; `stop()` asks the server to stop it.
 */
export function useSendMessage(
  onConversationCreated?: (id: string) => void,
  newConversation: object = {}, // SMA-49: e.g. { mode: 'study', document_ids: [...] }
) {
  const queryClient = useQueryClient()
  const [live, setLive] = useState<LiveAnswer | null>(null)
  const answering = useRef<string | null>(null) // the conversation being answered

  const mutation = useMutation({
    mutationFn: async ({ conversation_id, ...body }: ChatRequest) => {
      let id = conversation_id
      if (!id) {
        id = (await apiPost<Conversation>('/api/conversations', newConversation)).id
        onConversationCreated?.(id)
      }
      answering.current = id
      setLive({ text: '', toolCalls: [] })
      return streamMessage(id, body, {
        onToken: (text) => setLive((now) => now && { ...now, text: now.text + text }),
        // A new turn starts after a tool: only the last turn's text is the answer.
        onTool: (call) =>
          setLive((now) => now && { text: '', toolCalls: [...now.toolCalls, call] }),
      })
    },
    // The chat moved to the top of "Recent chats" (SMA-31). Set here, not in mutate(),
    // so it still runs if the page changes before the answer arrives.
    onSettled: () => {
      answering.current = null
      setLive(null)
      return queryClient.invalidateQueries({ queryKey: LIST_KEY })
    },
  })

  /** The Stop button: the server ends the answer, saves what arrived and sends `done`. */
  function stop() {
    const id = answering.current
    if (id) apiPost(`/api/conversations/${id}/stop`, {}).catch(() => {}) // already finished: fine
  }

  return { ...mutation, live, stop }
}
