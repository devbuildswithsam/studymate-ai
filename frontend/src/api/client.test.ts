// The API client sends the CSRF token on every write (SMA-58, test-first).
// Double-submit: the backend sets a `studymate_csrf` cookie that JavaScript can read; we
// copy it into the X-CSRF-Token header. Another website can't read our cookies, so it
// can't send a matching header.
import { afterEach, describe, expect, it } from 'vitest'

import { apiDelete, apiGet, apiPatch, apiPost, apiPut, csrfToken, toApiError } from '@/api/client'
import { mockFetch } from '@/test/render'

function setCookie(value: string) {
  document.cookie = value
}

afterEach(() => {
  // Expire the cookie again so tests don't leak into each other.
  document.cookie = 'studymate_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/'
})

function headersOf(fake: ReturnType<typeof mockFetch>): Record<string, string> {
  // mockFetch's fake is typed without arguments, but fetch is called with (path, init).
  const [, init] = fake.mock.calls[0] as unknown as [string, RequestInit]
  return (init.headers ?? {}) as Record<string, string>
}

describe('an empty answer', () => {
  it('204 No Content resolves without reading a body (e.g. logout, SMA-59)', async () => {
    const fake = mockFetch({})
    fake.mockImplementation(async () => new Response(null, { status: 204 }))

    await expect(apiPost('/api/auth/logout', {})).resolves.toBeUndefined()
  })
})

describe('csrfToken', () => {
  it('finds our cookie among others', () => {
    setCookie('theme=dark; path=/')
    setCookie('studymate_csrf=abc_DEF-123; path=/')

    expect(csrfToken()).toBe('abc_DEF-123')
  })

  it('is undefined without the cookie (local mode has no login)', () => {
    expect(csrfToken()).toBeUndefined()
  })
})

describe('the CSRF header', () => {
  it.each([
    ['POST', () => apiPost('/api/notes', { title: 'x' })],
    ['PATCH', () => apiPatch('/api/notes/n1', { title: 'x' })],
    ['PUT', () => apiPut('/api/conversations/c1/documents', { document_ids: [] })],
    ['DELETE', () => apiDelete('/api/notes/n1')],
  ])('is sent with %s', async (_method, call) => {
    setCookie('studymate_csrf=token-123; path=/')
    const fake = mockFetch({})

    await call()

    expect(headersOf(fake)['X-CSRF-Token']).toBe('token-123')
  })

  it('is not sent with GET (reading changes nothing)', async () => {
    setCookie('studymate_csrf=token-123; path=/')
    const fake = mockFetch({})

    await apiGet('/api/notes')

    expect(headersOf(fake)['X-CSRF-Token']).toBeUndefined()
  })

  it('is left out when there is no cookie', async () => {
    const fake = mockFetch({})

    await apiPost('/api/notes', { title: 'x' })

    expect('X-CSRF-Token' in headersOf(fake)).toBe(false)
  })
})

describe('toApiError (SMA-68)', () => {
  it('keeps the request id from the error body', async () => {
    const response = Response.json(
      { error: { code: 'internal_error', message: 'Oops', request_id: 'abc123def456' } },
      { status: 500 },
    )

    const error = await toApiError(response)

    expect([error.status, error.message, error.requestId]).toEqual([500, 'Oops', 'abc123def456'])
  })
})
