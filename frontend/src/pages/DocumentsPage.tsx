// My documents (wireframe 6.3): upload with real progress, then the list. SMA-47.
//
// An upload goes through: checked in the browser (type, 4 MB) -> "Uploading 45%" (bytes
// sent) -> the backend's own steps, streamed live ("Extracting page 12/30",
// "Embedding 18/30 chunks") -> the document appears in the list as Ready (or Failed: why).
import { useQueryClient } from '@tanstack/react-query'
import { UploadIcon } from 'lucide-react'
import { useRef, useState } from 'react'
import { toast } from 'sonner'

import { DOCUMENTS_KEY, useDeleteDocument, useDocuments, useRetryDocument } from '@/api/documents'
import { DocumentRow } from '@/components/documents/DocumentRow'
import { Button } from '@/components/ui/button'
import { friendlyError } from '@/lib/errors'
import { ACCEPT, checkFile, progressText, type UploadProgress, uploadDocument } from '@/lib/upload'
import { cn } from '@/lib/utils'

type UploadItem = {
  key: string
  file: File
  state: 'waiting' | 'active' | 'error'
  progress?: UploadProgress
  error?: string
}

/** The numbers for a <progress> bar, when the step has them. */
function bar(progress: UploadProgress | undefined): { value: number; max: number } | null {
  if (!progress) return null
  if (progress.stage === 'uploading') return { value: progress.percent, max: 100 }
  if ((progress.stage === 'extracting' || progress.stage === 'embedding') && progress.total) {
    return { value: progress.done ?? 0, max: progress.total }
  }
  return null
}

export function DocumentsPage() {
  const queryClient = useQueryClient()
  const documents = useDocuments()
  const retry = useRetryDocument()
  const remove = useDeleteDocument()
  const input = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  // The upload queue. The ref is the truth (the async loop reads it); the state copy is
  // what React renders.
  const queue = useRef<UploadItem[]>([])
  const [items, setItems] = useState<UploadItem[]>([])
  const running = useRef(false)
  const nextKey = useRef(0)

  function setQueue(next: UploadItem[]) {
    queue.current = next
    setItems(next)
  }
  function update(key: string, change: Partial<UploadItem>) {
    setQueue(queue.current.map((item) => (item.key === key ? { ...item, ...change } : item)))
  }

  function addFiles(files: File[]) {
    const added = files.map((file): UploadItem => {
      const problem = checkFile(file) // checked here first: no point sending a 9 MB file
      const key = `upload-${nextKey.current++}`
      return problem
        ? { key, file, state: 'error', error: problem }
        : { key, file, state: 'waiting' }
    })
    setQueue([...queue.current, ...added])
    void uploadQueued()
  }

  /** One upload at a time, in the order the files were chosen. */
  async function uploadQueued() {
    if (running.current) return // already working through the queue
    running.current = true
    try {
      let next: UploadItem | undefined
      while ((next = queue.current.find((item) => item.state === 'waiting'))) {
        const { key, file } = next
        update(key, { state: 'active' })
        try {
          await uploadDocument(file, (progress) => update(key, { progress }))
          setQueue(queue.current.filter((item) => item.key !== key)) // now in the list
        } catch (error) {
          update(key, { state: 'error', error: friendlyError(error) })
        }
        await queryClient.invalidateQueries({ queryKey: DOCUMENTS_KEY })
      }
    } finally {
      running.current = false
    }
  }

  const onError = { onError: (error: unknown) => toast.error(friendlyError(error)) }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <h1 className="text-2xl font-semibold">Documents</h1>

      <section
        aria-label="Upload documents"
        onDragOver={(e) => {
          e.preventDefault() // allows dropping here
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault() // stops the browser from opening the file
          setDragging(false)
          addFiles([...e.dataTransfer.files])
        }}
        className={cn(
          'flex flex-col items-center gap-3 rounded-xl border-2 border-dashed p-8 text-center',
          dragging ? 'border-primary bg-primary/5' : 'border-muted-foreground/30',
        )}
      >
        <UploadIcon aria-hidden className="size-8 text-muted-foreground" />
        <p>Drag &amp; drop PDF, TXT or MD files here (max 4 MB each)</p>
        <Button variant="outline" onClick={() => input.current?.click()}>
          Browse files
        </Button>
        <input
          ref={input}
          type="file"
          multiple
          accept={ACCEPT}
          aria-label="Choose files"
          className="hidden"
          onChange={(e) => {
            addFiles([...(e.target.files ?? [])])
            e.target.value = '' // so choosing the same file again still works
          }}
        />
      </section>

      {items.length > 0 && (
        <ul aria-label="Uploads" className="space-y-2">
          {items.map((item) => {
            const numbers = bar(item.progress)
            return (
              <li
                key={item.key}
                aria-label={item.file.name}
                className="rounded-lg border p-3 text-sm"
              >
                <div className="flex justify-between gap-3">
                  <span className="font-medium break-all">{item.file.name}</span>
                  <span
                    className={
                      item.state === 'error' ? 'text-destructive' : 'text-muted-foreground'
                    }
                  >
                    {item.state === 'error'
                      ? item.error
                      : item.progress
                        ? progressText(item.progress)
                        : 'Waiting…'}
                  </span>
                </div>
                {item.state === 'active' && numbers && (
                  <progress className="mt-2 h-2 w-full" value={numbers.value} max={numbers.max} />
                )}
              </li>
            )
          })}
        </ul>
      )}

      {documents.isLoading && <p className="text-muted-foreground">Loading documents…</p>}
      {documents.isError && <p className="text-destructive">{friendlyError(documents.error)}</p>}
      {documents.data && documents.data.length === 0 && (
        <p className="text-muted-foreground">No documents yet.</p>
      )}
      {documents.data && documents.data.length > 0 && (
        <table aria-label="My documents" className="w-full text-left text-sm">
          <thead className="border-b text-muted-foreground">
            <tr>
              <th className="py-2 pr-3 font-medium">Name</th>
              <th className="py-2 pr-3 font-medium">Pages</th>
              <th className="py-2 pr-3 font-medium">Status</th>
              <th className="py-2 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {documents.data.map((document) => (
              <DocumentRow
                key={document.id}
                document={document}
                busy={retry.isPending || remove.isPending}
                onRetry={(id) => retry.mutate(id, onError)}
                onDelete={(id) => remove.mutate(id, onError)}
              />
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
