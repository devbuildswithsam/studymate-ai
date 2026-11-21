// The general chat page (wireframe 6.1). SMA-25 (test-first). fetch is faked: no backend.
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { mockApi, renderApp } from '@/test/render'

const HEALTH = { body: { status: 'ok', version: '0.1.0', env: 'test', auth_mode: 'local' } }

const MODELS = {
  body: {
    default_model: 'gemini-3.5-flash',
    models: [
      {
        id: 'gemini-3.5-flash',
        provider: 'gemini',
        display_name: 'Gemini 3.5 Flash',
        supports_tools: true,
        supports_json: true,
        status: 'available',
      },
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

function reply(text: string, conversationId = 'conv-1', messageId = 'answer-1') {
  return {
    body: {
      conversation_id: conversationId,
      message_id: messageId, // SMA-32: the saved answer, for "Save as note"
      reply: text,
      provider: 'gemini',
      model: 'gemini-3.5-flash',
      mode: 'general',
      fallback_used: false,
      fallback_reason: null,
      tokens_in: 10,
      tokens_out: 5,
    },
  }
}

/**
 * The fake backend's chat routes (SMA-30): creating a conversation returns `id`, and
 * messages sent into it get `answer`.
 */
function chat(answer: Parameters<typeof mockApi>[0][string], id = 'conv-1') {
  return {
    'POST /api/conversations': { status: 201, body: { id } },
    [`/api/conversations/${id}/messages`]: answer,
  }
}

/** The JSON bodies sent as chat messages, in order. */
function chatBodies(fetch: ReturnType<typeof mockApi>) {
  return fetch.mock.calls
    .filter(([url]) => String(url).endsWith('/messages'))
    .map(([, init]) => JSON.parse(String(init?.body)))
}

/** The URLs that were POSTed to, in order. */
function postedUrls(fetch: ReturnType<typeof mockApi>) {
  return fetch.mock.calls.filter(([, init]) => init?.method === 'POST').map(([url]) => url)
}

const messages = () => screen.getByRole('list', { name: 'Messages' })
const input = () => screen.getByRole('textbox', { name: 'Message' })
const sendButton = () => screen.getByRole('button', { name: 'Send' })

describe('Chat page', () => {
  it('sends a message and shows it, a thinking indicator, then the answer', async () => {
    let answer: (r: Response) => void = () => {}
    const fetch = mockApi({
      '/api/health': HEALTH,
      ...chat(() => new Promise<Response>((resolve) => (answer = resolve))), // we decide when
    })
    renderApp('/')

    await userEvent.type(input(), 'What is osmosis?')
    await userEvent.click(sendButton())

    expect(within(messages()).getByText('What is osmosis?')).toBeInTheDocument() // shown at once
    expect(screen.getByText('StudyMate is thinking…')).toBeInTheDocument()
    expect(input()).toHaveValue('')
    expect(chatBodies(fetch)).toEqual([{ message: 'What is osmosis?', allow_fallback: true }])

    answer(Response.json(reply('Water moves **through** a membrane.').body))

    expect(await within(messages()).findByText('through')).toBeInTheDocument()
    expect(screen.queryByText('StudyMate is thinking…')).toBeNull()
  })

  it('starts one conversation, then sends every message into it, so the AI remembers', async () => {
    const fetch = mockApi({
      '/api/health': HEALTH,
      ...chat(reply('Answer.', 'conv-42'), 'conv-42'),
    })
    renderApp('/')

    await userEvent.type(input(), 'First{Enter}')
    await within(messages()).findByText('Answer.')
    await userEvent.type(input(), 'Second{Enter}')
    await waitFor(() => expect(chatBodies(fetch)).toHaveLength(2))

    expect(postedUrls(fetch)).toEqual([
      '/api/conversations',
      '/api/conversations/conv-42/messages',
      '/api/conversations/conv-42/title', // SMA-31: named after the first answer
      '/api/conversations/conv-42/messages',
    ])
    expect(chatBodies(fetch)[1]).toEqual({ message: 'Second', allow_fallback: true })
  })

  it('retries in the same conversation when the first answer fails', async () => {
    let fail = true
    const fetch = mockApi({
      '/api/health': HEALTH,
      ...chat(async () =>
        fail
          ? Response.json(
              { error: { code: 'service_unavailable', message: 'busy' } },
              { status: 503 },
            )
          : Response.json(reply('Now it works.').body),
      ),
    })
    renderApp('/')

    await userEvent.type(input(), 'Hello{Enter}')
    await screen.findByText(/The AI is busy right now/)
    fail = false
    await userEvent.click(sendButton()) // the text was given back: just send again

    expect(await within(messages()).findByText('Now it works.')).toBeInTheDocument()
    expect(postedUrls(fetch).filter((url) => url === '/api/conversations')).toHaveLength(1)
  })

  it('sends with Enter, and Shift+Enter adds a new line instead', async () => {
    const fetch = mockApi({ '/api/health': HEALTH, ...chat(reply('OK')) })
    renderApp('/')

    await userEvent.type(input(), 'Line one{Shift>}{Enter}{/Shift}Line two')
    expect(chatBodies(fetch)).toHaveLength(0)
    expect(input()).toHaveValue('Line one\nLine two')

    await userEvent.type(input(), '{Enter}')
    expect(chatBodies(fetch)).toEqual([{ message: 'Line one\nLine two', allow_fallback: true }])
  })

  it('cannot send an empty message', async () => {
    const fetch = mockApi({ '/api/health': HEALTH, ...chat(reply('OK')) })
    renderApp('/')

    expect(sendButton()).toBeDisabled()
    await userEvent.type(input(), '   {Enter}')

    expect(sendButton()).toBeDisabled()
    expect(chatBodies(fetch)).toHaveLength(0)
  })

  it('cannot send again while waiting for an answer', async () => {
    const fetch = mockApi({
      '/api/health': HEALTH,
      ...chat(() => new Promise<Response>(() => {})), // never answers
    })
    renderApp('/')

    await userEvent.type(input(), 'First{Enter}')
    await userEvent.type(input(), 'Second{Enter}')

    // SMA-62: while an answer is written, Send is replaced by Stop.
    expect(screen.queryByRole('button', { name: 'Send' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Stop' })).toBeInTheDocument()
    expect(chatBodies(fetch)).toHaveLength(1)
  })

  it('limits the input to 4000 characters, like the backend', () => {
    mockApi({ '/api/health': HEALTH })
    renderApp('/')

    expect(input()).toHaveAttribute('maxLength', '4000')
  })

  it('shows a friendly toast when the AI is busy, and gives the text back', async () => {
    mockApi({
      '/api/health': HEALTH,
      ...chat({
        status: 503,
        body: { error: { code: 'service_unavailable', message: 'The AI is unavailable (…)' } },
      }),
    })
    renderApp('/')

    await userEvent.type(input(), 'Explain entropy{Enter}')

    expect(await screen.findByText(/The AI is busy right now/)).toBeInTheDocument()
    expect(input()).toHaveValue('Explain entropy') // ready to retry, no retyping
    expect(within(messages()).queryByText('Explain entropy')).toBeNull() // no orphan bubble
  })

  it('shows a toast when the server cannot be reached', async () => {
    mockApi({
      '/api/health': HEALTH,
      ...chat(() => Promise.reject(new TypeError('Failed to fetch'))),
    })
    renderApp('/')

    await userEvent.type(input(), 'Hello{Enter}')

    expect(await screen.findByText(/Can't reach the server/)).toBeInTheDocument()
  })

  it("shows the backend's message for other errors (e.g. 422)", async () => {
    mockApi({
      '/api/health': HEALTH,
      ...chat({
        status: 422,
        body: { error: { code: 'validation_error', message: 'body.message: too long' } },
      }),
    })
    renderApp('/')

    await userEvent.type(input(), 'Hello{Enter}')

    expect(await screen.findByText(/body.message: too long/)).toBeInTheDocument()
  })
})

describe('Chat page when the backend is down behind the dev proxy', () => {
  it('shows "can\'t reach the server" for the proxy\'s empty 502', async () => {
    // What Vite's proxy really answers when FastAPI isn't running (checked by hand).
    mockApi({ '/api/health': HEALTH, ...chat(async () => new Response('', { status: 502 })) })
    renderApp('/')

    await userEvent.type(input(), 'Hello{Enter}')

    expect(await screen.findByText(/Can't reach the server/)).toBeInTheDocument()
  })
})

describe('Chat page model selector and badges (SMA-26)', () => {
  const modelSelect = () => screen.getByRole('combobox', { name: 'Model' })

  it('starts on the default model and sends it, with fallback on', async () => {
    const fetch = mockApi({
      '/api/health': HEALTH,
      '/api/models': MODELS,
      ...chat(reply('Hi')),
    })
    renderApp('/')

    expect(await screen.findByRole('combobox', { name: 'Model' })).toHaveValue('gemini-3.5-flash')
    await userEvent.type(input(), 'Hello{Enter}')

    expect(chatBodies(fetch)).toEqual([
      { message: 'Hello', model: 'gemini-3.5-flash', allow_fallback: true },
    ])
  })

  it('asks the newly chosen model after switching', async () => {
    const fetch = mockApi({
      '/api/health': HEALTH,
      '/api/models': MODELS,
      ...chat(reply('Hi')),
    })
    renderApp('/')

    await userEvent.selectOptions(
      await screen.findByRole('combobox', { name: 'Model' }),
      'openai/gpt-oss-120b',
    )
    await userEvent.type(input(), 'Hello{Enter}')

    expect(chatBodies(fetch)[0].model).toBe('openai/gpt-oss-120b')
  })

  it('sends allow_fallback false when the toggle is off', async () => {
    const fetch = mockApi({
      '/api/health': HEALTH,
      '/api/models': MODELS,
      ...chat(reply('Hi')),
    })
    renderApp('/')

    await screen.findByRole('combobox', { name: 'Model' })
    await userEvent.click(screen.getByRole('checkbox', { name: 'Use fallback if the model fails' }))
    await userEvent.type(input(), 'Hello{Enter}')

    expect(chatBodies(fetch)[0].allow_fallback).toBe(false)
  })

  it('labels each answer with the model that actually answered, and a fallback warning', async () => {
    const fallbackReply = {
      body: {
        ...reply('From the backup.').body,
        provider: 'groq',
        model: 'openai/gpt-oss-120b',
        fallback_used: true,
        fallback_reason: 'gemini-3.5-flash: rate-limited',
      },
    }
    mockApi({ '/api/health': HEALTH, '/api/models': MODELS, ...chat(fallbackReply) })
    renderApp('/')

    await screen.findByRole('combobox', { name: 'Model' })
    await userEvent.type(input(), 'Hello{Enter}')

    const answer = (await within(messages()).findByText('From the backup.')).closest('li')!
    expect(within(answer).getByText('General AI')).toBeInTheDocument()
    expect(within(answer).getByText('GPT-OSS 120B (Groq)')).toBeInTheDocument() // display name
    expect(
      within(answer).getByLabelText('Fallback used: gemini-3.5-flash: rate-limited'),
    ).toBeInTheDocument()
    expect(modelSelect()).toHaveValue('gemini-3.5-flash') // the choice itself doesn't change
  })

  it('still chats when the model list cannot be loaded (backend default model)', async () => {
    const fetch = mockApi({ '/api/health': HEALTH, ...chat(reply('Hi')) }) // /api/models -> 404
    renderApp('/')

    await userEvent.type(input(), 'Hello{Enter}')

    expect(await within(messages()).findByText('Hi')).toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'Model' })).toBeNull()
    expect(chatBodies(fetch)[0]).toEqual({ message: 'Hello', allow_fallback: true })
  })
})

describe('Reopening and continuing a saved chat (SMA-31)', () => {
  const SAVED = {
    id: 'c9',
    title: 'Osmosis in Plant Roots',
    provider: 'groq',
    model: 'openai/gpt-oss-120b', // this chat used the Groq model, not the default
    created_at: '2026-11-15T10:00:00Z',
    updated_at: '2026-11-15T10:01:00Z',
    messages: [
      saved('m1', 'user', 'What is osmosis?'),
      {
        ...saved('m2', 'assistant', 'Water moving through a membrane.'),
        provider: 'groq',
        model: 'openai/gpt-oss-120b',
        mode: 'general',
        fallback_used: true,
      },
    ],
  }

  function saved(id: string, role: 'user' | 'assistant', content: string) {
    return {
      id,
      role,
      content,
      provider: null,
      model: null,
      mode: null,
      fallback_used: false,
      tokens_in: null,
      tokens_out: null,
      created_at: '2026-11-15T10:00:00Z',
    }
  }

  function savedChatBackend() {
    return mockApi({
      '/api/health': HEALTH,
      '/api/models': MODELS,
      'GET /api/conversations': { body: [SAVED] },
      'GET /api/conversations/c9': { body: SAVED },
      ...chat(reply('Roots take in water by osmosis.', 'c9'), 'c9'),
    })
  }

  it('shows the saved messages with their badges', async () => {
    savedChatBackend()
    renderApp('/c/c9')

    expect(await within(messages()).findByText('What is osmosis?')).toBeInTheDocument()
    const answer = within(messages()).getByText('Water moving through a membrane.').closest('li')!
    expect(await within(answer).findByText('GPT-OSS 120B (Groq)')).toBeInTheDocument()
    expect(within(answer).getByLabelText('Fallback used: fallback used')).toBeInTheDocument()
    expect(
      screen.getByRole('heading', { level: 1, name: 'Osmosis in Plant Roots' }),
    ).toBeInTheDocument()
  })

  it('Done when: reopen an old chat from the sidebar and continue it with the same model', async () => {
    const fetch = savedChatBackend()
    renderApp('/')

    await userEvent.click(await screen.findByRole('link', { name: 'Osmosis in Plant Roots' }))
    await within(messages()).findByText('What is osmosis?')
    expect(screen.getByRole('combobox', { name: 'Model' })).toHaveValue('openai/gpt-oss-120b')
    await userEvent.type(input(), 'Why does it matter for roots?{Enter}')

    expect(
      await within(messages()).findByText('Roots take in water by osmosis.'),
    ).toBeInTheDocument()
    expect(postedUrls(fetch)).toEqual(['/api/conversations/c9/messages']) // no new chat
    expect(chatBodies(fetch)).toEqual([
      {
        message: 'Why does it matter for roots?',
        model: 'openai/gpt-oss-120b',
        allow_fallback: true,
      },
    ])
    expect(within(messages()).getByText('What is osmosis?')).toBeInTheDocument() // history kept
  })

  it('says so when the chat does not exist (e.g. it was deleted)', async () => {
    mockApi({ '/api/health': HEALTH }) // GET /api/conversations/gone -> 404
    renderApp('/c/gone')

    expect(await screen.findByText(/This chat doesn't exist/)).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: 'Message' })).toBeNull()
  })
})

describe('A new chat after its first answer (SMA-31)', () => {
  it("moves to the chat's own address, keeps the toggle, and shows the AI title in the sidebar", async () => {
    let titled = false
    const listed = () => [
      {
        id: 'c5',
        title: titled ? "Newton's Second Law" : null,
        provider: 'gemini',
        model: 'gemini-3.5-flash',
        created_at: '2026-11-16T10:00:00Z',
        updated_at: '2026-11-16T10:00:00Z',
      },
    ]
    const fetch = mockApi({
      '/api/health': HEALTH,
      '/api/models': MODELS,
      'GET /api/conversations': async () => Response.json(titled ? listed() : []),
      ...chat(reply('F = ma.', 'c5'), 'c5'),
      'POST /api/conversations/c5/title': async () => {
        titled = true
        return Response.json(listed()[0])
      },
    })
    renderApp('/')
    await screen.findByRole('combobox', { name: 'Model' })
    await userEvent.click(screen.getByRole('checkbox', { name: 'Use fallback if the model fails' }))

    await userEvent.type(input(), "Explain Newton's second law{Enter}")

    expect(await within(messages()).findByText('F = ma.')).toBeInTheDocument()
    const link = await screen.findByRole('link', { name: "Newton's Second Law" })
    expect(link).toHaveAttribute('href', '/c/c5')
    await waitFor(() => expect(link).toHaveAttribute('aria-current', 'page')) // now on /c/c5
    expect(
      screen.getByRole('heading', { level: 1, name: "Newton's Second Law" }),
    ).toBeInTheDocument()
    expect(within(messages()).getByText('F = ma.')).toBeInTheDocument() // nothing lost
    expect(
      screen.getByRole('checkbox', { name: 'Use fallback if the model fails' }),
    ).not.toBeChecked()
    expect(postedUrls(fetch).filter((url) => String(url).endsWith('/title'))).toHaveLength(1)
  })

  it('does not ask for a title again on later messages', async () => {
    const fetch = mockApi({ '/api/health': HEALTH, ...chat(reply('OK'), 'conv-1') })
    renderApp('/')

    await userEvent.type(input(), 'First{Enter}')
    await within(messages()).findByText('OK')
    await userEvent.type(input(), 'Second{Enter}')
    await waitFor(() => expect(chatBodies(fetch)).toHaveLength(2))

    expect(postedUrls(fetch).filter((url) => String(url).endsWith('/title'))).toHaveLength(1)
  })
})

describe('Save as note (SMA-32)', () => {
  it('saves an answer as a note linked to its message, titled from the question', async () => {
    let saved: unknown
    mockApi({
      '/api/health': HEALTH,
      ...chat(reply('Osmosis is water moving through a membrane.', 'conv-1', 'answer-7')),
      'POST /api/notes': async (init) => {
        saved = JSON.parse(String(init?.body))
        return Response.json({ id: 'note-1', ...(saved as object) }, { status: 201 })
      },
    })
    renderApp('/')
    await userEvent.type(input(), 'What is osmosis in plant roots and why does it matter?{Enter}')
    const answer = (
      await within(messages()).findByText('Osmosis is water moving through a membrane.')
    ).closest('li')!

    await userEvent.click(within(answer).getByRole('button', { name: 'Save as note' }))

    expect(await within(answer).findByRole('button', { name: 'Saved to notes' })).toBeDisabled()
    expect(saved).toEqual({
      title: 'What is osmosis in plant roots…', // the chat has no title yet: the question's start
      content: 'Osmosis is water moving through a membrane.',
      tags: [],
      source_message_id: 'answer-7',
    })
    expect(await screen.findByText('Saved to Notes')).toBeInTheDocument()
  })

  it('uses the chat title when there is one', async () => {
    const SAVED = {
      id: 'c9',
      title: 'Osmosis in Plant Roots',
      provider: 'gemini',
      model: 'gemini-3.5-flash',
      created_at: '2026-11-15T10:00:00Z',
      updated_at: '2026-11-15T10:01:00Z',
      messages: [
        {
          id: 'm1',
          role: 'user',
          content: 'What is osmosis?',
          provider: null,
          model: null,
          mode: null,
          fallback_used: false,
          tokens_in: null,
          tokens_out: null,
          created_at: '2026-11-15T10:00:00Z',
        },
        {
          id: 'm2',
          role: 'assistant',
          content: 'Water moving.',
          provider: 'gemini',
          model: 'gemini-3.5-flash',
          mode: 'general',
          fallback_used: false,
          tokens_in: 5,
          tokens_out: 2,
          created_at: '2026-11-15T10:00:00Z',
        },
      ],
    }
    let saved: { title?: string; source_message_id?: string } = {}
    mockApi({
      '/api/health': HEALTH,
      'GET /api/conversations/c9': { body: SAVED },
      'POST /api/notes': async (init) => {
        saved = JSON.parse(String(init?.body))
        return Response.json({ id: 'note-2', ...saved }, { status: 201 })
      },
    })
    renderApp('/c/c9')

    const answer = (await within(messages()).findByText('Water moving.')).closest('li')!
    await userEvent.click(within(answer).getByRole('button', { name: 'Save as note' }))

    await waitFor(() => expect(saved.title).toBe('Osmosis in Plant Roots'))
    expect(saved.source_message_id).toBe('m2')
  })

  it('lets me try again when saving fails', async () => {
    mockApi({
      '/api/health': HEALTH,
      ...chat(reply('An answer.')),
      'POST /api/notes': {
        status: 503,
        body: { error: { code: 'service_unavailable', message: 'Database is busy' } },
      },
    })
    renderApp('/')
    await userEvent.type(input(), 'Hi{Enter}')
    const answer = (await within(messages()).findByText('An answer.')).closest('li')!

    await userEvent.click(within(answer).getByRole('button', { name: 'Save as note' }))

    expect(await screen.findByText(/Database is busy|busy right now/)).toBeInTheDocument()
    expect(within(answer).getByRole('button', { name: 'Save as note' })).toBeEnabled()
  })

  it('my own messages have no "Save as note" button', async () => {
    mockApi({ '/api/health': HEALTH, ...chat(reply('An answer.')) })
    renderApp('/')
    await userEvent.type(input(), 'My question{Enter}')
    await within(messages()).findByText('An answer.')

    const question = within(messages()).getByText('My question').closest('li')!
    expect(within(question).queryByRole('button', { name: 'Save as note' })).toBeNull()
  })
})

describe('Answers that used tools (SMA-42)', () => {
  const CREATE = {
    name: 'create_task',
    arguments: { title: 'Finish thermodynamics notes', due_date: '2026-11-22' },
    result: '{"id": "t9", "title": "Finish thermodynamics notes"}',
    is_error: false,
    duration_ms: 15,
  }
  const LIST = {
    name: 'list_tasks',
    arguments: { status: 'todo' },
    result: '{}',
    is_error: false,
    duration_ms: 4,
  }
  const NEW_TASK = {
    id: 't9',
    title: 'Finish thermodynamics notes',
    description: null,
    due_date: '2026-11-22',
    priority: 'medium',
    status: 'todo',
    document_id: null,
    created_by: 'ai',
    created_at: '2026-11-18T09:00:00Z',
    completed_at: null,
  }

  function toolReply() {
    const answer = reply('Added it. Your pending task: Finish thermodynamics notes.')
    return {
      body: {
        ...answer.body,
        provider: 'groq',
        model: 'openai/gpt-oss-120b',
        mode: 'tool',
        tool_calls: [CREATE, LIST],
      },
    }
  }

  it('Done when: shows "Used tool" lines under the answer', async () => {
    mockApi({ '/api/health': HEALTH, '/api/models': MODELS, ...chat(toolReply()) })
    renderApp('/')

    await userEvent.type(
      input(),
      'Add a task to finish thermodynamics notes by Sunday, then list my pending tasks{Enter}',
    )

    const answer = (await within(messages()).findByText(/Added it\./)).closest('li')!
    const lines = within(within(answer).getByRole('list', { name: 'Tools used' })).getAllByRole(
      'listitem',
    )
    expect(lines.map((l) => l.textContent)).toEqual([
      'Used tool: create_task → title: Finish thermodynamics notes, due_date: 2026-11-22',
      'Used tool: list_tasks → status: todo',
    ])
    expect(within(answer).getByText('Used tools')).toBeInTheDocument()
  })

  it('shows the tool lines again when the chat is reopened', async () => {
    const savedChat = {
      id: 'c7',
      title: 'Thermodynamics task',
      provider: 'groq',
      model: 'openai/gpt-oss-120b',
      created_at: '2026-11-18T09:00:00Z',
      updated_at: '2026-11-18T09:00:00Z',
      messages: [
        {
          id: 'm1',
          role: 'assistant',
          content: 'Added it.',
          provider: 'groq',
          model: 'openai/gpt-oss-120b',
          mode: 'tool',
          fallback_used: false,
          tokens_in: 10,
          tokens_out: 5,
          tool_calls: [CREATE],
          created_at: '2026-11-18T09:00:00Z',
        },
      ],
    }
    mockApi({
      '/api/health': HEALTH,
      '/api/models': MODELS,
      'GET /api/conversations': { body: [savedChat] },
      'GET /api/conversations/c7': { body: savedChat },
    })
    renderApp('/c/c7')

    expect(await screen.findByText(/Used tool:/)).toHaveTextContent(
      'Used tool: create_task → title: Finish thermodynamics notes',
    )
  })

  it('the Tasks board shows the task the AI created', async () => {
    let taskCreated = false
    mockApi({
      '/api/health': HEALTH,
      '/api/models': MODELS,
      'GET /api/conversations': { body: [] },
      'GET /api/tasks': { body: [] },
      'POST /api/conversations': { status: 201, body: { id: 'conv-1' } },
      '/api/conversations/conv-1/messages': async () => {
        taskCreated = true // the backend's tool wrote the task
        return Response.json(toolReply().body)
      },
    })
    // The board after the chat: replace the empty list with the new task.
    const fetch = vi.mocked(globalThis.fetch)
    const real = fetch.getMockImplementation()!
    fetch.mockImplementation(async (url, init) =>
      String(url) === '/api/tasks' && taskCreated ? Response.json([NEW_TASK]) : real(url, init),
    )
    renderApp('/tasks')
    await screen.findByRole('heading', { name: 'Tasks' })

    await userEvent.click(screen.getByRole('link', { name: 'Chat' }))
    await userEvent.type(input(), 'Add a task to finish thermodynamics notes{Enter}')
    await within(messages()).findByText(/Added it\./)
    await userEvent.click(screen.getByRole('link', { name: 'Tasks' }))

    expect(await screen.findByText('Finish thermodynamics notes')).toBeInTheDocument()
  })
})

describe('Confirmation cards and Undo (SMA-43)', () => {
  const PENDING = {
    id: 'act1',
    tool: 'complete_task',
    kind: 'change',
    status: 'pending',
    summary: "Mark 'Revise ch.3' as done",
    error: null,
  }
  const CREATED = {
    id: 'act2',
    tool: 'create_task',
    kind: 'create',
    status: 'done',
    summary: "Add task 'Essay'",
    error: null,
  }

  function answerWith(actions: object[]) {
    const answer = reply('Please confirm it below.')
    return { body: { ...answer.body, mode: 'tool', tool_calls: [], actions } }
  }

  it('Done when: confirming a card runs it and shows it as done', async () => {
    const fetch = mockApi({
      '/api/health': HEALTH,
      '/api/models': MODELS,
      ...chat(answerWith([PENDING])),
      'POST /api/actions/act1/confirm': { body: { ...PENDING, status: 'done' } },
    })
    renderApp('/')

    await userEvent.type(input(), 'Complete my Revise ch.3 task{Enter}')
    const card = await screen.findByRole('listitem', { name: PENDING.summary })
    expect(card).toHaveTextContent("Mark 'Revise ch.3' as done?")
    await userEvent.click(within(card).getByRole('button', { name: 'Confirm' }))

    expect(await screen.findByText("Done: Mark 'Revise ch.3' as done")).toBeInTheDocument()
    expect(postedUrls(fetch)).toContain('/api/actions/act1/confirm')
    expect(screen.queryByRole('button', { name: 'Confirm' })).toBeNull()
  })

  it('cancels a card', async () => {
    mockApi({
      '/api/health': HEALTH,
      '/api/models': MODELS,
      ...chat(answerWith([PENDING])),
      'POST /api/actions/act1/cancel': { body: { ...PENDING, status: 'cancelled' } },
    })
    renderApp('/')

    await userEvent.type(input(), 'Complete my Revise ch.3 task{Enter}')
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel' }))

    expect(await screen.findByText("Cancelled: Mark 'Revise ch.3' as done")).toBeInTheDocument()
  })

  it('undoes a task the AI created', async () => {
    const fetch = mockApi({
      '/api/health': HEALTH,
      '/api/models': MODELS,
      ...chat(answerWith([CREATED])),
      'POST /api/actions/act2/undo': { body: { ...CREATED, status: 'undone' } },
    })
    renderApp('/')

    await userEvent.type(input(), 'Add a task: essay{Enter}')
    await userEvent.click(await screen.findByRole('button', { name: 'Undo' }))

    expect(await screen.findByText("Undone: Add task 'Essay'")).toBeInTheDocument()
    expect(postedUrls(fetch)).toContain('/api/actions/act2/undo')
  })

  it('shows the error and keeps the card when a click fails', async () => {
    mockApi({
      '/api/health': HEALTH,
      '/api/models': MODELS,
      ...chat(answerWith([PENDING])),
      'POST /api/actions/act1/confirm': {
        status: 409,
        body: { error: { code: 'conflict', message: 'This action is already cancelled.' } },
      },
    })
    renderApp('/')

    await userEvent.type(input(), 'Complete my Revise ch.3 task{Enter}')
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm' }))

    expect(await screen.findByText('This action is already cancelled.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Confirm' })).toBeEnabled() // try again
  })

  it('shows the cards again when the chat is reopened', async () => {
    const savedChat = {
      id: 'c8',
      title: 'Revision',
      provider: 'groq',
      model: 'openai/gpt-oss-120b',
      created_at: '2026-11-18T09:00:00Z',
      updated_at: '2026-11-18T09:00:00Z',
      messages: [
        {
          id: 'm1',
          role: 'assistant',
          content: 'Please confirm.',
          provider: 'groq',
          model: 'openai/gpt-oss-120b',
          mode: 'tool',
          fallback_used: false,
          tokens_in: 1,
          tokens_out: 1,
          tool_calls: [],
          actions: [PENDING],
          created_at: '2026-11-18T09:00:00Z',
        },
      ],
    }
    mockApi({
      '/api/health': HEALTH,
      '/api/models': MODELS,
      'GET /api/conversations': { body: [savedChat] },
      'GET /api/conversations/c8': { body: savedChat },
    })
    renderApp('/c/c8')

    expect(await screen.findByRole('button', { name: 'Confirm' })).toBeInTheDocument()
  })
})
