// The chat message list. SMA-25 (test-first).
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { MessageList } from '@/components/chat/MessageList'
import type { AgentAction } from '@/api/actions'
import type { Citation, ToolCallOut } from '@/api/chat'
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

describe('MessageList AI actions: confirmation cards and Undo (SMA-43)', () => {
  const action = (
    status: AgentAction['status'],
    extra: Partial<AgentAction> = {},
  ): AgentAction => ({
    id: 'act1',
    tool: 'complete_task',
    kind: 'change',
    status,
    summary: "Mark 'Revise ch.3' as done",
    error: null,
    ...extra,
  })
  const answerWith = (...actions: AgentAction[]): ChatMessage => ({
    id: 'a1',
    role: 'assistant',
    content: 'Please confirm.',
    meta: { modelName: 'GPT-OSS 120B (Groq)', fallbackReason: null, actions },
  })

  it('shows a pending change as a card with Confirm and Cancel', async () => {
    const onAction = vi.fn(async () => {})
    render(<MessageList messages={[answerWith(action('pending'))]} onAction={onAction} />)

    const card = within(screen.getByRole('list', { name: 'AI actions' })).getByRole('listitem')
    expect(card).toHaveTextContent("Mark 'Revise ch.3' as done?")
    await userEvent.click(within(card).getByRole('button', { name: 'Confirm' }))
    expect(onAction).toHaveBeenCalledWith(expect.objectContaining({ id: 'act1' }), 'confirm')
    await userEvent.click(within(card).getByRole('button', { name: 'Cancel' }))
    expect(onAction).toHaveBeenLastCalledWith(expect.objectContaining({ id: 'act1' }), 'cancel')
  })

  it('offers Undo on something the AI created', async () => {
    const onAction = vi.fn(async () => {})
    const created = action('done', {
      tool: 'create_task',
      kind: 'create',
      summary: "Add task 'Essay'",
    })
    render(<MessageList messages={[answerWith(created)]} onAction={onAction} />)

    const card = screen.getByRole('listitem', { name: "Add task 'Essay'" })
    expect(card).toHaveTextContent("Done: Add task 'Essay'")
    await userEvent.click(within(card).getByRole('button', { name: 'Undo' }))
    expect(onAction).toHaveBeenCalledWith(created, 'undo')
  })

  it('shows how each action ended, without buttons', () => {
    render(
      <MessageList
        messages={[
          answerWith(
            action('done', { id: 'x1' }), // a confirmed change: no Undo
            action('cancelled', { id: 'x2' }),
            action('undone', { id: 'x3', kind: 'create', summary: "Add task 'Essay'" }),
            action('failed', { id: 'x4', error: 'No task with id t1.' }),
          ),
        ]}
        onAction={vi.fn()}
      />,
    )

    const cards = within(screen.getByRole('list', { name: 'AI actions' })).getAllByRole('listitem')
    expect(cards.map((c) => c.textContent)).toEqual([
      "Done: Mark 'Revise ch.3' as done",
      "Cancelled: Mark 'Revise ch.3' as done",
      "Undone: Add task 'Essay'",
      "Failed: Mark 'Revise ch.3' as done (No task with id t1.)",
    ])
    expect(screen.queryByRole('button', { name: /Confirm|Cancel|Undo/ })).toBeNull()
  })

  it('keeps the buttons from being clicked twice while waiting', async () => {
    let finish: () => void = () => {}
    const onAction = vi.fn(() => new Promise<void>((resolve) => (finish = resolve)))
    render(<MessageList messages={[answerWith(action('pending'))]} onAction={onAction} />)

    await userEvent.click(screen.getByRole('button', { name: 'Confirm' }))

    expect(screen.getByRole('button', { name: 'Confirm' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
    finish()
  })

  it('says a held tool call is waiting for you', () => {
    const held: ToolCallOut = {
      name: 'complete_task',
      arguments: { task_id: 't1' },
      result: 'Not done yet',
      is_error: false,
      duration_ms: 1,
      held: true,
    }
    render(
      <MessageList
        messages={[
          { ...answerWith(action('pending')), meta: { ...answerWith().meta!, toolCalls: [held] } },
        ]}
      />,
    )

    expect(
      within(screen.getByRole('list', { name: 'Tools used' })).getByRole('listitem'),
    ).toHaveTextContent('Used tool: complete_task → waiting for your confirmation')
  })
})

describe('MessageList study answers (SMA-49)', () => {
  const citation = (n: number, page: number | null = 12): Citation => ({
    n,
    chunk_id: `c${n}`,
    document_id: 'd1',
    filename: 'Physics.pdf',
    page,
    text: 'Force equals mass times acceleration.',
  })
  const grounded = (citations: Citation[]): ChatMessage => ({
    id: 'a1',
    role: 'assistant',
    content: citations.length ? 'F = ma [1] [2].' : "I couldn't find this in your documents.",
    meta: { modelName: 'GPT-OSS 120B (Groq)', fallbackReason: null, grounded: { citations } },
  })

  it('labels a grounded answer "From your documents · n sources" with citation chips', async () => {
    const onCitation = vi.fn()
    render(
      <MessageList
        messages={[grounded([citation(1), citation(2, null)])]}
        onCitation={onCitation}
      />,
    )

    expect(screen.getByText('From your documents · 2 sources')).toBeInTheDocument()
    expect(screen.queryByText('General AI')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: '[1] Physics.pdf p. 12' }))
    expect(onCitation).toHaveBeenCalledWith('a1', 1)
    expect(screen.getByRole('button', { name: '[2] Physics.pdf' })).toBeInTheDocument() // no page
  })

  it('says "1 source", not "1 sources"', () => {
    render(<MessageList messages={[grounded([citation(1)])]} />)

    expect(screen.getByText('From your documents · 1 source')).toBeInTheDocument()
  })

  it('shows the not-found notice with a button to answer from general knowledge', async () => {
    const onAnswerGenerally = vi.fn()
    render(
      <MessageList
        messages={[user('Who won the 1998 World Cup?', 'u1'), grounded([])]}
        onAnswerGenerally={onAnswerGenerally}
      />,
    )

    expect(screen.getByText('Not found in your documents')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Answer from general knowledge' }))
    expect(onAnswerGenerally).toHaveBeenCalledWith('Who won the 1998 World Cup?')
  })
})
