// Test helpers: render the app the way main.tsx does, but at any URL. SMA-24.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'

import { AppRoutes } from '@/App'

/** Render any component with a fresh query cache (no retries: fail fast in tests). */
export function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

/** Render the whole app at `url`, the way main.tsx does. */
export function renderApp(url = '/') {
  return renderWithQuery(
    <MemoryRouter initialEntries={[url]}>
      <AppRoutes />
    </MemoryRouter>,
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
  const fake = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    const route = routes[`${method} ${String(input)}`] ?? routes[String(input)]
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
