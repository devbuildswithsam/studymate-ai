// Tasks board (wireframe 6.6): To do / Doing / Done, managed without any AI. SMA-40.
// From SMA-41/42 the AI can add tasks too: they show an "AI" marker.
import { PlusIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { type TaskPriority, type TaskStatus, useCreateTask, useTasks } from '@/api/tasks'
import { TaskCard, TaskFields } from '@/components/tasks/TaskCard'
import { Button } from '@/components/ui/button'
import { friendlyError } from '@/lib/errors'

const COLUMNS: { status: TaskStatus; title: string }[] = [
  { status: 'todo', title: 'To do' },
  { status: 'doing', title: 'Doing' },
  { status: 'done', title: 'Done' },
]

type Filter = 'all' | TaskPriority

export function TasksPage() {
  const tasks = useTasks()
  const [adding, setAdding] = useState(false)
  const [filter, setFilter] = useState<Filter>('all')

  const shown = (tasks.data ?? []).filter((t) => filter === 'all' || t.priority === filter)

  return (
    <div className="flex h-full flex-col gap-4">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="mr-auto text-2xl font-semibold">Tasks</h1>
        <Button variant="outline" onClick={() => setAdding(true)} disabled={adding}>
          <PlusIcon aria-hidden />
          New task
        </Button>
        <label className="flex items-center gap-2 text-sm">
          Filter:
          <select
            aria-label="Filter"
            value={filter}
            onChange={(event) => setFilter(event.target.value as Filter)}
            className="rounded-md border bg-background px-2 py-1"
          >
            <option value="all">All</option>
            <option value="high">High priority</option>
            <option value="medium">Medium priority</option>
            <option value="low">Low priority</option>
          </select>
        </label>
      </header>

      {adding && <NewTaskForm onClose={() => setAdding(false)} />}
      {tasks.isError && <p className="text-muted-foreground">Couldn&apos;t load your tasks</p>}
      {tasks.data?.length === 0 && !adding && <p className="text-muted-foreground">No tasks yet</p>}

      <div className="grid flex-1 gap-4 md:grid-cols-3">
        {COLUMNS.map(({ status, title }) => {
          const inColumn = shown.filter((t) => t.status === status)
          return (
            <section
              key={status}
              aria-label={title}
              className="flex flex-col gap-2 rounded-lg bg-muted/40 p-3"
            >
              <h2 className="text-sm font-semibold">
                {title} <span className="text-muted-foreground">({inColumn.length})</span>
              </h2>
              {inColumn.map((task) => (
                <TaskCard key={task.id} task={task} />
              ))}
            </section>
          )
        })}
      </div>
    </div>
  )
}

function NewTaskForm({ onClose }: { onClose: () => void }) {
  const [title, setTitle] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [priority, setPriority] = useState<TaskPriority>('medium')
  const create = useCreateTask()

  return (
    <form
      className="flex max-w-xl flex-col gap-2 rounded-lg border p-3 text-sm"
      onSubmit={(event) => {
        event.preventDefault()
        create.mutate(
          { title: title.trim(), priority, ...(dueDate ? { due_date: dueDate } : {}) },
          { onSuccess: onClose, onError: (error) => toast.error(friendlyError(error)) },
        )
      }}
    >
      <TaskFields
        title={title}
        onTitle={setTitle}
        dueDate={dueDate}
        onDueDate={setDueDate}
        priority={priority}
        onPriority={setPriority}
      />
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={!title.trim() || create.isPending}>
          Add task
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onClose}>
          Cancel
        </Button>
      </div>
    </form>
  )
}
