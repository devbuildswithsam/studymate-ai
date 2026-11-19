// Document detail (wireframe 6.4): summary and key points, regenerated on request. SMA-50.
// fetch is faked: no backend.
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { DocumentInfo } from '@/api/documents'
import { mockApi, renderApp } from '@/test/render'

const HEALTH = { body: { status: 'ok', version: '0.1.0', env: 'test', auth_mode: 'local' } }
const PHYSICS: DocumentInfo = {
  id: 'd1',
  filename: 'Physics.pdf',
  mime_type: 'application/pdf',
  size_bytes: 1000,
  page_count: 34,
  status: 'ready',
  error: null,
  summary: "This chapter covers Newton's laws of motion.",
  key_points: ['Force equals mass times acceleration.', 'Every action has a reaction.'],
  created_at: '2026-11-19T09:00:00Z',
  can_retry: false,
}

function backend(document: DocumentInfo = PHYSICS, regenerated?: object) {
  return mockApi({
    '/api/health': HEALTH,
    'GET /api/conversations': { body: [] },
    'GET /api/documents': { body: [document] },
    'GET /api/documents/d1': { body: document },
    'POST /api/documents/d1/summary': regenerated
      ? { body: regenerated }
      : {
          status: 503,
          body: { error: { code: 'service_unavailable', message: 'The AI is busy. Try again.' } },
        },
  })
}

function requests(fetch: ReturnType<typeof mockApi>, url: string) {
  return fetch.mock.calls.filter(([u]) => u === url)
}

describe('Document page', () => {
  it('Done when: shows the saved summary and key points, without asking the AI', async () => {
    const fetch = backend()
    renderApp('/documents/d1')

    expect(await screen.findByRole('heading', { name: 'Physics.pdf' })).toBeInTheDocument()
    expect(screen.getByText('34 pages')).toBeInTheDocument()
    expect(screen.getByText(/covers Newton's laws/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'Key points' }))
    const points = within(screen.getByRole('tabpanel')).getAllByRole('listitem')
    expect(points.map((p) => p.textContent)).toEqual(PHYSICS.key_points)
    expect(requests(fetch, '/api/documents/d1/summary')).toEqual([]) // cached: no AI call
  })

  it('regenerates the summary in the chosen style', async () => {
    const fetch = backend(PHYSICS, {
      ...PHYSICS,
      summary: 'A detailed summary of the chapter.',
      key_points: ['One.', 'Two.'],
    })
    renderApp('/documents/d1')
    await screen.findByText(/covers Newton's laws/)

    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Style' }), 'detailed')
    await userEvent.click(screen.getByRole('button', { name: 'Regenerate' }))

    expect(await screen.findByText('A detailed summary of the chapter.')).toBeInTheDocument()
    const [[, init]] = requests(fetch, '/api/documents/d1/summary')
    expect(JSON.parse(String(init?.body))).toEqual({ style: 'detailed' })
  })

  it('keeps the old summary and shows why when regenerating fails', async () => {
    backend()
    renderApp('/documents/d1')
    await screen.findByText(/covers Newton's laws/)

    await userEvent.click(screen.getByRole('button', { name: 'Regenerate' }))

    expect(await screen.findByText('The AI is busy. Try again.')).toBeInTheDocument()
    expect(screen.getByText(/covers Newton's laws/)).toBeInTheDocument()
  })

  it('offers to write a summary when there is none yet', async () => {
    backend({ ...PHYSICS, summary: null, key_points: null })
    renderApp('/documents/d1')

    expect(await screen.findByText(/No summary yet/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Regenerate' })).toBeEnabled()
  })

  it('opens a study chat with this document already picked', async () => {
    mockApi({
      '/api/health': HEALTH,
      '/api/models': { body: { default_model: null, models: [] } },
      'GET /api/conversations': { body: [] },
      'GET /api/documents': { body: [PHYSICS] },
      'GET /api/documents/d1': { body: PHYSICS },
    })
    renderApp('/documents/d1')

    await userEvent.click(await screen.findByRole('link', { name: 'Chat with this document' }))

    expect(await screen.findByRole('button', { name: 'Remove Physics.pdf' })).toBeInTheDocument()
  })

  it('cannot regenerate a document that is not ready', async () => {
    backend({
      ...PHYSICS,
      status: 'failed',
      summary: null,
      key_points: null,
      error: 'No text found.',
    })
    renderApp('/documents/d1')

    expect(await screen.findByText(/Failed: No text found/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Regenerate' })).toBeNull()
  })

  it('says so when the document does not exist', async () => {
    mockApi({ '/api/health': HEALTH, 'GET /api/conversations': { body: [] } })
    renderApp('/documents/nope')

    expect(await screen.findByText(/doesn't exist/)).toBeInTheDocument()
  })
})

describe('Documents list (SMA-50)', () => {
  it('links each document to its page', async () => {
    backend()
    renderApp('/documents')

    expect(await screen.findByRole('link', { name: 'Physics.pdf' })).toHaveAttribute(
      'href',
      '/documents/d1',
    )
  })
})
