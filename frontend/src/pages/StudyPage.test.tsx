// Study chat (wireframe 6.2): ask your documents, with citations. SMA-49, test-first.
// fetch is faked: no backend.
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { mockApi, renderApp } from '@/test/render'

const HEALTH = { body: { status: 'ok', version: '0.1.0', env: 'test', auth_mode: 'local' } }
const MODELS = {
  body: {
    default_model: 'openai/gpt-oss-120b',
    models: [
      {
        id: 'openai/gpt-oss-120b',
        provider: 'groq',
        display_name: 'GPT-OSS 120B (Groq)',
        supports_tools: true,
        supports_json: true,
        status: 'available',
      },
    ],
  },
}

function doc(id: string, filename: string, status = 'ready') {
  return {
    id,
    filename,
    mime_type: 'application/pdf',
    size_bytes: 1,
    page_count: 30,
    status,
    error: null,
    summary: null,
    key_points: null,
    created_at: '2026-11-19T09:00:00Z',
    can_retry: false,
  }
}

const CITATION = {
  n: 1,
  chunk_id: 'c1',
  document_id: 'd1',
  filename: 'Physics.pdf',
  page: 12,
  text: 'Newton’s second law: force equals mass times acceleration.',
}

function reply(text: string, citations: object[], mode = 'grounded') {
  return {
    conversation_id: 's1',
    message_id: `a-${text.length}`,
    reply: text,
    provider: 'groq',
    model: 'openai/gpt-oss-120b',
    mode,
    tool_calls: [],
    actions: [],
    citations,
    fallback_used: false,
    fallback_reason: null,
    tokens_in: 10,
    tokens_out: 5,
  }
}

/** The fake backend for a new study chat: documents, then one conversation "s1". */
function studyBackend(answers: object[]) {
  const replies = [...answers]
  return mockApi({
    '/api/health': HEALTH,
    '/api/models': MODELS,
    'GET /api/conversations': { body: [] },
    'GET /api/documents': {
      body: [
        doc('d1', 'Physics.pdf'),
        doc('d2', 'Biology.pdf'),
        doc('d3', 'Half.pdf', 'processing'),
      ],
    },
    'POST /api/conversations': {
      status: 201,
      body: { id: 's1', mode: 'study', documents: [{ id: 'd1', filename: 'Physics.pdf' }] },
    },
    '/api/conversations/s1/messages': async () => Response.json(replies.shift()),
    '/api/conversations/s1/title': { body: { id: 's1', title: 'Newton', mode: 'study' } },
  })
}

function posted(fetch: ReturnType<typeof mockApi>, url: string) {
  return fetch.mock.calls
    .filter(([u, init]) => u === url && init?.method !== 'GET' && init?.body)
    .map(([, init]) => JSON.parse(String(init?.body)))
}

const input = () => screen.getByRole('textbox', { name: 'Message' })
const sources = () => screen.getByRole('complementary', { name: 'Sources' })

async function pickPhysics() {
  await userEvent.selectOptions(await screen.findByRole('combobox', { name: 'Add document' }), 'd1')
}

