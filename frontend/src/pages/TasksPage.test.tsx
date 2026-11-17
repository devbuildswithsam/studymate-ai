// Tasks board (wireframe 6.6): To do / Doing / Done, managed without any AI. SMA-40, test-first.
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { mockApi, renderApp } from '@/test/render'

const HEALTH = { body: { status: 'ok', version: '0.1.0', env: 'test', auth_mode: 'local' } }

type FakeTask = {
  id: string
  title: string
  description: string | null
  due_date: string | null
  priority: 'low' | 'medium' | 'high'
  status: 'todo' | 'doing' | 'done'
  document_id: null
  created_by: 'user' | 'ai'
  created_at: string
  completed_at: string | null
}

function task(id: string, title: string, extra: Partial<FakeTask> = {}): FakeTask {
  return {
    id,
    title,
    description: null,
    due_date: null,
    priority: 'medium',
    status: 'todo',
    document_id: null,
    created_by: 'user',
    created_at: '2026-11-16T09:00:00Z',
    completed_at: null,
    ...extra,
  }
}

const PHYSICS = task('t1', 'Revise Phy ch3', { due_date: '2026-11-20', created_by: 'ai' })
const DBMS = task('t2', 'DBMS notes', { due_date: '2026-11-17', status: 'doing', priority: 'high' })
const QUIZ = task('t3', 'Quiz 1', { status: 'done', completed_at: '2026-11-16T12:00:00Z' })

/** A fake tasks backend that remembers creates, edits and deletes. */
function tasksBackend(initial: FakeTask[] = [PHYSICS, DBMS, QUIZ]) {
  let tasks = [...initial]
  let next = 10
  const routes: Parameters<typeof mockApi>[0] = {
    '/api/health': HEALTH,
    'GET /api/tasks': async () => Response.json(tasks),
    'POST /api/tasks': async (init) => {
      const body = JSON.parse(String(init?.body))
      const created = task(`t${next++}`, body.title, body)
      tasks = [...tasks, created]
      return Response.json(created, { status: 201 })
    },
  }
  for (const id of ['t1', 't2', 't3', 't10']) {
    routes[`PATCH /api/tasks/${id}`] = async (init) => {
      const changes = JSON.parse(String(init?.body))
      tasks = tasks.map((t) => (t.id === id ? { ...t, ...changes } : t))
      return Response.json(tasks.find((t) => t.id === id))
    }
    routes[`DELETE /api/tasks/${id}`] = async () => {
      tasks = tasks.filter((t) => t.id !== id)
      return new Response(null, { status: 204 })
    }
  }
  return mockApi(routes)
}

const column = (name: string) => screen.getByRole('region', { name })
const card = (title: string) => screen.getByRole('article', { name: title })

function requests(fetch: ReturnType<typeof mockApi>, method: string) {
  return fetch.mock.calls
    .filter(([, init]) => init?.method === method)
    .map(([url, init]) => [url, init?.body ? JSON.parse(String(init.body)) : undefined])
}

