// One row of "My documents" (wireframe 6.3): name, pages, status, actions. SMA-47.
import { RotateCcwIcon, Trash2Icon } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'

import type { DocumentInfo } from '@/api/documents'
import { Button } from '@/components/ui/button'

type Props = {
  document: DocumentInfo
  onRetry: (id: string) => void
  onDelete: (id: string) => void
  busy: boolean // a retry or delete is running: no double clicks
}

function statusText(document: DocumentInfo): string {
  if (document.status === 'ready') return 'Ready'
  if (document.status === 'processing') return 'Processing…'
  return `Failed: ${document.error ?? 'unknown error'}`
}

export function DocumentRow({ document, onRetry, onDelete, busy }: Props) {
  const [confirming, setConfirming] = useState(false)
  const name = document.filename
  return (
    <tr className="border-b last:border-0">
      <td className="py-2 pr-3 font-medium break-all">
        {/* The wireframe's [Open]: the document's page, with its summary (SMA-50). */}
        <Link to={`/documents/${document.id}`} className="hover:underline">
          {name}
        </Link>
      </td>
      <td className="py-2 pr-3 tabular-nums">{document.page_count ?? '—'}</td>
      <td className={document.status === 'failed' ? 'py-2 pr-3 text-destructive' : 'py-2 pr-3'}>
        {statusText(document)}
      </td>
      <td className="py-2">
        {confirming ? (
          <span className="flex items-center gap-1">
            <span className="text-sm">Delete?</span>
            <Button
              size="sm"
              variant="destructive"
              aria-label={`Yes, delete ${name}`}
              disabled={busy}
              onClick={() => onDelete(document.id)}
            >
              Delete
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
          </span>
        ) : (
          <span className="flex items-center gap-1">
            {document.can_retry && (
              <Button
                size="sm"
                variant="outline"
                aria-label={`Retry ${name}`}
                disabled={busy}
                onClick={() => onRetry(document.id)}
              >
                <RotateCcwIcon aria-hidden />
                Retry
              </Button>
            )}
            <Button
              size="icon"
              variant="ghost"
              aria-label={`Delete ${name}`}
              onClick={() => setConfirming(true)}
            >
              <Trash2Icon aria-hidden />
            </Button>
          </span>
        )}
      </td>
    </tr>
  )
}
