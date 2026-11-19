// Saved conversations (backend: app/api/conversations.py). SMA-31.
import { type QueryClient, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { AgentAction } from '@/api/actions'
import type { ChatReply, Citation, ToolCallOut } from '@/api/chat'
import { ApiError, apiDelete, apiGet, apiPatch, apiPost } from '@/api/client'

/** Same fields as the backend's ConversationOut: one row of the sidebar. */
export type ConversationSummary = {
  id: string
  title: string | null // null until the AI names it after the first answer
  provider: string | null
  model: string | null // the model this chat last used: reopening it picks it again
  mode?: 'general' | 'study' // SMA-49: study chats open on the Study page
  created_at: string
  updated_at: string
}

/** A document a study chat may search (SMA-49). */
export type DocumentRef = { id: string; filename: string }

/** Same fields as the backend's MessageOut. */
export type SavedMessage = {
  id: string
  role: 'user' | 'assistant' | 'tool'
  content: string
  provider: string | null
  model: string | null
  mode: string | null
  fallback_used: boolean
  tokens_in: number | null
  tokens_out: number | null
  tool_calls?: ToolCallOut[] | null // SMA-42: the tools used for this answer
  actions?: AgentAction[] // SMA-43: confirmation cards and Undo
  citations?: Citation[] | null // SMA-49: a study answer's sources ([] = not found)
  created_at: string
  fallback_reason?: string | null // only known for answers given while the page is open
}

export type ConversationDetail = ConversationSummary & {
  messages: SavedMessage[]
  documents?: DocumentRef[] // SMA-49: study chats only
}

// Two separate keys on purpose: refreshing the sidebar list must not refetch the open chat.
export const LIST_KEY = ['conversation-list'] as const
export const detailKey = (id: string) => ['conversation', id] as const

/** The sidebar list, most recent activity first. */
export function useConversations() {
  return useQuery({
    queryKey: LIST_KEY,
    queryFn: () => apiGet<ConversationSummary[]>('/api/conversations'),
  })
}

/**
 * One chat with its messages. `undefined` = a new chat: nothing to load.
 * load: false = only read what is already cached, never fetch.
 */
export function useConversation(id: string | undefined, { load = true } = {}) {
  return useQuery({
    queryKey: detailKey(id ?? ''),
    queryFn: () => apiGet<ConversationDetail>(`/api/conversations/${id}`),
    enabled: id !== undefined && load,
    // The chat page adds each new turn to the cache itself, so it never needs a refetch.
    staleTime: Infinity,
    // A 404 won't fix itself (deleted chat, wrong link): show it at once, don't retry.
    retry: (failures, error) =>
      !(error instanceof ApiError && error.status === 404) && failures < 3,
  })
}

/** Add a question and its answer to the open chat's cached messages. */
export function addTurn(
  queryClient: QueryClient,
  conversationId: string,
  question: string,
  reply: ChatReply,
  model: string | undefined, // the model the message was sent with: the backend saves it too
) {
  const now = new Date().toISOString()
  queryClient.setQueryData<ConversationDetail>(detailKey(conversationId), (old) => {
    const chat: ConversationDetail = old ?? {
      id: conversationId,
      title: null,
      provider: null,
      model: null,
      created_at: now,
      updated_at: now,
      messages: [],
    }
    const turn = chat.messages.length // gives each new message a unique local id
    const empty = { provider: null, model: null, mode: null, tokens_in: null, tokens_out: null }
    return {
      ...chat,
      model: model ?? chat.model,
      updated_at: now,
      messages: [
        ...chat.messages,
        {
          ...empty,
          id: `${conversationId}-q${turn}`,
          role: 'user',
          content: question,
          fallback_used: false,
          created_at: now,
        },
        {
          id: reply.message_id, // the real id, so "Save as note" can point to it
          role: 'assistant',
          content: reply.reply,
          provider: reply.provider,
          model: reply.model,
          mode: reply.mode,
          fallback_used: reply.fallback_used,
          fallback_reason: reply.fallback_reason,
          tokens_in: reply.tokens_in,
          tokens_out: reply.tokens_out,
          tool_calls: reply.tool_calls,
          actions: reply.actions,
          citations: reply.mode === 'grounded' ? reply.citations : null,
          created_at: now,
        },
      ],
    }
  })
}

/**
 * Ask the AI to name a chat after its first answer, then refresh the sidebar.
 * A plain function, not a hook: it keeps going even if the page that started it changes.
 */
export async function requestTitle(queryClient: QueryClient, conversationId: string) {
  try {
    const named = await apiPost<ConversationSummary>(
      `/api/conversations/${conversationId}/title`,
      {},
    )
    queryClient.setQueryData<ConversationDetail>(
      detailKey(conversationId),
      (old) => old && { ...old, title: named.title },
    )
  } catch {
    // A title is nice to have: "Untitled chat" is fine if this fails.
  }
  await queryClient.invalidateQueries({ queryKey: LIST_KEY })
}

export function useRenameConversation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      apiPatch<ConversationSummary>(`/api/conversations/${id}`, { title }),
    onSuccess: (renamed) => {
      queryClient.setQueryData<ConversationDetail>(
        detailKey(renamed.id),
        (old) => old && { ...old, title: renamed.title },
      )
      return queryClient.invalidateQueries({ queryKey: LIST_KEY })
    },
  })
}

export function useDeleteConversation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/api/conversations/${id}`),
    onSuccess: (_nothing, id) => {
      queryClient.removeQueries({ queryKey: detailKey(id) })
      return queryClient.invalidateQueries({ queryKey: LIST_KEY })
    },
  })
}
