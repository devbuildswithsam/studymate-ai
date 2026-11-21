// Settings: personal access tokens for MCP clients (SMA-61). Test-first.
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { AccessToken } from '@/api/tokens'
import { mockApi, renderApp } from '@/test/render'

const NOW = Date.now()
const days = (n: number) => new Date(NOW + n * 24 * 60 * 60 * 1000).toISOString()

function token(id: string, name: string, extra: Partial<AccessToken> = {}): AccessToken {
  return {
    id,
    name,
    prefix: `smat_${id}abcdef`.slice(0, 12),
    created_at: days(-10),
    expires_at: days(80),
    last_used_at: null,
    ...extra,
  }
}

const INSPECTOR = token('t1', 'MCP Inspector', { last_used_at: days(-1) })
const OLD = token('t2', 'Old laptop', { expires_at: days(-2) })
const SECRET = 'smat_' + 'S'.repeat(43)

/** A fake tokens backend that remembers creates and revokes. */
function tokensBackend(initial: AccessToken[] = [INSPECTOR, OLD], mode = 'jwt') {
  const state = { tokens: [...initial], created: [] as unknown[], revoked: [] as string[] }
  const fetch = mockApi({
    '/api/health': { body: { status: 'ok', version: '1.0.0', env: 'test', auth_mode: mode } },
    '/api/conversations': { body: [] },
    'GET /api/tokens': async () => Response.json(state.tokens),
    'POST /api/tokens': async (init) => {
      const body = JSON.parse(String(init?.body))
      state.created.push(body)
      const made = token('t9', body.name)
      state.tokens = [made, ...state.tokens]
      return Response.json({ ...made, token: SECRET }, { status: 201 })
    },
    'DELETE /api/tokens/t1': async () => {
      state.revoked.push('t1')
      state.tokens = state.tokens.filter((t) => t.id !== 't1')
      return new Response(null, { status: 204 })
    },
  })
  return { state, fetch }
}

describe('Settings: access tokens', () => {
  it('lists my tokens with their prefix, use and expiry', async () => {
    tokensBackend()
    renderApp('/settings')

    const inspector = await screen.findByRole('listitem', { name: 'MCP Inspector' })
    expect(within(inspector).getByText(/smat_t1abcde/)).toBeVisible()
    expect(within(inspector).getByText(/last used/i)).toBeVisible()
    const old = screen.getByRole('listitem', { name: 'Old laptop' })
    expect(within(old).getByText('Expired')).toBeVisible()
    expect(within(old).getByText(/never used/i)).toBeVisible()
  })

  it('creates a token and shows it once, with a warning and a copy button', async () => {
    const { state } = tokensBackend([])
    renderApp('/settings')

    await userEvent.type(await screen.findByLabelText('Token name'), 'Claude Desktop')
    await userEvent.selectOptions(screen.getByLabelText('Expires after'), '30')
    await userEvent.click(screen.getByRole('button', { name: 'Create token' }))

    expect(await screen.findByText(SECRET)).toBeVisible()
    expect(screen.getByText(/won't be able to see it again/i)).toBeVisible()
    expect(screen.getByRole('button', { name: 'Copy token' })).toBeInTheDocument()
    expect(state.created).toEqual([{ name: 'Claude Desktop', expires_in_days: 30 }])
    expect(await screen.findByRole('listitem', { name: 'Claude Desktop' })).toBeVisible()

    await userEvent.click(screen.getByRole('button', { name: "I've copied it" }))
    expect(screen.queryByText(SECRET)).not.toBeInTheDocument() // gone for good
  })

  it('revokes a token', async () => {
    const { state } = tokensBackend()
    renderApp('/settings')

    const inspector = await screen.findByRole('listitem', { name: 'MCP Inspector' })
    await userEvent.click(within(inspector).getByRole('button', { name: 'Revoke' }))

    expect(state.revoked).toEqual(['t1'])
    await waitFor(() =>
      expect(screen.queryByRole('listitem', { name: 'MCP Inspector' })).not.toBeInTheDocument(),
    )
  })

  it('shows why a token could not be made', async () => {
    mockApi({
      'GET /api/tokens': { body: [] },
      'POST /api/tokens': {
        status: 409,
        body: { error: { code: 'conflict', message: 'You already have 10 tokens.' } },
      },
    })
    renderApp('/settings')

    await userEvent.type(await screen.findByLabelText('Token name'), 'One more')
    await userEvent.click(screen.getByRole('button', { name: 'Create token' }))

    expect(await screen.findByText('You already have 10 tokens.')).toBeVisible()
  })

  it('says that local mode needs no token', async () => {
    tokensBackend([], 'local')
    renderApp('/settings')

    expect(await screen.findByText(/local mode.*no token/i)).toBeVisible()
  })

  it('is reachable from the sidebar', async () => {
    tokensBackend()
    renderApp('/')

    await userEvent.click(await screen.findByRole('link', { name: 'Settings' }))

    expect(await screen.findByRole('heading', { level: 1, name: 'Settings' })).toBeVisible()
  })
})
