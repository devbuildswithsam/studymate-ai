// Chat messages, saved by the backend (app/api/conversations.py). SMA-25, SMA-30.
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { apiPost } from '@/api/client'
import { LIST_KEY } from '@/api/conversations'

/** What the chat page sends. Without conversation_id, a new conversation is started. */
export type ChatRequest = {
  message: string
  conversation_id?: string
  model?: string
  allow_fallback?: boolean // SMA-26: false = only the chosen model may answer
}

/** Same fields as the backend's ChatReply. */
export type ChatReply = {
  conversation_id: string
  reply: string
  provider: string
  model: string
  mode: 'general'
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
export function useSendMessage(onConversationCreated?: (id: string) => void) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ conversation_id, ...body }: ChatRequest) => {
      let id = conversation_id
      if (!id) {
        id = (await apiPost<Conversation>('/api/conversations', {})).id
        onConversationCreated?.(id)
      }
      return apiPost<ChatReply>(`/api/conversations/${id}/messages`, body)
    },
    // The chat moved to the top of "Recent chats" (SMA-31). Set here, not in mutate(),
    // so it still runs if the page changes before the answer arrives.
    onSettled: () => queryClient.invalidateQueries({ queryKey: LIST_KEY }),
  })
}
