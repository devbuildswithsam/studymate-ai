// Documents page (wireframe 6.3): upload with real progress, list, retry, delete.
// SMA-47, test-first. fetch is faked; uploadDocument is replaced so each test decides
// which progress events arrive, and when.
import { act, fireEvent, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import type { DocumentInfo } from '@/api/documents'
import { type UploadProgress, uploadDocument } from '@/lib/upload'
import { mockApi, renderApp } from '@/test/render'

vi.mock('@/lib/upload', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/upload')>()), // checkFile etc. stay real
  uploadDocument: vi.fn(),
}))

const HEALTH = { body: { status: 'ok', version: '0.1.0', env: 'test', auth_mode: 'local' } }
const MB = 1024 * 1024

function doc(id: string, filename: string, extra: Partial<DocumentInfo> = {}): DocumentInfo {
  return {
    id,
    filename,
    mime_type: 'application/pdf',
    size_bytes: 1000,
    page_count: 30,
    status: 'ready',
    error: null,
    summary: null,
    key_points: null,
    created_at: '2026-11-19T09:00:00Z',
    can_retry: false,
    ...extra,
  }
}

/** A fake documents backend that remembers retries and deletes. */
function documentsBackend(initial: DocumentInfo[]) {
  let documents = [...initial]
  const routes: Parameters<typeof mockApi>[0] = {
    '/api/health': HEALTH,
    'GET /api/documents': async () => Response.json(documents),
  }
  for (const d of initial) {
    routes[`POST /api/documents/${d.id}/retry`] = async () => {
      documents = documents.map((x) =>
        x.id === d.id ? { ...x, status: 'ready', can_retry: false, error: null } : x,
      )
      return Response.json(documents.find((x) => x.id === d.id))
    }
    routes[`DELETE /api/documents/${d.id}`] = async () => {
      documents = documents.filter((x) => x.id !== d.id)
      return new Response(null, { status: 204 })
    }
  }
  return {
    fetch: mockApi(routes),
    add: (d: DocumentInfo) => (documents = [d, ...documents]),
  }
}

/** Make uploadDocument controllable: send(progress) and finish(document) from the test. */
function controlUpload() {
  type Controls = {
    send: (progress: UploadProgress) => void
    finish: (document: DocumentInfo) => void
    fail: (error: Error) => void
  }
  const upload = {} as Controls // filled in when the page starts the upload
  vi.mocked(uploadDocument).mockImplementation(
    (_file, onProgress) =>
      new Promise((resolve, reject) => {
        upload.send = (p) => act(() => onProgress(p))
        upload.finish = (d) => act(() => resolve(d))
        upload.fail = (e) => act(() => reject(e))
      }),
  )
  return upload
}

const pdf = (name = 'Physics.pdf', bytes = 1000) => new File([new Uint8Array(bytes)], name)
const chooseFiles = (...files: File[]) =>
  userEvent.upload(screen.getByLabelText('Choose files'), files, { applyAccept: false })
const table = () => screen.getByRole('table', { name: 'My documents' })
const row = (name: string) => within(table()).getByRole('row', { name: new RegExp(name) })
const uploads = () => screen.getByRole('list', { name: 'Uploads' })

// Braces matter: a function RETURNED from beforeEach is run as cleanup after the test, and
// mockReset() returns the mock itself, which would then be "called" as cleanup.
beforeEach(() => {
  vi.mocked(uploadDocument).mockReset()
})

