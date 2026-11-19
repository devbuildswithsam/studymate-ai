// Chat messages, saved by the backend (app/api/conversations.py). SMA-25, SMA-30.
import { useMutation, useQueryClient } from '@tanstack/react-query'

import type { AgentAction } from '@/api/actions'
import { apiPost } from '@/api/client'
import { LIST_KEY } from '@/api/conversations'

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
}

/** Same fields as the backend's ConversationOut (only what we use so far). */
type Conversation = { id: string }

/**
 * useMutation: for actions that change something (useQuery is for reading).
 * onConversationCreated: called as soon as a new conversation exists, BEFORE the AI
 * answers, so a failed answer can be retried in the same conversation.
 */
export function useSendMessage(
  onConversationCreated?: (id: string) => void,
  newConversation: object = {}, // SMA-49: e.g. { mode: 'study', document_ids: [...] }
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ conversation_id, ...body }: ChatRequest) => {
      let id = conversation_id
      if (!id) {
        id = (await apiPost<Conversation>('/api/conversations', newConversation)).id
        onConversationCreated?.(id)
      }
      return apiPost<ChatReply>(`/api/conversations/${id}/messages`, body)
    },
    // The chat moved to the top of "Recent chats" (SMA-31). Set here, not in mutate(),
    // so it still runs if the page changes before the answer arrives.
    onSettled: () => queryClient.invalidateQueries({ queryKey: LIST_KEY }),
  })
}
