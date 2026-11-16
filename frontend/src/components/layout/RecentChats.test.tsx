// Sidebar "Recent chats": open, start new, rename, delete (wireframe 6.1). SMA-31, test-first.
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { mockApi, renderApp } from '@/test/render'

const HEALTH = { body: { status: 'ok', version: '0.1.0', env: 'test', auth_mode: 'local' } }

function conversation(id: string, title: string | null, model = 'gemini-3.5-flash') {
  return {
    id,
    title,
    provider: 'gemini',
    model,
    created_at: '2026-11-16T10:00:00Z',
    updated_at: '2026-11-16T10:00:00Z',
  }
}

const OSMOSIS = conversation('c1', 'Osmosis in Plant Roots')
const KREBS = conversation('c2', 'Krebs Cycle Steps')
const UNTITLED = conversation('c3', null)

/** A fake backend whose conversation list can change (rename, delete). */
function fakeBackend(initial = [OSMOSIS, KREBS, UNTITLED]) {
  let list = [...initial]
  const fetch = mockApi({
    '/api/health': HEALTH,
    'GET /api/conversations': async () => Response.json(list),
    ...Object.fromEntries(
      initial.flatMap((c) => [
        [`GET /api/conversations/${c.id}`, async () => Response.json({ ...c, messages: [] })],
        [
          `PATCH /api/conversations/${c.id}`,
          async (init?: RequestInit) => {
            const { title } = JSON.parse(String(init?.body))
            list = list.map((item) => (item.id === c.id ? { ...item, title } : item))
            return Response.json({ ...c, title })
          },
        ],
        [
          `DELETE /api/conversations/${c.id}`,
          async () => {
            list = list.filter((item) => item.id !== c.id)
            return new Response(null, { status: 204 })
          },
        ],
      ]),
    ),
  })
  return fetch
}

const recentChats = () => screen.getByRole('navigation', { name: 'Recent chats' })

/** Requests sent with this method, as [url, body]. */
function requests(fetch: ReturnType<typeof mockApi>, method: string) {
  return fetch.mock.calls
    .filter(([, init]) => init?.method === method)
    .map(([url, init]) => [url, init?.body ? JSON.parse(String(init.body)) : undefined])
}

describe('Recent chats in the sidebar', () => {
  it('lists my chats by title, with "Untitled chat" for one without a title yet', async () => {
    fakeBackend()
    renderApp('/')

    const links = await within(recentChats()).findAllByRole('link')

    expect(links.map((link) => [link.textContent, link.getAttribute('href')])).toEqual([
      ['Osmosis in Plant Roots', '/c/c1'],
      ['Krebs Cycle Steps', '/c/c2'],
      ['Untitled chat', '/c/c3'],
    ])
  })

  it('marks the open chat', async () => {
    fakeBackend()
    renderApp('/c/c2')

    const open = await within(recentChats()).findByRole('link', { name: 'Krebs Cycle Steps' })

    expect(open).toHaveAttribute('aria-current', 'page')
  })

  it('opens a chat when it is clicked', async () => {
    fakeBackend()
    renderApp('/')

    await userEvent.click(await screen.findByRole('link', { name: 'Krebs Cycle Steps' }))

    expect(screen.getByRole('link', { name: 'Krebs Cycle Steps' })).toHaveAttribute(
      'aria-current',
      'page',
    )
  })

  it('"New chat" leaves the open chat for an empty one', async () => {
    fakeBackend()
    renderApp('/c/c1')
    await within(recentChats()).findByRole('link', { name: 'Osmosis in Plant Roots' })

    await userEvent.click(screen.getByRole('link', { name: 'New chat' }))

    expect(screen.getByText(/Ask a study question to get started/)).toBeInTheDocument()
    expect(
      within(recentChats()).getByRole('link', { name: 'Osmosis in Plant Roots' }),
    ).not.toHaveAttribute('aria-current')
  })

  it('says so when the list cannot be loaded', async () => {
    mockApi({ '/api/health': HEALTH }) // GET /api/conversations -> 404
    renderApp('/')

    expect(await screen.findByText("Couldn't load your chats")).toBeInTheDocument()
  })
})

describe('Renaming a chat', () => {
  it('saves the new title with Enter', async () => {
    const fetch = fakeBackend()
    renderApp('/')
    await userEvent.click(await screen.findByRole('button', { name: 'Rename Krebs Cycle Steps' }))

    const input = screen.getByRole('textbox', { name: 'Chat title' })
    expect(input).toHaveValue('Krebs Cycle Steps')
    await userEvent.clear(input)
    await userEvent.type(input, '  Krebs cycle revision {Enter}')

    expect(
      await within(recentChats()).findByRole('link', { name: 'Krebs cycle revision' }),
    ).toBeInTheDocument()
    expect(requests(fetch, 'PATCH')).toEqual([
      ['/api/conversations/c2', { title: 'Krebs cycle revision' }],
    ])
  })

  it('Escape cancels without saving', async () => {
    const fetch = fakeBackend()
    renderApp('/')
    await userEvent.click(await screen.findByRole('button', { name: 'Rename Krebs Cycle Steps' }))

    await userEvent.type(screen.getByRole('textbox', { name: 'Chat title' }), ' extra{Escape}')

    expect(screen.queryByRole('textbox', { name: 'Chat title' })).toBeNull()
    expect(
      within(recentChats()).getByRole('link', { name: 'Krebs Cycle Steps' }),
    ).toBeInTheDocument()
    expect(requests(fetch, 'PATCH')).toEqual([])
  })

  it('an empty title is not saved', async () => {
    const fetch = fakeBackend()
    renderApp('/')
    await userEvent.click(await screen.findByRole('button', { name: 'Rename Krebs Cycle Steps' }))

    await userEvent.clear(screen.getByRole('textbox', { name: 'Chat title' }))
    await userEvent.keyboard('{Enter}')

    expect(requests(fetch, 'PATCH')).toEqual([])
    expect(
      within(recentChats()).getByRole('link', { name: 'Krebs Cycle Steps' }),
    ).toBeInTheDocument()
  })
})

describe('Deleting a chat', () => {
  it('asks first, and Cancel keeps the chat', async () => {
    const fetch = fakeBackend()
    renderApp('/')
    await userEvent.click(await screen.findByRole('button', { name: 'Delete Krebs Cycle Steps' }))

    expect(screen.getByText('Delete this chat?')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(screen.queryByText('Delete this chat?')).toBeNull()
    expect(requests(fetch, 'DELETE')).toEqual([])
  })

  it('deletes after confirming, and the chat leaves the list', async () => {
    const fetch = fakeBackend()
    renderApp('/')
    await userEvent.click(await screen.findByRole('button', { name: 'Delete Krebs Cycle Steps' }))

    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))

    await waitFor(() =>
      expect(within(recentChats()).queryByRole('link', { name: 'Krebs Cycle Steps' })).toBeNull(),
    )
    expect(requests(fetch, 'DELETE')).toEqual([['/api/conversations/c2', undefined]])
  })

  it('deleting the open chat goes back to an empty new chat', async () => {
    fakeBackend()
    renderApp('/c/c2')
    await userEvent.click(await screen.findByRole('button', { name: 'Delete Krebs Cycle Steps' }))

    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))

    expect(await screen.findByText(/Ask a study question to get started/)).toBeInTheDocument()
  })
})
