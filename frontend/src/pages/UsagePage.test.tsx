// Admin usage: AI calls, failures and tokens per day and model (SMA-68). Test-first.
import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { LOCAL_USER, mockApi, renderApp } from '@/test/render'

const HEALTH = { body: { status: 'ok', version: '1.0.0', env: 'test', auth_mode: 'jwt' } }
const ADMIN = { ...LOCAL_USER, is_admin: true }
const STUDENT = { ...LOCAL_USER, is_admin: false }

const USAGE = {
  days: 30,
  rows: [
    {
      day: '2026-11-21',
      provider: 'groq',
      model: 'openai/gpt-oss-120b',
      calls: 12,
      failures: 2,
      tokens_in: 9000,
      tokens_out: 1500,
    },
    {
      day: '2026-11-20',
      provider: 'gemini',
      model: 'gemini-3.5-flash',
      calls: 3,
      failures: 0,
      tokens_in: 400,
      tokens_out: 120,
    },
  ],
  totals: { calls: 15, failures: 2, tokens_in: 9400, tokens_out: 1620 },
}

describe('Usage page (admin)', () => {
  it('shows one row per day and model, and the totals', async () => {
    mockApi({
      '/api/health': HEALTH,
      '/api/auth/me': { body: ADMIN },
      '/api/admin/usage?days=30': { body: USAGE },
    })
    renderApp('/admin/usage', { user: ADMIN })

    expect(await screen.findByRole('heading', { level: 1, name: 'AI usage' })).toBeInTheDocument()
    await screen.findByRole('table') // the numbers arrive after the heading
    const rows = screen.getAllByRole('row')
    expect(rows[1]).toHaveTextContent('2026-11-21')
    expect(rows[1]).toHaveTextContent('openai/gpt-oss-120b')
    expect(
      within(rows[1])
        .getAllByRole('cell')
        .map((c) => c.textContent),
    ).toEqual(['2026-11-21', 'openai/gpt-oss-120b', '12', '2', '9,000', '1,500'])
    expect(rows[rows.length - 1]).toHaveTextContent('Total')
    expect(rows[rows.length - 1]).toHaveTextContent('15')
    expect(screen.getByText(/last 30 days/)).toBeInTheDocument()
  })

  it('tells a non-admin they cannot see it', async () => {
    mockApi({
      '/api/health': HEALTH,
      '/api/auth/me': { body: STUDENT },
      '/api/admin/usage?days=30': {
        status: 403,
        body: { error: { code: 'forbidden', message: 'Only an admin can see this page.' } },
      },
    })
    renderApp('/admin/usage', { user: STUDENT })

    expect(await screen.findByRole('alert')).toHaveTextContent('Only an admin can see this page.')
  })

  it('is linked from Settings for admins only', async () => {
    mockApi({ '/api/health': HEALTH, '/api/auth/me': { body: ADMIN }, '/api/tokens': { body: [] } })
    const { unmount } = renderApp('/settings', { user: ADMIN })
    expect(await screen.findByRole('link', { name: 'AI usage (admin)' })).toHaveAttribute(
      'href',
      '/admin/usage',
    )
    unmount()

    mockApi({
      '/api/health': HEALTH,
      '/api/auth/me': { body: STUDENT },
      '/api/tokens': { body: [] },
    })
    renderApp('/settings', { user: STUDENT })
    await screen.findByRole('heading', { level: 1, name: 'Settings' })
    expect(screen.queryByRole('link', { name: 'AI usage (admin)' })).not.toBeInTheDocument()
  })
})
