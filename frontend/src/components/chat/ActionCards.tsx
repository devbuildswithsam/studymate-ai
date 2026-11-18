// Under an AI answer: what the AI changed or wants to change (guide 7.2). SMA-43.
// pending -> a card: Confirm / Cancel. A create that ran -> Undo. Otherwise: how it ended.
import { useState } from 'react'

import type { ActionVerb, AgentAction } from '@/api/actions'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

type Props = {
  actions: AgentAction[]
  onAction: (action: AgentAction, verb: ActionVerb) => Promise<unknown>
}

const ENDED: Record<AgentAction['status'], string> = {
  pending: '',
  done: 'Done',
  cancelled: 'Cancelled',
  undone: 'Undone',
  failed: 'Failed',
}

export function ActionCards({ actions, onAction }: Props) {
  return (
    <ul aria-label="AI actions" className="mt-3 space-y-2">
      {actions.map((action) => (
        <ActionCard key={action.id} action={action} onAction={onAction} />
      ))}
    </ul>
  )
}

function ActionCard({ action, onAction }: { action: AgentAction; onAction: Props['onAction'] }) {
  const [busy, setBusy] = useState(false) // one click at a time: no double confirm

  async function act(verb: ActionVerb) {
    setBusy(true)
    try {
      await onAction(action, verb)
    } catch {
      // The page shows the error; the buttons come back so you can try again.
    } finally {
      setBusy(false)
    }
  }

  const pending = action.status === 'pending'
  const canUndo = action.status === 'done' && action.kind === 'create'
  return (
    <li
      aria-label={action.summary}
      className={cn(
        'flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2 text-sm',
        pending ? 'border-amber-500 bg-background' : 'text-muted-foreground',
      )}
    >
      <span>
        {pending ? `${action.summary}?` : `${ENDED[action.status]}: ${action.summary}`}
        {action.status === 'failed' && action.error && ` (${action.error})`}
      </span>
      {pending && (
        <span className="flex gap-2">
          <Button size="sm" disabled={busy} onClick={() => act('confirm')}>
            Confirm
          </Button>
          <Button size="sm" variant="outline" disabled={busy} onClick={() => act('cancel')}>
            Cancel
          </Button>
        </span>
      )}
      {canUndo && (
        <Button size="sm" variant="outline" disabled={busy} onClick={() => act('undo')}>
          Undo
        </Button>
      )}
    </li>
  )
}
