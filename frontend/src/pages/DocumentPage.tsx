// One document (wireframe 6.4): its summary and key points, regenerated on request. SMA-50.
//
// The summary was written once, when the document was ingested, and saved: opening this
// page only reads it (no AI call). "Regenerate" is the only thing that asks the AI again.
import { useState } from 'react'
import { Link, useParams } from 'react-router'

import { ApiError } from '@/api/client'
import { useDocument, useRegenerateSummary } from '@/api/documents'
import { Button } from '@/components/ui/button'
import { friendlyError } from '@/lib/errors'
import { cn } from '@/lib/utils'

type Tab = 'summary' | 'key-points'
const TABS: { id: Tab; label: string }[] = [
  { id: 'summary', label: 'Summary' },
  { id: 'key-points', label: 'Key points' },
]

export function DocumentPage() {
  const { documentId = '' } = useParams()
  const document = useDocument(documentId)
  const regenerate = useRegenerateSummary(documentId)
  const [tab, setTab] = useState<Tab>('summary')
  const [style, setStyle] = useState<'short' | 'detailed'>('short')

  if (document.isLoading) return <p className="text-muted-foreground">Loading document…</p>
  if (document.isError || !document.data) {
    const gone = document.error instanceof ApiError && document.error.status === 404
    return (
      <div className="mx-auto max-w-3xl space-y-3">
        <h1 className="text-2xl font-semibold">Document</h1>
        <p className="text-muted-foreground">
          {gone
            ? "This document doesn't exist (maybe it was deleted)."
            : friendlyError(document.error)}
        </p>
        <Link to="/documents" className="text-sm underline">
          Back to my documents
        </Link>
      </div>
    )
  }

  const doc = document.data
  const ready = doc.status === 'ready'
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold break-all">{doc.filename}</h1>
          <p className="text-sm text-muted-foreground">
            {doc.page_count !== null && `${doc.page_count} pages`}
            {doc.status === 'failed' && `Failed: ${doc.error}`}
            {doc.status === 'processing' && 'Processing…'}
          </p>
        </div>
        {ready && (
          <div className="flex gap-2">
            <Button asChild variant="outline">
              {/* Opens a new study chat with this document already picked (SMA-49). */}
              <Link to="/study" state={{ documents: [{ id: doc.id, filename: doc.filename }] }}>
                Chat with this document
              </Link>
            </Button>
            <Button asChild variant="outline">
              {/* SMA-63: the Quizzes page, with this document already picked. */}
              <Link to="/quizzes" state={{ documentId: doc.id }}>
                Make a quiz
              </Link>
            </Button>
          </div>
        )}
      </header>

      <div role="tablist" aria-label="Document views" className="flex gap-1 border-b">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls={`panel-${t.id}`}
            onClick={() => setTab(t.id)}
            className={cn(
              '-mb-px border-b-2 px-3 py-2 text-sm',
              tab === t.id
                ? 'border-primary font-medium'
                : 'border-transparent text-muted-foreground',
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      <section
        role="tabpanel"
        id={`panel-${tab}`}
        aria-labelledby={`tab-${tab}`}
        className="space-y-4"
      >
        {ready && (
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-2 text-sm">
              Style
              <select
                aria-label="Style"
                value={style}
                onChange={(e) => setStyle(e.target.value as 'short' | 'detailed')}
                className="rounded-md border bg-background px-2 py-1"
              >
                <option value="short">Short</option>
                <option value="detailed">Detailed</option>
              </select>
            </label>
            <Button
              size="sm"
              variant="outline"
              disabled={regenerate.isPending}
              onClick={() => regenerate.mutate(style)}
            >
              {regenerate.isPending ? 'Writing…' : 'Regenerate'}
            </Button>
          </div>
        )}
        {regenerate.isError && (
          <p role="alert" className="text-sm text-destructive">
            {/* The backend's own sentence says what went wrong and what to do (a 503 can
                also mean "the AI sent an unexpected answer", not only "busy"). */}
            {regenerate.error instanceof ApiError
              ? regenerate.error.message
              : friendlyError(regenerate.error)}
          </p>
        )}

        {!doc.summary ? (
          <p className="text-muted-foreground">
            No summary yet.{ready && ' Click Regenerate to write one.'}
          </p>
        ) : tab === 'summary' ? (
          <p className="leading-relaxed whitespace-pre-line">{doc.summary}</p>
        ) : (
          <ul className="list-disc space-y-1 pl-5">
            {(doc.key_points ?? []).map((point, i) => (
              <li key={i}>{point}</li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