describe('Tasks board', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] }) // only the clock: "today" is Tue 17 Nov 2026
    vi.setSystemTime(new Date(2026, 10, 17, 10, 0))
  })
  afterEach(() => vi.useRealTimers())

  it('shows each task in its column with its due date, priority and the AI marker', async () => {
    tasksBackend()
    renderApp('/tasks')

    expect(await within(column('To do')).findByText('Revise Phy ch3')).toBeInTheDocument()
    expect(within(column('Doing')).getByText('DBMS notes')).toBeInTheDocument()
    expect(within(column('Done')).getByText('Quiz 1')).toBeInTheDocument()

    expect(within(card('Revise Phy ch3')).getByText('Due Fri')).toBeInTheDocument()
    expect(within(card('Revise Phy ch3')).getByLabelText('Created by the AI')).toBeInTheDocument()
    expect(within(card('DBMS notes')).getByText('Due today')).toBeInTheDocument()
    expect(within(card('DBMS notes')).getByText('high')).toBeInTheDocument()
    expect(within(card('DBMS notes')).queryByLabelText('Created by the AI')).toBeNull()
  })

  it('creates a task in To do', async () => {
    const fetch = tasksBackend([])
    renderApp('/tasks')
    await screen.findByText('No tasks yet')

    await userEvent.click(screen.getByRole('button', { name: 'New task' }))
    await userEvent.type(screen.getByRole('textbox', { name: 'Title' }), 'Lab report')
    await userEvent.type(screen.getByLabelText('Due date'), '2026-11-18')
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Priority' }), 'high')
    await userEvent.click(screen.getByRole('button', { name: 'Add task' }))

    expect(await within(column('To do')).findByText('Lab report')).toBeInTheDocument()
    expect(requests(fetch, 'POST')).toEqual([
      ['/api/tasks', { title: 'Lab report', due_date: '2026-11-18', priority: 'high' }],
    ])
    expect(screen.queryByRole('textbox', { name: 'Title' })).toBeNull() // the form closes
  })

  it('a task without a due date is sent without one', async () => {
    const fetch = tasksBackend([])
    renderApp('/tasks')
    await userEvent.click(await screen.findByRole('button', { name: 'New task' }))

    await userEvent.type(screen.getByRole('textbox', { name: 'Title' }), 'Someday reading{Enter}')

    expect(await within(column('To do')).findByText('Someday reading')).toBeInTheDocument()
    expect(requests(fetch, 'POST')).toEqual([
      ['/api/tasks', { title: 'Someday reading', priority: 'medium' }], // no "due_date": ""
    ])
  })

  it('a task needs a title', async () => {
    tasksBackend([])
    renderApp('/tasks')
    await userEvent.click(await screen.findByRole('button', { name: 'New task' }))

    expect(screen.getByRole('button', { name: 'Add task' })).toBeDisabled()
  })

  it('moves a task To do -> Doing -> Done -> back to To do', async () => {
    const fetch = tasksBackend([PHYSICS])
    renderApp('/tasks')
    await within(column('To do')).findByText('Revise Phy ch3')

    await userEvent.click(within(card('Revise Phy ch3')).getByRole('button', { name: 'Start' }))
    await within(column('Doing')).findByText('Revise Phy ch3')
    await userEvent.click(within(card('Revise Phy ch3')).getByRole('button', { name: 'Done' }))
    await within(column('Done')).findByText('Revise Phy ch3')
    await userEvent.click(within(card('Revise Phy ch3')).getByRole('button', { name: 'Reopen' }))

    await within(column('To do')).findByText('Revise Phy ch3')
    expect(requests(fetch, 'PATCH').map(([, body]) => body)).toEqual([
      { status: 'doing' },
      { status: 'done' },
      { status: 'todo' },
    ])
  })

  it('edits a task', async () => {
    const fetch = tasksBackend([DBMS])
    renderApp('/tasks')
    await userEvent.click(
      await within(await screen.findByRole('article', { name: 'DBMS notes' })).findByRole(
        'button',
        {
          name: 'Edit',
        },
      ),
    )

    const title = within(card('DBMS notes')).getByRole('textbox', { name: 'Title' })
    await userEvent.clear(title)
    await userEvent.type(title, 'DBMS normal forms')
    await userEvent.clear(within(card('DBMS notes')).getByLabelText('Due date')) // remove the date
    await userEvent.click(within(card('DBMS notes')).getByRole('button', { name: 'Save' }))

    expect(await screen.findByRole('article', { name: 'DBMS normal forms' })).toBeInTheDocument()
    expect(requests(fetch, 'PATCH')).toEqual([
      [
        '/api/tasks/t2',
        { title: 'DBMS normal forms', due_date: null, priority: 'high', description: null },
      ],
    ])
  })

  it('deletes a task after confirming, and Cancel keeps it', async () => {
    const fetch = tasksBackend([QUIZ])
    renderApp('/tasks')
    await userEvent.click(
      await within(await screen.findByRole('article', { name: 'Quiz 1' })).findByRole('button', {
        name: 'Delete',
      }),
    )

    expect(within(card('Quiz 1')).getByText('Delete this task?')).toBeInTheDocument()
    await userEvent.click(within(card('Quiz 1')).getByRole('button', { name: 'Cancel' }))
    expect(requests(fetch, 'DELETE')).toEqual([])

    await userEvent.click(within(card('Quiz 1')).getByRole('button', { name: 'Delete' }))
    await userEvent.click(within(card('Quiz 1')).getByRole('button', { name: 'Yes, delete' }))

    await waitFor(() => expect(screen.queryByRole('article', { name: 'Quiz 1' })).toBeNull())
    expect(requests(fetch, 'DELETE')).toEqual([['/api/tasks/t3', undefined]])
  })

  it('filters the board by priority', async () => {
    tasksBackend()
    renderApp('/tasks')
    await screen.findByText('Revise Phy ch3')

    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Filter' }), 'high')

    expect(screen.queryByText('Revise Phy ch3')).toBeNull()
    expect(screen.getByText('DBMS notes')).toBeInTheDocument()
  })

  it('shows overdue tasks as overdue', async () => {
    tasksBackend([task('t1', 'Old essay', { due_date: '2026-11-15' })])
    renderApp('/tasks')

    expect(await screen.findByText('Overdue · 15 Nov')).toBeInTheDocument()
  })

  it('says so when the tasks cannot be loaded', async () => {
    mockApi({ '/api/health': HEALTH }) // GET /api/tasks -> 404
    renderApp('/tasks')

    expect(await screen.findByText("Couldn't load your tasks")).toBeInTheDocument()
  })
})
