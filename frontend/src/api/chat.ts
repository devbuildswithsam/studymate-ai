// POST /api/chat (backend: app/api/chat.py). SMA-25.
import { useMutation } from '@tanstack/react-query'

import { apiPost } from '@/api/client'

/** Same fields as the backend's ChatRequest. */
export type ChatRequest = {
  message: string
  conversation_id?: string // leave out to start a new conversation
  model?: string
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

/** useMutation: for actions that change something (useQuery is for reading). */
export function useSendMessage() {
  return useMutation({
    mutationFn: (request: ChatRequest) => apiPost<ChatReply>('/api/chat', request),
  })
}
