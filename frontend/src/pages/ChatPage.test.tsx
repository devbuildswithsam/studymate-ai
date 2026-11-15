// The general chat page (wireframe 6.1). SMA-25 (test-first). fetch is faked: no backend.
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { mockApi, renderApp } from '@/test/render'

const HEALTH = { body: { status: 'ok', version: '0.1.0', env: 'test', auth_mode: 'local' } }

function reply(text: string, conversationId = 'conv-1') {
  return {
    body: {
      conversation_id: conversationId,
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

/** The JSON bodies sent to POST /api/chat, in order. */
function chatBodies(fetch: ReturnType<typeof mockApi>) {
  return fetch.mock.calls
    .filter(([url]) => url === '/api/chat')
    .map(([, init]) => JSON.parse(String(init?.body)))
}

const messages = () => screen.getByRole('list', { name: 'Messages' })
const input = () => screen.getByRole('textbox', { name: 'Message' })
const sendButton = () => screen.getByRole('button', { name: 'Send' })

describe('Chat page', () => {
  it('sends a message and shows it, a thinking indicator, then the answer', async () => {
    let answer: (r: Response) => void = () => {}
    const fetch = mockApi({
      '/api/health': HEALTH,
      '/api/chat': () => new Promise<Response>((resolve) => (answer = resolve)), // we decide when
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

  it('sends the conversation id with the next message, so the AI remembers', async () => {
    const fetch = mockApi({ '/api/health': HEALTH, '/api/chat': reply('Answer.', 'conv-42') })
    renderApp('/')

    await userEvent.type(input(), 'First{Enter}')
    await within(messages()).findByText('Answer.')
    await userEvent.type(input(), 'Second{Enter}')
    await waitFor(() => expect(chatBodies(fetch)).toHaveLength(2))

    expect(chatBodies(fetch)[1]).toEqual({
      message: 'Second',
      conversation_id: 'conv-42',
      allow_fallback: true,
    })
  })

  it('sends with Enter, and Shift+Enter adds a new line instead', async () => {
    const fetch = mockApi({ '/api/health': HEALTH, '/api/chat': reply('OK') })
    renderApp('/')

    await userEvent.type(input(), 'Line one{Shift>}{Enter}{/Shift}Line two')
    expect(chatBodies(fetch)).toHaveLength(0)
    expect(input()).toHaveValue('Line one\nLine two')

    await userEvent.type(input(), '{Enter}')
    expect(chatBodies(fetch)).toEqual([{ message: 'Line one\nLine two', allow_fallback: true }])
  })

  it('cannot send an empty message', async () => {
    const fetch = mockApi({ '/api/health': HEALTH, '/api/chat': reply('OK') })
    renderApp('/')

    expect(sendButton()).toBeDisabled()
    await userEvent.type(input(), '   {Enter}')

    expect(sendButton()).toBeDisabled()
    expect(chatBodies(fetch)).toHaveLength(0)
  })

  it('cannot send again while waiting for an answer', async () => {
    const fetch = mockApi({
      '/api/health': HEALTH,
      '/api/chat': () => new Promise<Response>(() => {}), // never answers
    })
    renderApp('/')

    await userEvent.type(input(), 'First{Enter}')
    await userEvent.type(input(), 'Second{Enter}')

    expect(sendButton()).toBeDisabled()
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
      '/api/chat': {
        status: 503,
        body: { error: { code: 'service_unavailable', message: 'The AI is unavailable (…)' } },
      },
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
      '/api/chat': () => Promise.reject(new TypeError('Failed to fetch')),
    })
    renderApp('/')

    await userEvent.type(input(), 'Hello{Enter}')

    expect(await screen.findByText(/Can't reach the server/)).toBeInTheDocument()
  })

  it("shows the backend's message for other errors (e.g. 422)", async () => {
    mockApi({
      '/api/health': HEALTH,
      '/api/chat': {
        status: 422,
        body: { error: { code: 'validation_error', message: 'body.message: too long' } },
      },
    })
    renderApp('/')

    await userEvent.type(input(), 'Hello{Enter}')

    expect(await screen.findByText(/body.message: too long/)).toBeInTheDocument()
  })
})

describe('Chat page when the backend is down behind the dev proxy', () => {
  it('shows "can\'t reach the server" for the proxy\'s empty 502', async () => {
    // What Vite's proxy really answers when FastAPI isn't running (checked by hand).
    mockApi({ '/api/health': HEALTH, '/api/chat': async () => new Response('', { status: 502 }) })
    renderApp('/')

    await userEvent.type(input(), 'Hello{Enter}')

    expect(await screen.findByText(/Can't reach the server/)).toBeInTheDocument()
  })
})

describe('Chat page model selector and badges (SMA-26)', () => {
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
  const modelSelect = () => screen.getByRole('combobox', { name: 'Model' })

  it('starts on the default model and sends it, with fallback on', async () => {
    const fetch = mockApi({
      '/api/health': HEALTH,
      '/api/models': MODELS,
      '/api/chat': reply('Hi'),
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
      '/api/chat': reply('Hi'),
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
      '/api/chat': reply('Hi'),
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
    mockApi({ '/api/health': HEALTH, '/api/models': MODELS, '/api/chat': fallbackReply })
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
    const fetch = mockApi({ '/api/health': HEALTH, '/api/chat': reply('Hi') }) // /api/models -> 404
    renderApp('/')

    await userEvent.type(input(), 'Hello{Enter}')

    expect(await within(messages()).findByText('Hi')).toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'Model' })).toBeNull()
    expect(chatBodies(fetch)[0]).toEqual({ message: 'Hello', allow_fallback: true })
  })
})
