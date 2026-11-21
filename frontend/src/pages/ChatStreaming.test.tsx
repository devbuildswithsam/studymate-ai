// Streaming answers and the Stop button on the chat page (SMA-62). Test-first.
// The fake backend answers with a stream the test controls: it sends each event when it
// wants, so we can check what the page shows WHILE the answer is still arriving.
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { mockApi, renderApp } from '@/test/render'

const HEALTH = { body: { status: 'ok', version: '1.0.0', env: 'test', auth_mode: 'local' } }

/** A streamed answer the test drives: send(event, data), then close(). */
function liveAnswer() {
  let controller!: ReadableStreamDefaultController<Uint8Array>
  const body = new ReadableStream<Uint8Array>({ start: (c) => (controller = c) })
  const encoder = new TextEncoder()
  return {
    response: new Response(body, { headers: { 'Content-Type': 'text/event-stream' } }),
    send(event: string, data: unknown) {
      controller.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`))
    },
    close: () => controller.close(),
  }
}

function done(reply: string, extra: object = {}) {
  return {
    conversation_id: 'conv-1',
    message_id: 'answer-1',
    reply,
    provider: 'groq',
    model: 'openai/gpt-oss-120b',
    mode: 'general',
    tool_calls: [],
    actions: [],
    citations: [],
    fallback_used: false,
    fallback_reason: null,
    tokens_in: 10,
    tokens_out: 5,
    stopped: false,
    ...extra,
  }
}

function backend(live: ReturnType<typeof liveAnswer>, extra: Parameters<typeof mockApi>[0] = {}) {
  return mockApi({
    '/api/health': HEALTH,
    'POST /api/conversations': { status: 201, body: { id: 'conv-1' } },
    '/api/conversations/conv-1/messages': async () => live.response,
    'POST /api/conversations/conv-1/stop': { status: 202, body: {} },
    ...extra,
  })
}

async function ask(question = 'What is entropy?') {
  await userEvent.type(screen.getByRole('textbox', { name: 'Message' }), `${question}{Enter}`)
}

const messages = () => screen.getByRole('list', { name: 'Messages' })

describe('Streaming answers', () => {
  it('shows the answer as it arrives, then the saved answer', async () => {
    const live = liveAnswer()
    const fetch = backend(live)
    renderApp('/')
    await ask()

    live.send('token', { text: 'Entropy ' })
    expect(await within(messages()).findByText(/Entropy/)).toBeVisible() // before the end
    live.send('token', { text: 'measures disorder.' })
    expect(await within(messages()).findByText('Entropy measures disorder.')).toBeVisible()

    live.send('done', done('Entropy measures disorder.'))
    live.close()
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Stop' })).not.toBeInTheDocument(),
    )
    expect(within(messages()).getByText('Entropy measures disorder.')).toBeVisible()
    // It asked for a stream (and the server could still answer with plain JSON).
    const [, init] = fetch.mock.calls.find(([url]) => String(url).endsWith('/messages'))!
    expect((init?.headers as Record<string, string>).Accept).toContain('text/event-stream')
  })

  it('has a Stop button while the answer is written, which asks the server to stop', async () => {
    const live = liveAnswer()
    const fetch = backend(live)
    renderApp('/')
    await ask()
    live.send('token', { text: 'Entropy ' })

    await userEvent.click(await screen.findByRole('button', { name: 'Stop' }))

    const stops = fetch.mock.calls.filter(([url]) => String(url).endsWith('/stop'))
    expect(stops).toHaveLength(1)
    // The server ends the answer and sends what it saved.
    live.send('done', done('Entropy\n\n*(Stopped)*', { stopped: true }))
    live.close()
    expect(await within(messages()).findByText('(Stopped)')).toBeVisible()
  })

  it('shows the tools the AI uses while it works', async () => {
    const live = liveAnswer()
    backend(live)
    renderApp('/')
    await ask('list my tasks')

    live.send('tool', {
      name: 'list_tasks',
      arguments: {},
      result: '{"result": []}',
      is_error: false,
      duration_ms: 3,
    })

    const tools = await within(messages()).findByRole('list', { name: 'Tools used' })
    expect(tools).toHaveTextContent('Used tool: list_tasks')
  })

  it('keeps the part of an answer that was cut off, and says so', async () => {
    const live = liveAnswer()
    backend(live, {
      'GET /api/conversations/conv-1': {
        body: {
          id: 'conv-1',
          title: null,
          provider: null,
          model: null,
          mode: 'general',
          created_at: '2026-11-21T10:00:00Z',
          updated_at: '2026-11-21T10:00:00Z',
          documents: [],
          messages: [
            {
              id: 'q1',
              role: 'user',
              content: 'What is entropy?',
              provider: null,
              model: null,
              mode: null,
              fallback_used: false,
              tokens_in: null,
              tokens_out: null,
              created_at: '2026-11-21T10:00:00Z',
            },
            {
              id: 'a1',
              role: 'assistant',
              content: 'Entropy\n\n*(The answer was cut off. You can ask again.)*',
              provider: 'groq',
              model: 'openai/gpt-oss-120b',
              mode: 'general',
              fallback_used: false,
              tokens_in: null,
              tokens_out: null,
              created_at: '2026-11-21T10:00:00Z',
            },
          ],
        },
      },
    })
    renderApp('/')
    await ask()
    live.send('token', { text: 'Entropy ' })

    live.send('error', {
      error: { code: 'service_unavailable', message: 'The answer was cut off (groq: unavailable)' },
      message_id: 'a1',
    })
    live.close()

    expect(await screen.findByText('The answer was cut off (groq: unavailable)')).toBeVisible()
    expect(
      await within(messages()).findByText(/The answer was cut off. You can ask again/),
    ).toBeVisible()
    expect(screen.getByRole('textbox', { name: 'Message' })).toHaveValue('') // it was saved
  })

  it('gives the question back when nothing could be answered', async () => {
    const live = liveAnswer()
    backend(live)
    renderApp('/')
    await ask()

    live.send('error', {
      error: { code: 'service_unavailable', message: 'The AI is unavailable right now' },
      message_id: null,
    })
    live.close()

    await waitFor(() =>
      expect(screen.getByRole('textbox', { name: 'Message' })).toHaveValue('What is entropy?'),
    )
  })
})
