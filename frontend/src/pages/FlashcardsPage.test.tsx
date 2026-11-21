// Flashcards: decks from a document or a chat answer, and reviewing them (SMA-64).
// Test-first.
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { mockApi, renderApp } from '@/test/render'

const HEALTH = { body: { status: 'ok', version: '1.0.0', env: 'test', auth_mode: 'local' } }

const DECK = {
  id: 'k1',
  title: 'Entropy',
  source_type: 'answer',
  source_name: 'Thermodynamics revision',
  created_at: '2026-11-21T10:00:00Z',
  card_count: 2,
  reviewed: 0,
  known: 0,
  cards: [
    { front: 'What does entropy measure?', back: 'Disorder.', page: null, last: null },
    { front: 'In an isolated system, entropy…', back: 'Always increases.', page: 3, last: null },
  ],
}

function summary(extra: object = {}) {
  const { cards, ...rest } = DECK
  void cards
  return { ...rest, ...extra }
}

describe('Flashcards page', () => {
  it('makes a deck from a ready document and opens it', async () => {
    const fetch = mockApi({
      '/api/health': HEALTH,
      '/api/documents': {
        body: [
          {
            id: 'd1',
            filename: 'Physics.pdf',
            mime_type: 'application/pdf',
            size_bytes: 10,
            page_count: 3,
            status: 'ready',
            error: null,
            summary: null,
            key_points: null,
            created_at: '2026-11-21T09:00:00Z',
            can_retry: false,
          },
        ],
      },
      'GET /api/decks': { body: [] },
      'POST /api/decks': { status: 201, body: DECK },
      '/api/decks/k1': { body: DECK },
    })
    renderApp('/flashcards')

    await screen.findByRole('option', { name: 'Physics.pdf' })
    await userEvent.click(screen.getByRole('button', { name: 'Make flashcards' }))

    expect(await screen.findByRole('heading', { level: 1, name: 'Entropy' })).toBeVisible()
    const [, init] = fetch.mock.calls.find(
      ([url, i]) => url === '/api/decks' && i?.method === 'POST',
    )!
    expect(JSON.parse(String(init?.body))).toEqual({ document_id: 'd1' })
  })

  it('lists my decks with how many cards I know', async () => {
    mockApi({
      '/api/health': HEALTH,
      '/api/documents': { body: [] },
      'GET /api/decks': { body: [summary({ reviewed: 2, known: 1 })] },
    })
    renderApp('/flashcards')

    const deck = await screen.findByRole('listitem', { name: 'Entropy' })
    expect(within(deck).getByText(/known 1\/2/i)).toBeVisible()
    expect(within(deck).getByText(/Thermodynamics revision/)).toBeVisible()
  })

  it('is in the sidebar', async () => {
    mockApi({
      '/api/health': HEALTH,
      '/api/documents': { body: [] },
      'GET /api/decks': { body: [] },
    })
    renderApp('/')

    await userEvent.click(screen.getByRole('link', { name: 'Flashcards' }))

    expect(await screen.findByRole('heading', { level: 1, name: 'Flashcards' })).toBeVisible()
  })
})

describe('Reviewing a deck', () => {
  function backend() {
    return mockApi({
      '/api/health': HEALTH,
      '/api/decks/k1': { body: DECK },
      'POST /api/decks/k1/reviews': { status: 201, body: { card_count: 2, reviewed: 1, known: 1 } },
    })
  }

  it('shows the front, flips to the back, and saves "knew it"', async () => {
    const fetch = backend()
    renderApp('/flashcards/k1')

    expect(await screen.findByText('Card 1 of 2')).toBeVisible()
    expect(screen.getByText('What does entropy measure?')).toBeVisible()
    expect(screen.queryByText('Disorder.')).not.toBeInTheDocument() // the back is hidden

    await userEvent.click(screen.getByRole('button', { name: 'Show answer' }))
    expect(screen.getByText('Disorder.')).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: 'Knew it' }))

    expect(await screen.findByText('Card 2 of 2')).toBeVisible()
    const [, init] = fetch.mock.calls.find(([url]) => String(url).endsWith('/reviews'))!
    expect(JSON.parse(String(init?.body))).toEqual({ card: 0, knew: true })
  })

  it('shows the page a card comes from, and a score at the end', async () => {
    backend()
    renderApp('/flashcards/k1')
    await userEvent.click(await screen.findByRole('button', { name: 'Show answer' }))
    await userEvent.click(screen.getByRole('button', { name: 'Knew it' }))

    await userEvent.click(await screen.findByRole('button', { name: 'Show answer' }))
    expect(screen.getByText(/p\. 3/)).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: "Didn't know" }))

    expect(await screen.findByText('You knew 1 of 2')).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: 'Review again' }))
    expect(screen.getByText('Card 1 of 2')).toBeVisible()
  })
})

describe('"Make flashcards" under a chat answer', () => {
  it('makes a deck from that answer and offers to open it', async () => {
    const fetch = mockApi({
      '/api/health': HEALTH,
      'POST /api/conversations': { status: 201, body: { id: 'conv-1' } },
      '/api/conversations/conv-1/messages': {
        body: {
          conversation_id: 'conv-1',
          message_id: 'answer-1',
          reply: 'Entropy measures disorder.',
          provider: 'groq',
          model: 'openai/gpt-oss-120b',
          mode: 'general',
          tool_calls: [],
          actions: [],
          citations: [],
          fallback_used: false,
          fallback_reason: null,
          tokens_in: 5,
          tokens_out: 5,
        },
      },
      'POST /api/conversations/conv-1/title': { body: { id: 'conv-1', title: 'Entropy' } },
      'POST /api/decks': { status: 201, body: DECK },
      '/api/decks/k1': { body: DECK },
    })
    renderApp('/')
    await userEvent.type(
      screen.getByRole('textbox', { name: 'Message' }),
      'What is entropy?{Enter}',
    )

    await userEvent.click(await screen.findByRole('button', { name: 'Make flashcards' }))

    await waitFor(() => {
      const posted = fetch.mock.calls.find(
        ([url, i]) => url === '/api/decks' && i?.method === 'POST',
      )
      expect(JSON.parse(String(posted?.[1]?.body))).toEqual({ message_id: 'answer-1' })
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Open' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Entropy' })).toBeVisible()
  })
})
