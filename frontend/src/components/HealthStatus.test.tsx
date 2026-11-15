// HealthStatus reads GET /api/health through the dev proxy. SMA-24 (test-first).
import { screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { HealthStatus } from '@/components/HealthStatus'
import { mockFetch, renderApp, renderWithQuery } from '@/test/render'

const HEALTHY = { status: 'ok', version: '0.1.0', env: 'development', auth_mode: 'local' }

describe('HealthStatus', () => {
  it('calls the relative path /api/health (the proxy forwards it)', async () => {
    const fetch = mockFetch(HEALTHY)

    renderWithQuery(<HealthStatus />)

    await screen.findByText('API online')
    expect(fetch).toHaveBeenCalledWith('/api/health', expect.anything())
  })

  it('says it is checking while waiting for the answer', () => {
    // A fetch that never answers, so the component stays in its loading state.
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise(() => {})),
    )

    renderWithQuery(<HealthStatus />)

    expect(screen.getByRole('status')).toHaveTextContent('Checking API…')
  })

  it('shows online, the version and the auth mode', async () => {
    mockFetch(HEALTHY)

    renderWithQuery(<HealthStatus />)

    const status = await screen.findByRole('status')
    await screen.findByText('API online')
    expect(status).toHaveTextContent('v0.1.0')
    expect(status).toHaveTextContent('local')
  })

  it('shows offline with the message from our error format', async () => {
    mockFetch({ error: { code: 'service_unavailable', message: 'Database is down' } }, 503)

    renderWithQuery(<HealthStatus />)

    expect(await screen.findByText('API offline')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Database is down')
  })

  it('shows offline when the backend is not running at all', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))),
    )

    renderWithQuery(<HealthStatus />)

    expect(await screen.findByText('API offline')).toBeInTheDocument()
  })

  it('is shown in the sidebar of the app shell', async () => {
    mockFetch(HEALTHY)

    renderApp('/')

    expect(await screen.findByText('API online')).toBeInTheDocument()
  })
})
