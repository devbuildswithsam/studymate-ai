// Upload a document and follow its ingestion live (guide 7.3, SMA-47).
//
// Why XMLHttpRequest and not fetch: fetch can't tell us how much of the FILE has been
// sent, and the guide wants a real upload percentage. XHR reports both directions:
//   xhr.upload.onprogress -> bytes sent        ("Uploading 45%")
//   xhr.onprogress        -> the answer so far: one JSON event per line (NDJSON),
//                            streamed by the backend while it works ("Embedding 18/30")
import { ApiError, csrfHeader } from '@/api/client'
import type { DocumentInfo } from '@/api/documents'

export const MAX_UPLOAD_BYTES = 4 * 1024 * 1024 // same limit as the backend (4 MB)
const ALLOWED_EXTENSIONS = ['.pdf', '.docx', '.txt', '.md'] // SMA-66: DOCX
export const ACCEPT = ALLOWED_EXTENSIONS.join(',')

/** One step of the ingestion, exactly as the backend streams it. */
export type IngestEvent =
  | { stage: 'extracting'; done?: number; total?: number }
  | { stage: 'chunking' }
  | { stage: 'embedding'; done: number; total: number }
  | { stage: 'summarizing' } // SMA-50: the summary and key points
  | { stage: 'ready'; document?: DocumentInfo }
  | { stage: 'failed'; error: string; document?: DocumentInfo }

export type UploadProgress = { stage: 'uploading'; percent: number } | IngestEvent

/**
 * Checked in the browser BEFORE uploading (the backend checks again: never trust the
 * browser). Returns the problem in words, or null if the file looks fine.
 */
export function checkFile(file: File): string | null {
  const name = file.name.toLowerCase()
  if (!ALLOWED_EXTENSIONS.some((extension) => name.endsWith(extension))) {
    return `${file.name}: only PDF, DOCX, TXT or MD files.`
  }
  if (file.size > MAX_UPLOAD_BYTES) return `${file.name} is larger than 4 MB.`
  if (file.size === 0) return `${file.name} is empty.`
  return null
}

/** What to show for a progress step. */
export function progressText(progress: UploadProgress): string {
  switch (progress.stage) {
    case 'uploading':
      return `Uploading ${progress.percent}%`
    case 'extracting':
      return progress.done
        ? `Extracting page ${progress.done}/${progress.total}`
        : 'Extracting text…'
    case 'chunking':
      return 'Chunking…'
    case 'embedding':
      return `Embedding ${progress.done}/${progress.total} chunks`
    case 'summarizing':
      return 'Writing summary…'
    case 'ready':
      return 'Ready'
    case 'failed':
      return `Failed: ${progress.error}`
  }
}

/** Splits streamed text into complete lines; a half line waits for the rest. */
export class LineSplitter {
  private rest = ''

  push(text: string): string[] {
    const lines = (this.rest + text).split('\n')
    this.rest = lines.pop() ?? '' // the last piece has no "\n" yet
    return lines.filter((line) => line.trim() !== '')
  }
}

/**
 * Upload one file. Calls onProgress for every step and resolves with the final document
 * (ready OR failed: the page shows why). Rejects if the file is refused (413/415) or the
 * server can't be reached.
 */
export function uploadDocument(
  file: File,
  onProgress: (progress: UploadProgress) => void,
): Promise<DocumentInfo> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const lines = new LineSplitter()
    let read = 0 // how much of responseText we've already handled
    let finalDocument: DocumentInfo | undefined

    function readNewLines() {
      if (xhr.status >= 400) return // an error answer is one JSON object, read at the end
      const text = xhr.responseText.slice(read)
      read = xhr.responseText.length
      for (const line of lines.push(text)) {
        const event = JSON.parse(line) as IngestEvent
        onProgress(event)
        if ((event.stage === 'ready' || event.stage === 'failed') && event.document) {
          finalDocument = event.document
        }
      }
    }

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        onProgress({ stage: 'uploading', percent: Math.round((e.loaded / e.total) * 100) })
      }
    }
    xhr.onprogress = readNewLines
    xhr.onload = () => {
      if (xhr.status >= 400) {
        reject(errorFrom(xhr.status, xhr.responseText))
        return
      }
      readNewLines() // anything that arrived with the very last bytes
      if (finalDocument) resolve(finalDocument)
      else reject(new ApiError(xhr.status, 'error', 'The upload ended without a result.'))
    }
    xhr.onerror = () => reject(new Error('network error')) // friendlyError: can't reach

    const form = new FormData()
    form.append('file', file)
    xhr.open('POST', '/api/documents')
    xhr.setRequestHeader('Accept', 'application/x-ndjson, application/json')
    for (const [name, value] of Object.entries(csrfHeader())) {
      xhr.setRequestHeader(name, value) // SMA-58: uploads are writes too
    }
    xhr.send(form)
  })
}

function errorFrom(status: number, text: string): ApiError {
  try {
    const body = JSON.parse(text)
    const error = body?.error
    if (error?.message) return new ApiError(status, error.code, error.message, error.request_id)
  } catch {
    // Not JSON (e.g. the dev proxy's empty 502): use a generic message.
  }
  return new ApiError(status, 'error', `Upload failed (HTTP ${status})`)
}
