// Accounts (backend: app/api/auth.py, ADR-0009). SMA-59.
// The session itself is an HttpOnly cookie: this code never sees it. It only asks the
// backend "who am I?" and reacts to the answer.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'

import { ApiError, apiGet, apiPost } from '@/api/client'

/** Same fields as the backend's UserOut. */
export type User = { id: string; email: string; name: string | null }

export const ME_KEY = ['me'] as const

/** Is this the backend saying "not logged in" (no cookie, or it expired)? */
export function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401
}

/**
 * GET /api/auth/me: the signed-in user. In local mode always the local user; in jwt mode
 * a 401 means "nobody", so it isn't retried.
 */
export function useMe() {
  return useQuery({
    queryKey: ME_KEY,
    queryFn: () => apiGet<User>('/api/auth/me'),
    retry: false,
  })
}

/** After login or register: forget everything cached, then remember who's in. The cache
 * may hold the previous person's chats and notes; none of it may leak. "Who am I?" is
 * overwritten rather than removed, so components already showing it update at once. */
function useStartAs() {
  const queryClient = useQueryClient()
  return (user: User) => {
    queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== ME_KEY[0] })
    queryClient.setQueryData(ME_KEY, user)
  }
}

export function useLogin() {
  const startAs = useStartAs()
  return useMutation({
    mutationFn: (body: { email: string; password: string }) =>
      apiPost<User>('/api/auth/login', body),
    onSuccess: startAs,
  })
}

export function useRegister() {
  const startAs = useStartAs()
  return useMutation({
    mutationFn: (body: { email: string; password: string; name?: string }) =>
      apiPost<User>('/api/auth/register', body),
    onSuccess: startAs,
  })
}

/**
 * Logout, then go to Login. Everything cached is forgotten, "who am I?" included, even if
 * the request fails (server down): this browser keeps nothing of the user's.
 * Navigating is part of it: the page on screen still holds the old "who am I?" answer,
 * while the Login page asks again and gets "nobody".
 */
export function useLogout() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  return useMutation({
    mutationFn: () => apiPost<void>('/api/auth/logout', {}),
    onSettled: () => {
      queryClient.removeQueries()
      void navigate('/login', { replace: true })
    },
  })
}