describe('Study page', () => {
  it('lets me pick ready documents, and asks for one before I can send', async () => {
    studyBackend([])
    renderApp('/study')

    const picker = await screen.findByRole('combobox', { name: 'Add document' })
    const options = within(picker)
      .getAllByRole('option')
      .map((o) => o.textContent)
    expect(options).toEqual(['+ add document', 'Physics.pdf', 'Biology.pdf']) // not Half.pdf
    expect(input()).toHaveAttribute('placeholder', 'Add a document to start asking')
    await userEvent.type(input(), 'Hello')
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled() // no document yet

    await pickPhysics()

    expect(screen.getByRole('button', { name: 'Remove Physics.pdf' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send' })).toBeEnabled()
  })

  it('Done when: an answer cites the right page, shown as a chip and in the Sources panel', async () => {
    const fetch = studyBackend([reply('F = ma [1].', [CITATION])])
    renderApp('/study')
    await pickPhysics()

    await userEvent.type(input(), "What is Newton's second law?{Enter}")

    expect(await screen.findByText('From your documents · 1 source')).toBeInTheDocument()
    expect(posted(fetch, '/api/conversations')).toEqual([{ mode: 'study', document_ids: ['d1'] }])
    await userEvent.click(screen.getByRole('button', { name: '[1] Physics.pdf p.12' }))
    const source = within(sources()).getByRole('listitem', { name: '[1] Physics.pdf p.12' })
    expect(source).toHaveTextContent('force equals mass times acceleration')
    expect(source).toHaveAttribute('aria-current', 'true') // the clicked one is highlighted
  })

  it('Done when: an unanswerable question shows the not-found notice, then a general answer on request', async () => {
    const fetch = studyBackend([
      reply("I couldn't find this in your documents.", []),
      reply('France won the 1998 World Cup.', [], 'general'),
    ])
    renderApp('/study')
    await pickPhysics()

    await userEvent.type(input(), 'Who won the 1998 World Cup?{Enter}')

    expect(await screen.findByText('Not found in your documents')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Answer from general knowledge' }))
    expect(await screen.findByText('France won the 1998 World Cup.')).toBeInTheDocument()
    expect(posted(fetch, '/api/conversations/s1/messages')[1]).toEqual({
      message: 'Who won the 1998 World Cup?',
      general: true,
    })
    expect(screen.getAllByText('General AI')).toHaveLength(1) // labelled: never mixed silently
  })

  it('reopens a saved study chat with its documents and sources, and can change them', async () => {
    const saved = {
      id: 's7',
      title: 'Newton',
      mode: 'study',
      provider: 'groq',
      model: 'openai/gpt-oss-120b',
      created_at: '2026-11-19T09:00:00Z',
      updated_at: '2026-11-19T09:00:00Z',
      documents: [{ id: 'd1', filename: 'Physics.pdf' }],
      messages: [
        {
          id: 'a1',
          role: 'assistant',
          content: 'F = ma [1].',
          provider: 'groq',
          model: 'openai/gpt-oss-120b',
          mode: 'grounded',
          fallback_used: false,
          tokens_in: 1,
          tokens_out: 1,
          citations: [CITATION],
          created_at: '2026-11-19T09:00:00Z',
        },
      ],
    }
    const fetch = mockApi({
      '/api/health': HEALTH,
      '/api/models': MODELS,
      'GET /api/conversations': { body: [saved] },
      'GET /api/conversations/s7': { body: saved },
      'GET /api/documents': { body: [doc('d1', 'Physics.pdf')] },
      'PUT /api/conversations/s7/documents': { body: { ...saved, documents: [] } },
    })
    renderApp('/study/s7')

    expect(await screen.findByText('From your documents · 1 source')).toBeInTheDocument()
    expect(within(sources()).getByText(/force equals mass/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Remove Physics.pdf' }))

    expect(posted(fetch, '/api/conversations/s7/documents')).toEqual([{ document_ids: [] }])
  })

  it('says when there is nothing to study yet', async () => {
    mockApi({
      '/api/health': HEALTH,
      '/api/models': MODELS,
      'GET /api/conversations': { body: [] },
      'GET /api/documents': { body: [] },
    })
    renderApp('/study')

    expect(await screen.findByText(/Upload a document first/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Documents page' })).toHaveAttribute(
      'href',
      '/documents',
    )
  })
})

describe('Recent chats (SMA-49)', () => {
  it('opens a study chat on the Study page', async () => {
    mockApi({
      '/api/health': HEALTH,
      '/api/models': MODELS,
      'GET /api/conversations': {
        body: [
          {
            id: 's1',
            title: 'Newton',
            mode: 'study',
            provider: null,
            model: null,
            created_at: '',
            updated_at: '',
          },
          {
            id: 'c1',
            title: 'Osmosis',
            mode: 'general',
            provider: null,
            model: null,
            created_at: '',
            updated_at: '',
          },
        ],
      },
    })
    renderApp('/notes')

    expect(await screen.findByRole('link', { name: 'Newton' })).toHaveAttribute('href', '/study/s1')
    expect(screen.getByRole('link', { name: 'Osmosis' })).toHaveAttribute('href', '/c/c1')
  })
})
