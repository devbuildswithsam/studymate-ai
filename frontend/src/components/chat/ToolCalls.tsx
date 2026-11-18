// "Used tool: create_task → …" lines under an AI answer (guide 7.2, SMA-42).
// They show what the AI actually did, so you can check it (and spot a wrong date).
import { WrenchIcon } from 'lucide-react'

import type { ToolCallOut } from '@/api/chat'

/** The arguments as short "key: value" pairs, e.g. "title: Essay, due_date: 2026-11-22". */
function describeArguments(args: ToolCallOut['arguments']): string {
  if (typeof args === 'string') return args // broken JSON from the AI: show it as it was
  return Object.entries(args)
    .map(([key, value]) => `${key}: ${typeof value === 'string' ? value : JSON.stringify(value)}`)
    .join(', ')
}

export function ToolCalls({ calls }: { calls: ToolCallOut[] }) {
  return (
    <ul aria-label="Tools used" className="mt-2 space-y-0.5 text-xs text-muted-foreground">
      {calls.map((call, index) => {
        // A failed call shows the tool's error: the AI saw the same text and could retry.
        const detail = call.is_error ? `failed: ${call.result}` : describeArguments(call.arguments)
        return (
          <li
            key={index}
            title={call.result} // hover: what the tool sent back to the AI
            className={call.is_error ? 'text-destructive' : undefined}
          >
            <WrenchIcon aria-hidden className="mr-1 inline size-3" />
            Used tool: <code>{call.name}</code>
            {detail && ` → ${detail}`}
          </li>
        )
      })}
    </ul>
  )
}
