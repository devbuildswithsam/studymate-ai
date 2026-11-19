// Uploading a document with real progress (SMA-47, test-first).
// A fake XMLHttpRequest plays the browser + server: we decide when bytes are sent and when
// lines of the streamed answer arrive.
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import { checkFile, LineSplitter, progressText, uploadDocument } from '@/lib/upload'

class FakeXhr {
  static last: FakeXhr
  method = ''
  url = ''
  body: FormData | null = null
  status = 0
  responseText = ''
  upload: { onprogress: ((e: ProgressEvent) => void) | null } = { onprogress: null }
  onprogress: (() => void) | null = null
  onload: (() => void) | null = null
  onerror: (() => void) | null = null

  constructor() {
    FakeXhr.last = this
  }
  open(method: string, url: string) {
    this.method = method
    this.url = url
  }
  setRequestHeader() {}
  send(body: FormData) {
    this.body = body
  }
  // --- what the test makes happen ---
  sent(loaded: number, total: number) {
    this.upload.onprogress?.({ lengthComputable: true, loaded, total } as ProgressEvent)
  }
  receive(text: string, status = 201) {
    this.status = status
    this.responseText += text
    this.onprogress?.()
  }
  finish(status = 201) {
    this.status = status
    this.onload?.()
  }
}

const line = (event: object) => JSON.stringify(event) + '\n'
const DOCUMENT = { id: 'd1', filename: 'Physics.pdf', status: 'ready', page_count: 30 }

function start(file = new File(['%PDF-'], 'Physics.pdf')) {
  vi.stubGlobal('XMLHttpRequest', FakeXhr)
  const seen: string[] = []
  const done = uploadDocument(file, (progress) => seen.push(progressText(progress)))
  return { xhr: FakeXhr.last, seen, done }
}

afterEach(() => vi.unstubAllGlobals())

describe('uploadDocument', () => {
  it('posts the file as multipart form data', () => {
    const { xhr } = start()

    expect([xhr.method, xhr.url]).toEqual(['POST', '/api/documents'])
    expect((xhr.body?.get('file') as File).name).toBe('Physics.pdf')
  })

  it('reports the upload percentage, then each event as it arrives, then resolves', async () => {
    const { xhr, seen, done } = start()

    xhr.sent(50, 100)
    xhr.sent(100, 100)
    xhr.receive(line({ stage: 'extracting' }) + line({ stage: 'extracting', done: 12, total: 30 }))
    xhr.receive(line({ stage: 'chunking' }) + line({ stage: 'embedding', done: 18, total: 30 }))
    xhr.receive(line({ stage: 'ready', document: DOCUMENT }))
    xhr.finish()

    await expect(done).resolves.toEqual(DOCUMENT)
    expect(seen).toEqual([
      'Uploading 50%',
      'Uploading 100%',
      'Extracting text…',
      'Extracting page 12/30',
      'Chunking…',
      'Embedding 18/30 chunks',
      'Ready',
    ])
  })

  it('waits for a line that arrives in two pieces', async () => {
    const { xhr, seen, done } = start()
    const text = line({ stage: 'embedding', done: 5, total: 9 })

    xhr.receive(text.slice(0, 10))
    expect(seen).toEqual([]) // half a line: nothing to show yet
    xhr.receive(text.slice(10) + line({ stage: 'ready', document: DOCUMENT }))
    xhr.finish()

    await done
    expect(seen).toEqual(['Embedding 5/9 chunks', 'Ready'])
  })

  it('resolves with a failed document too: the page shows why', async () => {
    const { xhr, done } = start()
    const failed = { ...DOCUMENT, status: 'failed', error: 'No text found' }

    xhr.receive(line({ stage: 'failed', error: 'No text found', document: failed }))
    xhr.finish()

    await expect(done).resolves.toEqual(failed)
  })

  it("rejects with the backend's error when the file is refused (413 / 415)", async () => {
    const { xhr, done } = start()
    const error = { error: { code: 'payload_too_large', message: 'The file is larger than 4 MB.' } }

    xhr.receive(JSON.stringify(error), 413)
    xhr.finish(413)

    await expect(done).rejects.toEqual(
      new ApiError(413, 'payload_too_large', 'The file is larger than 4 MB.'),
    )
  })

  it('rejects when the server cannot be reached', async () => {
    const { xhr, done } = start()

    xhr.onerror?.()

    await expect(done).rejects.toThrow()
    await expect(done).rejects.not.toBeInstanceOf(ApiError) // friendlyError: "Can't reach..."
  })
})

describe('LineSplitter', () => {
  it('returns only complete lines and keeps the rest for later', () => {
    const lines = new LineSplitter()

    expect(lines.push('{"a":1}\n{"b"')).toEqual(['{"a":1}'])
    expect(lines.push(':2}\n')).toEqual(['{"b":2}'])
    expect(lines.push('')).toEqual([])
  })
})

describe('checkFile (in the browser, before any upload)', () => {
  const file = (name: string, bytes: number) => new File([new Uint8Array(bytes)], name)
  const MB = 1024 * 1024

  it('accepts PDF, TXT and MD files up to 4 MB', () => {
    expect(checkFile(file('Physics.pdf', 4 * MB))).toBeNull()
    expect(checkFile(file('notes.TXT', 10))).toBeNull()
    expect(checkFile(file('dbms.md', 10))).toBeNull()
  })

  it('refuses a file over 4 MB', () => {
    expect(checkFile(file('big.pdf', 4 * MB + 1))).toBe('big.pdf is larger than 4 MB.')
  })

  it('refuses other types and empty files', () => {
    expect(checkFile(file('slides.pptx', 10))).toBe('slides.pptx: only PDF, TXT or MD files.')
    expect(checkFile(file('empty.txt', 0))).toBe('empty.txt is empty.')
  })
})

describe('progressText (SMA-50)', () => {
  it('says the summary is being written', () => {
    expect(progressText({ stage: 'summarizing' })).toBe('Writing summary…')
  })
})
