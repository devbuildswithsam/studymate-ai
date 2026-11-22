// Progress dashboard: quizzes, flashcards, tasks and documents at a glance (SMA-65).
// Test-first.
import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { progressUrl } from '@/api/progress'
import { mockApi, renderApp } from '@/test/render'

const HEALTH = { body: { status: 'ok', version: '1.0.0', env: 'test', auth_mode: 'local' } }

const EMPTY = {
  quizzes: { attempts: 0, average_percent: null, history: [] },
  flashcards: { decks: 0, cards_reviewed: 0, cards_known: 0, reviews: 0 },
  tasks: { done_last_7_days: 0, open: 0, overdue: 0 },
  documents: { ready: 0, studied: 0 },
}

const BUSY = {
  quizzes: {
    attempts: 2,
    average_percent: 65,
    history: [
      { created_at: '2026-11-20T10:00:00Z', quiz_title: 'Entropy', score: 2, total: 5 },
      { created_at: '2026-11-21T10:00:00Z', quiz_title: 'Cells', score: 9, total: 10 },
    ],
  },
  flashcards: { decks: 2, cards_reviewed: 12, cards_known: 9, reviews: 30 },
  tasks: { done_last_7_days: 4, open: 3, overdue: 1 },
  documents: { ready: 5, studied: 2 },
}

describe('Progress page', () => {
  it('asks for the numbers with the browser date', () => {
    expect(progressUrl(new Date(2026, 0, 5, 23, 30))).toBe('/api/progress?today=2026-01-05')
  })

  it('shows every number', async () => {
    mockApi({ '/api/health': HEALTH, [progressUrl()]: { body: BUSY } })
    renderApp('/progress')

    const quizzes = await screen.findByRole('region', { name: 'Quizzes' })
    expect(quizzes).toHaveTextContent('65%')
    expect(quizzes).toHaveTextContent('2 attempts')
    const cards = screen.getByRole('region', { name: 'Flashcards' })
    expect(cards).toHaveTextContent('9 of 12')
    expect(cards).toHaveTextContent('2 decks')
    const tasks = screen.getByRole('region', { name: 'Tasks' })
    expect(tasks).toHaveTextContent('4')
    expect(tasks).toHaveTextContent('3 open')
    expect(tasks).toHaveTextContent('1 overdue')
    expect(screen.getByRole('region', { name: 'Documents' })).toHaveTextContent('2 of 5')
  })

  it('draws one bar per quiz attempt, with a table for screen readers', async () => {
    mockApi({ '/api/health': HEALTH, [progressUrl()]: { body: BUSY } })
    renderApp('/progress')

    const chart = await screen.findByRole('figure', { name: /quiz scores/i })
    expect(within(chart).getAllByTestId('bar')).toHaveLength(2)
    const rows = within(chart).getAllByRole('row')
    expect(rows[1]).toHaveTextContent('Entropy')
    expect(rows[1]).toHaveTextContent('2/5 (40%)')
    expect(rows[2]).toHaveTextContent('9/10 (90%)')
  })

  it('says how to get started when there is nothing yet', async () => {
    mockApi({ '/api/health': HEALTH, [progressUrl()]: { body: EMPTY } })
    renderApp('/progress')

    const quizzes = await screen.findByRole('region', { name: 'Quizzes' })
    expect(quizzes).toHaveTextContent('No quiz taken yet')
    expect(screen.queryByRole('figure')).not.toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Tasks' })).not.toHaveTextContent('overdue')
  })

  it('shows a friendly error when the numbers cannot be loaded', async () => {
    mockApi({
      '/api/health': HEALTH,
      [progressUrl()]: { status: 500, body: { error: { code: 'x', message: 'boom' } } },
    })
    renderApp('/progress')

    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })
})
