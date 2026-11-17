// One card on the tasks board (wireframe 6.6): move, edit or delete it. SMA-40.
import { SparklesIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import {
  type Task,
  type TaskChanges,
  type TaskPriority,
  useDeleteTask,
  useUpdateTask,
} from '@/api/tasks'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { dueLabel } from '@/lib/dates'
import { friendlyError } from '@/lib/errors'
import { cn } from '@/lib/utils'

type Mode = 'show' | 'edit' | 'confirm-delete'

export function TaskCard({ task }: { task: Task }) {
  const [mode, setMode] = useState<Mode>('show')
  const update = useUpdateTask()
  const remove = useDeleteTask()
  const onError = (error: unknown) => toast.error(friendlyError(error))

  function change(changes: TaskChanges, onDone?: () => void) {
    update.mutate({ id: task.id, changes }, { onSuccess: onDone, onError })
  }

  return (
    // aria-label: screen readers (and tests) can find a card by its title.
    <article
      aria-label={task.title}
      className="rounded-lg border bg-background p-3 text-sm shadow-xs"
    >
      {mode === 'edit' ? (
        <EditTask
          task={task}
          onSave={(changes) => change(changes, () => setMode('show'))}
          onCancel={() => setMode('show')}
        />
      ) : (
        <>
          <div className="flex items-start justify-between gap-2">
            <h3 className="font-medium">{task.title}</h3>
            {task.created_by === 'ai' && (
              <Badge variant="secondary" aria-label="Created by the AI" title="Created by the AI">
                <SparklesIcon aria-hidden />
                AI
              </Badge>
            )}
          </div>
          {task.description && <p className="mt-1 text-muted-foreground">{task.description}</p>}
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {task.due_date && task.status !== 'done' && <DueDate dueDate={task.due_date} />}
            <Badge variant="outline">{task.priority}</Badge>
          </div>

          {mode === 'confirm-delete' ? (
            <div className="mt-3 flex items-center gap-2 rounded-md border p-2">
              <span>Delete this task?</span>
              <Button
                size="xs"
                variant="destructive"
                disabled={remove.isPending}
                onClick={() => remove.mutate(task.id, { onError })}
              >
                Yes, delete
              </Button>
              <Button size="xs" variant="ghost" onClick={() => setMode('show')}>
                Cancel
              </Button>
            </div>
          ) : (
            <div className="mt-3 flex flex-wrap gap-1">
              {task.status === 'todo' && (
                <Button size="xs" variant="outline" onClick={() => change({ status: 'doing' })}>
                  Start
                </Button>
              )}
              {task.status === 'doing' && (
                <Button size="xs" variant="outline" onClick={() => change({ status: 'todo' })}>
                  Back
                </Button>
              )}
              {task.status !== 'done' ? (
                <Button size="xs" variant="outline" onClick={() => change({ status: 'done' })}>
                  Done
                </Button>
              ) : (
                <Button size="xs" variant="outline" onClick={() => change({ status: 'todo' })}>
                  Reopen
                </Button>
              )}
              <Button size="xs" variant="ghost" onClick={() => setMode('edit')}>
                Edit
              </Button>
              <Button size="xs" variant="ghost" onClick={() => setMode('confirm-delete')}>
                Delete
              </Button>
            </div>
          )}
        </>
      )}
    </article>
  )
}

function DueDate({ dueDate }: { dueDate: string }) {
  const { label, overdue } = dueLabel(dueDate)
  return (
    <span
      className={cn('text-xs', overdue ? 'font-medium text-destructive' : 'text-muted-foreground')}
    >
      {label}
    </span>
  )
}

type EditProps = { task: Task; onSave: (changes: TaskChanges) => void; onCancel: () => void }

function EditTask({ task, onSave, onCancel }: EditProps) {
  const [title, setTitle] = useState(task.title)
  const [dueDate, setDueDate] = useState(task.due_date ?? '')
  const [priority, setPriority] = useState<TaskPriority>(task.priority)
  const [description, setDescription] = useState(task.description ?? '')

  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(event) => {
        event.preventDefault()
        // Empty fields are sent as null: that clears them on the server.
        onSave({
          title: title.trim(),
          due_date: dueDate || null,
          priority,
          description: description.trim() || null,
        })
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
      <textarea
        aria-label="Description"
        placeholder="Description (optional)"
        value={description}
        maxLength={2000}
        onChange={(event) => setDescription(event.target.value)}
        className="rounded-md border bg-background px-2 py-1"
      />
      <div className="flex gap-2">
        <Button type="submit" size="xs" disabled={!title.trim()}>
          Save
        </Button>
        <Button type="button" size="xs" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

type FieldsProps = {
  title: string
  onTitle: (value: string) => void
  dueDate: string
  onDueDate: (value: string) => void
  priority: TaskPriority
  onPriority: (value: TaskPriority) => void
}

/** Title, due date and priority inputs, shared by "New task" and "Edit". */
export function TaskFields(props: FieldsProps) {
  return (
    <>
      <input
        aria-label="Title"
        placeholder="What to do"
        value={props.title}
        maxLength={200}
        autoFocus
        onChange={(event) => props.onTitle(event.target.value)}
        className="rounded-md border bg-background px-2 py-1"
      />
      <div className="flex gap-2">
        <input
          type="date"
          aria-label="Due date"
          value={props.dueDate}
          onChange={(event) => props.onDueDate(event.target.value)}
          className="rounded-md border bg-background px-2 py-1"
        />
        <select
          aria-label="Priority"
          value={props.priority}
          onChange={(event) => props.onPriority(event.target.value as TaskPriority)}
          className="rounded-md border bg-background px-2 py-1"
        >
          <option value="low">low</option>
          <option value="medium">medium</option>
          <option value="high">high</option>
        </select>
      </div>
    </>
  )
}
