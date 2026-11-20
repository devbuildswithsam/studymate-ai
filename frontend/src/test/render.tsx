// Test helpers: render the app the way main.tsx does, but at any URL. SMA-24.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'

import { AppRoutes } from '@/App'
import { ME_KEY, type User } from '@/api/auth'
import { makeQueryClient } from '@/lib/queryClient'

/** Who renderApp starts as: local mode's one user, like the real app in local mode. */
export const LOCAL_USER: User = { id: 'local', email: 'local@studymate.dev', name: 'Local user' }

/** Render any component with a fresh query cache (no retries: fail fast in tests). */
export function renderWithQuery(ui: ReactNode, queryClient = testQueryClient()) {
  return {
    ...render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>),
    queryClient,
  }
}

function testQueryClient(): QueryClient {
  // The app's own cache setup (its 401 rule included), without retries.
  return makeQueryClient({ queries: { retry: false } })
}

/**
 * Render the whole app at `url`, the way main.tsx does.
 * `user`: who "who am I?" already knows at the start (SMA-59). The default is the local
 * user, so pages render at once as in local mode; `null` starts logged out.
 */
export function renderApp(url = '/', { user = LOCAL_USER }: { user?: User | null } = {}) {
  const queryClient = testQueryClient()
  if (user) queryClient.setQueryData(ME_KEY, user)
  return renderWithQuery(
    <MemoryRouter initialEntries={[url]}>
      <AppRoutes />
    </MemoryRouter>,
    queryClient,
  )
}

type FakeRoute = { status?: number; body: unknown } | ((init?: RequestInit) => Promise<Response>)

/**
 * Replace fetch with a fake backend: one answer per path, e.g.
 * mockApi({ '/api/health': { body: {...} }, 'POST /api/conversations': { body: {...} } }).
 * A key with a method ("POST /api/...") only matches that method and wins over a plain
 * path (SMA-31: GET and POST /api/conversations do different things).
 * A function route can build its own Response (or reject, like a dead server).
 * Unknown paths answer 404 in our error format.
 */
export function mockApi(routes: Record<string, FakeRoute>) {
  // SMA-59: the app asks "who am I?" on every page. Unless a test says otherwise, the
  // answer is the local user, as in local mode.
  const all: Record<string, FakeRoute> = { '/api/auth/me': { body: LOCAL_USER }, ...routes }
  const fake = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    const route = all[`${method} ${String(input)}`] ?? all[String(input)]
    if (typeof route === 'function') return route(init)
    if (route) return Response.json(route.body, { status: route.status ?? 200 })
    return Response.json({ error: { code: 'not_found', message: 'Not Found' } }, { status: 404 })
  })
  vi.stubGlobal('fetch', fake)
  return fake
}

/** Replace the browser's fetch with a fake that answers `body` with `status`. */
export function mockFetch(body: unknown, status = 200) {
  const fake = vi.fn(async () => Response.json(body, { status }))
  vi.stubGlobal('fetch', fake)
  return fake
}
