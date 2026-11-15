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

/** Replace the browser's fetch with a fake that answers `body` with `status`. */
export function mockFetch(body: unknown, status = 200) {
  const fake = vi.fn(async () => Response.json(body, { status }))
  vi.stubGlobal('fetch', fake)
  return fake
}
