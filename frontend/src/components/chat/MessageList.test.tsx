// The chat message list. SMA-25 (test-first).
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { MessageList } from '@/components/chat/MessageList'
import type { ToolCallOut } from '@/api/chat'
import type { ChatMessage } from '@/components/chat/types'

const user = (content: string, id = 'u1'): ChatMessage => ({ id, role: 'user', content })
const ai = (content: string, id = 'a1'): ChatMessage => ({ id, role: 'assistant', content })

describe('MessageList', () => {
  it('shows the messages in order, labelled by who wrote them', () => {
    render(<MessageList messages={[user('What is osmosis?'), ai('Water moves.')]} />)

    const items = within(screen.getByRole('list', { name: 'Messages' })).getAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(items[0]).toHaveTextContent('You')
    expect(items[0]).toHaveTextContent('What is osmosis?')
    expect(items[1]).toHaveTextContent('StudyMate')
    expect(items[1]).toHaveTextContent('Water moves.')
  })

  it('shows the user text exactly as typed (no Markdown)', () => {
    render(<MessageList messages={[user('**not bold**')]} />)

    expect(screen.getByText('**not bold**')).toBeInTheDocument()
  })

  it('renders Markdown in AI answers: bold, tables and code', () => {
    const answer = [
      'Newton says **F = ma**.',
      '',
      '| Law | Idea |',
      '| --- | --- |',
      '| 1st | Inertia |',
      '',
      '```python',
      'force = mass * acceleration',
      '```',
    ].join('\n')

    render(<MessageList messages={[ai(answer)]} />)

    expect(screen.getByText('F = ma').tagName).toBe('STRONG')
    expect(screen.getByRole('table')).toHaveTextContent('Inertia')
    expect(screen.getByText('force = mass * acceleration').closest('pre')).not.toBeNull()
  })

  it('renders maths with KaTeX', () => {
    const { container } = render(<MessageList messages={[ai('Energy: $E = mc^2$')]} />)

    expect(container.querySelector('.katex')).not.toBeNull()
  })

  it('never turns raw HTML in an answer into real elements (XSS)', () => {
    const attack = 'Hi <img src="x" onerror="alert(1)"> and <b>bold?</b> <script>alert(2)</script>'

    const { container } = render(<MessageList messages={[ai(attack)]} />)

    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('b')).toBeNull()
    expect(container.querySelector('script')).toBeNull()
  })

  it('shows a thinking indicator while waiting for the answer', () => {
    render(<MessageList messages={[user('Hi')]} isThinking />)

    expect(screen.getByRole('status')).toHaveTextContent('StudyMate is thinking…')
  })

  it('has no thinking indicator otherwise', () => {
    render(<MessageList messages={[user('Hi')]} />)

    expect(screen.queryByRole('status')).toBeNull()
  })

  it('has a Copy button only on AI answers, which copies the original text', async () => {
    const writeText = vi.fn(async () => {})
    const clipboard = { writeText }
    vi.stubGlobal('navigator', { ...navigator, clipboard })
    render(<MessageList messages={[user('Q'), ai('**Answer** text', 'a1')]} />)

    const buttons = screen.getAllByRole('button', { name: 'Copy answer' })
    expect(buttons).toHaveLength(1)
    await userEvent.click(buttons[0])

    expect(writeText).toHaveBeenCalledWith('**Answer** text') // the Markdown, not the HTML
    expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument()
  })
})

describe('MessageList badges (SMA-26)', () => {
  const answered = (meta: ChatMessage['meta']): ChatMessage => ({
    id: 'a1',
    role: 'assistant',
    content: 'An answer.',
    meta,
  })

  it('shows "General AI" and the model on every answer', () => {
    render(
      <MessageList
        messages={[answered({ modelName: 'Gemini 3.5 Flash', fallbackReason: null })]}
      />,
    )

    const answer = screen.getAllByRole('listitem')[0]
    expect(within(answer).getByText('General AI')).toBeInTheDocument()
    expect(within(answer).getByText('Gemini 3.5 Flash')).toBeInTheDocument()
    expect(screen.queryByText('fallback')).toBeNull()
  })

  it('shows a fallback warning with the reason on hover and for screen readers', () => {
    const reason = 'gemini-3.5-flash: rate-limited'
    render(
      <MessageList
        messages={[answered({ modelName: 'GPT-OSS 120B (Groq)', fallbackReason: reason })]}
      />,
    )

    const warning = screen.getByLabelText(`Fallback used: ${reason}`)
    expect(warning).toHaveTextContent('fallback')
    expect(warning).toHaveAttribute('title', reason) // the hover text
    expect(screen.getByText('GPT-OSS 120B (Groq)')).toBeInTheDocument()
  })

  it('shows no badges on your own messages', () => {
    render(<MessageList messages={[user('Hi')]} />)

    expect(screen.queryByText('General AI')).toBeNull()
  })
})

describe('MessageList tool calls (SMA-42)', () => {
  const withTools = (toolCalls: ToolCallOut[]): ChatMessage => ({
    id: 'a1',
    role: 'assistant',
    content: 'Added it.',
    meta: { modelName: 'GPT-OSS 120B (Groq)', fallbackReason: null, toolCalls },
  })
  const tool = (name: string, args: ToolCallOut['arguments'], isError = false): ToolCallOut => ({
    name,
    arguments: args,
    result: isError ? 'Input validation error: priority must be low, medium or high' : '{}',
    is_error: isError,
    duration_ms: 12,
  })

  it('shows a "Used tool" line for each tool the AI used, with its arguments', () => {
    render(
      <MessageList
        messages={[
          withTools([
            tool('create_task', { title: 'Finish thermodynamics notes', due_date: '2026-11-22' }),
            tool('list_tasks', {}),
          ]),
        ]}
      />,
    )

    const lines = within(screen.getByRole('list', { name: 'Tools used' })).getAllByRole('listitem')
    expect(lines.map((l) => l.textContent)).toEqual([
      'Used tool: create_task → title: Finish thermodynamics notes, due_date: 2026-11-22',
      'Used tool: list_tasks',
    ])
  })

  it('marks a failed tool call and says why', () => {
    render(
      <MessageList messages={[withTools([tool('create_task', { priority: 'urgent' }, true)])]} />,
    )

    const line = within(screen.getByRole('list', { name: 'Tools used' })).getByRole('listitem')
    expect(line).toHaveTextContent('failed: Input validation error: priority must be')
  })

  it('labels the answer "Used tools" instead of "General AI"', () => {
    render(<MessageList messages={[withTools([tool('list_tasks', {})])]} />)

    expect(screen.getByText('Used tools')).toBeInTheDocument()
    expect(screen.queryByText('General AI')).toBeNull()
  })

  it('shows no tool list on a plain answer', () => {
    render(<MessageList messages={[ai('Water moves.')]} />)

    expect(screen.queryByRole('list', { name: 'Tools used' })).toBeNull()
  })
})