describe('Documents page', () => {
  it('shows my documents with their pages and status', async () => {
    documentsBackend([
      doc('d1', 'Physics.pdf'),
      doc('d2', 'Scan.pdf', { status: 'failed', page_count: 8, error: 'No text found.' }),
      doc('d3', 'notes.md', { mime_type: 'text/markdown', page_count: null, status: 'processing' }),
    ])
    renderApp('/documents')

    expect(await screen.findByRole('row', { name: /Physics\.pdf/ })).toHaveTextContent('30')
    expect(row('Physics.pdf')).toHaveTextContent('Ready')
    expect(row('Scan.pdf')).toHaveTextContent('Failed: No text found.')
    expect(row('notes.md')).toHaveTextContent('—') // no pages for text files
    expect(row('notes.md')).toHaveTextContent('Processing')
  })

  it('says how to add documents, with the 4 MB limit', async () => {
    documentsBackend([])
    renderApp('/documents')

    expect(await screen.findByText(/No documents yet/)).toBeInTheDocument()
    expect(screen.getByText(/PDF, TXT or MD/)).toHaveTextContent('max 4 MB')
  })

  it('Done when: an upload shows real progress through to Ready', async () => {
    const backend = documentsBackend([])
    const upload = controlUpload()
    renderApp('/documents')
    await screen.findByText(/No documents yet/)

    await chooseFiles(pdf())
    const item = within(uploads()).getByRole('listitem', { name: 'Physics.pdf' })
    upload.send({ stage: 'uploading', percent: 45 })
    expect(item).toHaveTextContent('Uploading 45%')
    upload.send({ stage: 'extracting', done: 12, total: 30 })
    expect(item).toHaveTextContent('Extracting page 12/30')
    upload.send({ stage: 'chunking' })
    upload.send({ stage: 'embedding', done: 18, total: 30 })
    expect(item).toHaveTextContent('Embedding 18/30 chunks')
    expect(within(item).getByRole('progressbar')).toHaveAttribute('value', '18')

    backend.add(doc('d9', 'Physics.pdf'))
    upload.finish(doc('d9', 'Physics.pdf'))

    expect(await screen.findByRole('row', { name: /Physics\.pdf/ })).toHaveTextContent('Ready')
    expect(screen.queryByRole('list', { name: 'Uploads' })).toBeNull() // done: only the list
  })

  it('uploads several files one after another', async () => {
    documentsBackend([])
    const upload = controlUpload()
    renderApp('/documents')
    await screen.findByText(/No documents yet/)

    await chooseFiles(pdf('a.pdf'), pdf('b.pdf'))

    expect(uploadDocument).toHaveBeenCalledTimes(1) // b waits for a
    expect(within(uploads()).getByRole('listitem', { name: 'b.pdf' })).toHaveTextContent('Waiting')
    upload.finish(doc('d1', 'a.pdf'))
    await vi.waitFor(() => expect(uploadDocument).toHaveBeenCalledTimes(2))
  })

  it('a file added while another is uploading waits its turn', async () => {
    documentsBackend([])
    const upload = controlUpload()
    renderApp('/documents')
    await screen.findByText(/No documents yet/)

    await chooseFiles(pdf('a.pdf'))
    await chooseFiles(pdf('b.pdf')) // a.pdf is still uploading

    expect(uploadDocument).toHaveBeenCalledTimes(1)
    upload.finish(doc('d1', 'a.pdf'))
    await vi.waitFor(() => expect(uploadDocument).toHaveBeenCalledTimes(2))
    expect(vi.mocked(uploadDocument).mock.calls[1][0].name).toBe('b.pdf')
  })

  it('accepts files dropped on the drop zone', async () => {
    documentsBackend([])
    controlUpload()
    renderApp('/documents')
    await screen.findByText(/No documents yet/)

    fireEvent.drop(screen.getByRole('region', { name: 'Upload documents' }), {
      dataTransfer: { files: [pdf('dropped.pdf')] },
    })

    await vi.waitFor(() => expect(uploadDocument).toHaveBeenCalledTimes(1))
    expect(vi.mocked(uploadDocument).mock.calls[0][0].name).toBe('dropped.pdf')
  })

  // --- Checked in the browser before any upload -------------------------------------------

  it('refuses a file over 4 MB without uploading it', async () => {
    documentsBackend([])
    renderApp('/documents')
    await screen.findByText(/No documents yet/)

    await chooseFiles(pdf('big.pdf', 4 * MB + 1))

    expect(within(uploads()).getByRole('listitem', { name: 'big.pdf' })).toHaveTextContent(
      'big.pdf is larger than 4 MB.',
    )
    expect(uploadDocument).not.toHaveBeenCalled()
  })

  it('refuses other file types without uploading them', async () => {
    documentsBackend([])
    renderApp('/documents')
    await screen.findByText(/No documents yet/)

    await chooseFiles(pdf('slides.pptx'))

    expect(uploads()).toHaveTextContent('only PDF, TXT or MD files')
    expect(uploadDocument).not.toHaveBeenCalled()
  })

  it("shows the server's reason when it refuses a file", async () => {
    documentsBackend([])
    const upload = controlUpload()
    renderApp('/documents')
    await screen.findByText(/No documents yet/)

    await chooseFiles(pdf('virus.pdf'))
    upload.fail(new ApiError(415, 'unsupported_media_type', 'virus.pdf is not a real PDF.'))

    expect(await within(uploads()).findByText(/virus\.pdf is not a real PDF/)).toBeInTheDocument()
  })

  // --- Retry and delete ---------------------------------------------------------------------

  it('retries a document whose embedding failed', async () => {
    const { fetch } = documentsBackend([
      doc('d2', 'DBMS.pdf', { status: 'failed', can_retry: true, error: 'The service is busy.' }),
      doc('d3', 'Scan.pdf', { status: 'failed', can_retry: false, error: 'No text found.' }),
    ])
    renderApp('/documents')
    await screen.findByRole('row', { name: /DBMS\.pdf/ })

    expect(within(row('Scan.pdf')).queryByRole('button', { name: /Retry/ })).toBeNull()
    await userEvent.click(within(row('DBMS.pdf')).getByRole('button', { name: 'Retry DBMS.pdf' }))

    await vi.waitFor(() => expect(row('DBMS.pdf')).toHaveTextContent('Ready'))
    expect(fetch).toHaveBeenCalledWith('/api/documents/d2/retry', expect.anything())
  })

  it('deletes a document after confirming', async () => {
    documentsBackend([doc('d1', 'Physics.pdf')])
    renderApp('/documents')
    await screen.findByRole('row', { name: /Physics\.pdf/ })

    await userEvent.click(screen.getByRole('button', { name: 'Delete Physics.pdf' }))
    await userEvent.click(screen.getByRole('button', { name: 'Yes, delete Physics.pdf' }))

    expect(await screen.findByText(/No documents yet/)).toBeInTheDocument()
  })
})
