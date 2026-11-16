// Notes page (wireframe 6.7): list, search, open, edit, create, delete. SMA-32, test-first.
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { mockApi, renderApp } from '@/test/render'

const HEALTH = { body: { status: 'ok', version: '0.1.0', env: 'test', auth_mode: 'local' } }

type FakeNote = {
  id: string
  title: string
  content: string
  tags: string[]
  source: { message_id: string; conversation_id: string; conversation_title: string | null } | null
  created_at: string
  updated_at: string
}

function note(id: string, title: string, content: string, extra: Partial<FakeNote> = {}): FakeNote {
  return {
    id,
    title,
    content,
    tags: [],
    source: null,
    created_at: '2026-11-10T09:00:00Z',
    updated_at: '2026-11-10T09:00:00Z',
    ...extra,
  }
}

const NEWTON = note('n1', "Newton's 2nd law", 'F = m * a', {
  tags: ['physics', 'exam'],
  source: { message_id: 'm7', conversation_id: 'c3', conversation_title: 'Physics revision' },
})
const SQL = note('n2', 'SQL joins cheatsheet', 'INNER JOIN keeps matching rows')

/** A fake notes backend that remembers creates, edits and deletes. */
function notesBackend(initial: FakeNote[] = [NEWTON, SQL]) {
  let notes = [...initial]
  const byId = (id: string) => notes.find((n) => n.id === id)
  const routes: Parameters<typeof mockApi>[0] = {
    '/api/health': HEALTH,
    'GET /api/notes': async () => Response.json(notes),
    'GET /api/notes/search?q=newton': async () =>
      Response.json(notes.filter((n) => /newton/i.test(n.title + n.content))),
    'GET /api/notes/search?q=zebra': async () => Response.json([]),
    'POST /api/notes': async (init) => {
      const body = JSON.parse(String(init?.body))
      const created = note('n9', body.title, body.content, { tags: body.tags })
      notes = [created, ...notes]
      return Response.json(created, { status: 201 })
    },
  }
  for (const id of ['n1', 'n2', 'n9']) {
    routes[`GET /api/notes/${id}`] = async () =>
      byId(id)
        ? Response.json(byId(id))
        : Response.json(
            { error: { code: 'not_found', message: 'Note not found' } },
            { status: 404 },
          )
    routes[`PATCH /api/notes/${id}`] = async (init) => {
      const changes = JSON.parse(String(init?.body))
      notes = notes.map((n) => (n.id === id ? { ...n, ...changes } : n))
      return Response.json(byId(id))
    }
    routes[`DELETE /api/notes/${id}`] = async () => {
      notes = notes.filter((n) => n.id !== id)
      return new Response(null, { status: 204 })
    }
  }
  return mockApi(routes)
}

const noteList = () => screen.getByRole('navigation', { name: 'Notes list' })

function requests(fetch: ReturnType<typeof mockApi>, method: string) {
  return fetch.mock.calls
    .filter(([, init]) => init?.method === method)
    .map(([url, init]) => [url, init?.body ? JSON.parse(String(init.body)) : undefined])
}

