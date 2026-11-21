// Quizzes: make one from a document, take it, see the score and explanations (SMA-63).
// Test-first. The right answers come from the server only after an attempt.
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { mockApi, renderApp } from '@/test/render'

const HEALTH = { body: { status: 'ok', version: '1.0.0', env: 'test', auth_mode: 'local' } }

function document(id: string, filename: string, status = 'ready') {
  return {
    id,
    filename,
    mime_type: 'application/pdf',
    size_bytes: 1000,
    page_count: 3,
    status,
    error: null,
    summary: null,
    key_points: null,
    created_at: '2026-11-21T09:00:00Z',
    can_retry: false,
  }
}

const QUIZ = {
  id: 'q1',
  title: 'Photosynthesis',
  document_id: 'd1',
  document_name: 'Photosynthesis.pdf',
  created_at: '2026-11-21T10:00:00Z',
  questions: [
    {
      question: 'Why do plants look green?',
      options: ['They reflect green', 'They absorb green', 'Soil', 'Water'],
      page: 4,
    },
    { question: 'What is released?', options: ['Nitrogen', 'Oxygen', 'Helium', 'Argon'], page: 2 },
  ],
}

const RESULT = {
  id: 'a1',
  score: 1,
  total: 2,
  results: [
    {
      chosen: 0,
      correct_answer: 0,
      is_correct: true,
      explanation: 'Chlorophyll reflects green light.',
      page: 4,
    },
    {
      chosen: 0,
      correct_answer: 1,
      is_correct: false,
      explanation: 'Water is split, releasing oxygen.',
      page: 2,
    },
  ],
}

function summary(extra: object = {}) {
  return {
    id: 'q1',
    title: 'Photosynthesis',
    document_id: 'd1',
    document_name: 'Photosynthesis.pdf',
    created_at: '2026-11-21T10:00:00Z',
    question_count: 2,
    attempts: 0,
    best_score: null,
    last_score: null,
    ...extra,
  }
}

describe('Quizzes page', () => {
  it('makes a quiz from a ready document and opens it', async () => {
    const fetch = mockApi({
      '/api/health': HEALTH,
      '/api/documents': {
        body: [document('d1', 'Photosynthesis.pdf'), document('d2', 'Busy.pdf', 'processing')],
      },
      'GET /api/quizzes': { body: [] },
      'POST /api/quizzes': { status: 201, body: QUIZ },
      '/api/quizzes/q1': { body: QUIZ },
    })
    renderApp('/quizzes')

    const picker = await screen.findByLabelText('Document')
    await waitFor(() => expect(within(picker).getAllByRole('option')).toHaveLength(1)) // ready only
    await userEvent.selectOptions(screen.getByLabelText('Questions'), '10')
    await userEvent.click(screen.getByRole('button', { name: 'Make quiz' }))

    expect(await screen.findByRole('heading', { level: 1, name: 'Photosynthesis' })).toBeVisible()
    const [, init] = fetch.mock.calls.find(
      ([url, i]) => url === '/api/quizzes' && i?.method === 'POST',
    )!
    expect(JSON.parse(String(init?.body))).toEqual({ document_id: 'd1', questions: 10 })
  })

  it('lists my quizzes with their best score', async () => {
    mockApi({
      '/api/health': HEALTH,
      '/api/documents': { body: [] },
      'GET /api/quizzes': {
        body: [
          summary({ attempts: 2, best_score: 2, last_score: 1 }),
          summary({ id: 'q2', title: 'Entropy' }),
        ],
      },
    })
    renderApp('/quizzes')

    const taken = await screen.findByRole('listitem', { name: 'Photosynthesis' })
    expect(within(taken).getByText(/best 2\/2/i)).toBeVisible()
    expect(
      within(screen.getByRole('listitem', { name: 'Entropy' })).getByText(/not taken yet/i),
    ).toBeVisible()
  })

  it('explains why a quiz could not be made', async () => {
    mockApi({
      '/api/health': HEALTH,
      '/api/documents': { body: [document('d1', 'Photosynthesis.pdf')] },
      'GET /api/quizzes': { body: [] },
      'POST /api/quizzes': {
        status: 503,
        body: {
          error: {
            code: 'service_unavailable',
            message: "The AI couldn't write a valid quiz this time.",
          },
        },
      },
    })
    renderApp('/quizzes')

    await screen.findByRole('option', { name: 'Photosynthesis.pdf' })
    await userEvent.click(screen.getByRole('button', { name: 'Make quiz' }))

    expect(await screen.findByText("The AI couldn't write a valid quiz this time.")).toBeVisible()
  })
})

describe('Taking a quiz', () => {
  function backend() {
    return mockApi({
      '/api/health': HEALTH,
      '/api/quizzes/q1': { body: QUIZ },
      'POST /api/quizzes/q1/attempts': { status: 201, body: RESULT },
    })
  }

  it('checks the answers only when every question is answered, then shows the score', async () => {
    const fetch = backend()
    renderApp('/quizzes/q1')

    const first = await screen.findByRole('group', { name: '1. Why do plants look green?' })
    const check = screen.getByRole('button', { name: 'Check answers' })
    await userEvent.click(within(first).getByLabelText('They reflect green'))
    expect(check).toBeDisabled() // question 2 still open
    const second = screen.getByRole('group', { name: '2. What is released?' })
    await userEvent.click(within(second).getByLabelText('Nitrogen'))
    await userEvent.click(check)

    expect(await screen.findByText('Score: 1 / 2')).toBeVisible()
    const [, init] = fetch.mock.calls.find(([url]) => String(url).endsWith('/attempts'))!
    expect(JSON.parse(String(init?.body))).toEqual({ answers: [0, 0] })
  })

  it('shows each answer with the right one, the explanation and the page', async () => {
    backend()
    renderApp('/quizzes/q1')
    await userEvent.click(await screen.findByLabelText('They reflect green'))
    await userEvent.click(screen.getByLabelText('Nitrogen'))
    await userEvent.click(screen.getByRole('button', { name: 'Check answers' }))

    const wrong = await screen.findByRole('group', { name: '2. What is released?' })
    expect(within(wrong).getByText(/Wrong\. The answer is: Oxygen/)).toBeVisible()
    expect(within(wrong).getByText(/Water is split, releasing oxygen\./)).toBeVisible()
    expect(within(wrong).getByText(/p\. 2/)).toBeVisible()
    const right = screen.getByRole('group', { name: '1. Why do plants look green?' })
    expect(within(right).getByText('Correct')).toBeVisible()
  })

  it('can be tried again', async () => {
    backend()
    renderApp('/quizzes/q1')
    await userEvent.click(await screen.findByLabelText('They reflect green'))
    await userEvent.click(screen.getByLabelText('Nitrogen'))
    await userEvent.click(screen.getByRole('button', { name: 'Check answers' }))

    await userEvent.click(await screen.findByRole('button', { name: 'Try again' }))

    expect(screen.queryByText('Score: 1 / 2')).not.toBeInTheDocument()
    expect(screen.getByLabelText('They reflect green')).not.toBeChecked()
  })
})
