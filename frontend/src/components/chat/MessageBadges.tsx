// Badges under an AI answer (guide §7.5, wireframe 6.9). SMA-26.
// "General AI", or "Used tools" when the AI used MCP tools (SMA-42); Stage 4 adds "From your documents" / "Not found in your documents".
import { TriangleAlertIcon } from 'lucide-react'

import type { AnswerMeta } from '@/components/chat/types'
import { Badge } from '@/components/ui/badge'

export function MessageBadges({ meta }: { meta: AnswerMeta }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Badge variant="secondary">{meta.toolCalls?.length ? 'Used tools' : 'General AI'}</Badge>
      <Badge variant="outline">{meta.modelName}</Badge>
      {meta.fallbackReason && (
        // title = the reason on hover; aria-label = the same for screen readers
        // (hover alone isn't accessible).
        <Badge
          variant="outline"
          title={meta.fallbackReason}
          aria-label={`Fallback used: ${meta.fallbackReason}`}
          className="border-amber-500 text-amber-700 dark:text-amber-400"
        >
          <TriangleAlertIcon aria-hidden />
          fallback
        </Badge>
      )}
    </div>
  )
}
