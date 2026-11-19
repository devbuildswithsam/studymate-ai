// Badges under an AI answer (guide §7.5, wireframe 6.9). SMA-26.
// "General AI", "Used tools" (MCP tools, SMA-42), or for study answers (SMA-49, guide 7.5)
// a green "From your documents · n sources" or an amber "Not found in your documents".
import { BookOpenCheckIcon, SearchXIcon, TriangleAlertIcon } from 'lucide-react'

import type { AnswerMeta } from '@/components/chat/types'
import { Badge } from '@/components/ui/badge'

export function MessageBadges({ meta }: { meta: AnswerMeta }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {meta.grounded ? (
        <GroundedBadge count={meta.grounded.citations.length} />
      ) : (
        <Badge variant="secondary">{meta.toolCalls?.length ? 'Used tools' : 'General AI'}</Badge>
      )}
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

function GroundedBadge({ count }: { count: number }) {
  if (count === 0) {
    return (
      <Badge variant="outline" className="border-amber-500 text-amber-700 dark:text-amber-400">
        <SearchXIcon aria-hidden />
        Not found in your documents
      </Badge>
    )
  }
  return (
    <Badge variant="outline" className="border-green-600 text-green-700 dark:text-green-400">
      <BookOpenCheckIcon aria-hidden />
      {`From your documents · ${count} ${count === 1 ? 'source' : 'sources'}`}
    </Badge>
  )
}
