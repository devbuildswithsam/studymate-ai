// The AI's writes: confirmation cards and Undo (backend: app/api/actions.py). SMA-43.
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { apiPost } from '@/api/client'
import { type ConversationDetail, detailKey } from '@/api/conversations'

/** Same fields as the backend's ActionOut. */
export type AgentAction = {
  id: string
  tool: string // e.g. "complete_task"
  kind: 'create' | 'change'
  status: 'pending' | 'done' | 'cancelled' | 'failed' | 'undone'
  summary: string // "Mark 'Revise ch.3' as done"
  error: string | null // why a confirmed action failed
}

export type ActionVerb = 'confirm' | 'cancel' | 'undo'

/**
 * Confirm, cancel or undo one action of the open chat. The answer's card is updated in
 * the cached chat (no refetch). The Tasks and Notes pages reload their lists whenever
 * they open, so they show the change without any extra code here.
 */
export function useAgentAction(conversationId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ action, verb }: { action: AgentAction; verb: ActionVerb }) =>
      apiPost<AgentAction>(`/api/actions/${action.id}/${verb}`, {}),
    onSuccess: (updated) => {
      if (!conversationId) return
      queryClient.setQueryData<ConversationDetail>(
        detailKey(conversationId),
        (old) =>
          old && {
            ...old,
            messages: old.messages.map((m) => ({
              ...m,
              actions: m.actions?.map((a) => (a.id === updated.id ? updated : a)),
            })),
          },
      )
    },
  })
}
