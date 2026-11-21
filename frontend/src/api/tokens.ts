// Personal access tokens for MCP clients (backend: app/api/tokens.py). SMA-61.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiDelete, apiGet, apiPost } from '@/api/client'

/** Same fields as the backend's TokenOut. The token itself is never here. */
export type AccessToken = {
  id: string
  name: string
  prefix: string // "smat_AbCdEfG": enough to recognise it
  created_at: string
  expires_at: string
  last_used_at: string | null
}

/** Only the answer to "create" holds the token: shown once, then forgotten. */
export type NewAccessToken = AccessToken & { token: string }

export const EXPIRY_CHOICES = [
  { days: 30, label: '30 days' },
  { days: 90, label: '90 days' },
  { days: 365, label: '1 year' },
] as const

const TOKENS_KEY = ['tokens'] as const

export function useTokens() {
  return useQuery({ queryKey: TOKENS_KEY, queryFn: () => apiGet<AccessToken[]>('/api/tokens') })
}

export function useCreateToken() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { name: string; expires_in_days: number }) =>
      apiPost<NewAccessToken>('/api/tokens', body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: TOKENS_KEY }),
  })
}

export function useRevokeToken() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/api/tokens/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: TOKENS_KEY }),
  })
}