describe('Notes page', () => {
  it('lists my notes and opens one with its tags and the chat it came from', async () => {
    notesBackend()
    renderApp('/notes')

    const links = await within(noteList()).findAllByRole('link')
    expect(links.map((l) => l.textContent)).toEqual(["Newton's 2nd law", 'SQL joins cheatsheet'])
    await userEvent.click(links[0])

    expect(await screen.findByRole('textbox', { name: 'Title' })).toHaveValue("Newton's 2nd law")
    expect(screen.getByRole('textbox', { name: 'Content' })).toHaveValue('F = m * a')
    expect(screen.getByRole('textbox', { name: 'Tags' })).toHaveValue('physics, exam')
    const from = screen.getByRole('link', { name: 'Physics revision' })
    expect(from).toHaveAttribute('href', '/c/c3')
    expect(from.parentElement).toHaveTextContent('From: Physics revision, 10 Nov')
  })

  it('searches as I type, and shows everything again when the search is cleared', async () => {
    const fetch = notesBackend()
    renderApp('/notes')
    await within(noteList()).findByRole('link', { name: 'SQL joins cheatsheet' })

    await userEvent.type(screen.getByRole('searchbox', { name: 'Search notes' }), 'newton')

    await waitFor(() =>
      expect(within(noteList()).queryByRole('link', { name: 'SQL joins cheatsheet' })).toBeNull(),
    )
    expect(within(noteList()).getByRole('link', { name: "Newton's 2nd law" })).toBeInTheDocument()
    // Waits for a pause in typing: one search request, not one per letter.
    expect(fetch.mock.calls.filter(([url]) => String(url).includes('/search'))).toHaveLength(1)

    await userEvent.clear(screen.getByRole('searchbox', { name: 'Search notes' }))
    expect(
      await within(noteList()).findByRole('link', { name: 'SQL joins cheatsheet' }),
    ).toBeInTheDocument()
  })

  it('says so when nothing matches', async () => {
    notesBackend()
    renderApp('/notes')

    await userEvent.type(screen.getByRole('searchbox', { name: 'Search notes' }), 'zebra')

    expect(await screen.findByText('No notes match “zebra”')).toBeInTheDocument()
  })

  it('edits a note and saves the title, content and tags', async () => {
    const fetch = notesBackend()
    renderApp('/notes/n2')
    const content = await screen.findByRole('textbox', { name: 'Content' })
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled() // nothing changed yet

    await userEvent.clear(content)
    await userEvent.type(content, 'LEFT JOIN keeps every left row')
    await userEvent.clear(screen.getByRole('textbox', { name: 'Tags' }))
    await userEvent.type(screen.getByRole('textbox', { name: 'Tags' }), 'sql, , dbms ')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    await screen.findByText('Note saved')
    expect(requests(fetch, 'PATCH')).toEqual([
      [
        '/api/notes/n2',
        {
          title: 'SQL joins cheatsheet',
          content: 'LEFT JOIN keeps every left row',
          tags: ['sql', 'dbms'],
        },
      ],
    ])
  })

  it('cannot save a note without a title', async () => {
    notesBackend()
    renderApp('/notes/n2')

    await userEvent.clear(await screen.findByRole('textbox', { name: 'Title' }))

    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })

  it('creates a new note', async () => {
    const fetch = notesBackend()
    renderApp('/notes')

    await userEvent.click(await screen.findByRole('link', { name: 'New note' }))
    await userEvent.type(screen.getByRole('textbox', { name: 'Title' }), 'Exam plan December')
    await userEvent.type(screen.getByRole('textbox', { name: 'Content' }), 'Revise ch. 3 on Friday')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    const created = await within(noteList()).findByRole('link', { name: 'Exam plan December' })
    await waitFor(() => expect(created).toHaveAttribute('aria-current', 'page')) // now open
    expect(requests(fetch, 'POST')).toEqual([
      ['/api/notes', { title: 'Exam plan December', content: 'Revise ch. 3 on Friday', tags: [] }],
    ])
  })

  it('deletes a note after confirming', async () => {
    const fetch = notesBackend()
    renderApp('/notes/n2')
    await userEvent.click(await screen.findByRole('button', { name: 'Delete' }))

    expect(screen.getByText('Delete this note?')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))

    await waitFor(() =>
      expect(within(noteList()).queryByRole('link', { name: 'SQL joins cheatsheet' })).toBeNull(),
    )
    expect(requests(fetch, 'DELETE')).toEqual([['/api/notes/n2', undefined]])
    expect(screen.getByText('Select a note, or create a new one.')).toBeInTheDocument()
  })

  it('Cancel keeps the note', async () => {
    const fetch = notesBackend()
    renderApp('/notes/n2')
    await userEvent.click(await screen.findByRole('button', { name: 'Delete' }))

    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(screen.queryByText('Delete this note?')).toBeNull()
    expect(requests(fetch, 'DELETE')).toEqual([])
  })

  it('says so when a note does not exist', async () => {
    notesBackend()
    renderApp('/notes/gone')

    expect(await screen.findByText(/This note doesn't exist/)).toBeInTheDocument()
  })
})
