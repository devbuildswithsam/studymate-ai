// The one place the app calls fetch. SMA-24.
// Paths are always relative ("/api/..."): in development Vite's proxy forwards them to FastAPI.

/** An error from our API, in the backend's format: {"error": {"code", "message"}}. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

/**
 * The CSRF token (SMA-58): the backend puts it in a cookie JavaScript may read, and every
 * write sends it back in the X-CSRF-Token header. Other websites can't read our cookies,
 * so they can't send a matching header. Undefined in local mode (no login, no cookie).
 */
export function csrfToken(): string | undefined {
  const prefix = 'studymate_csrf='
  const cookie = document.cookie.split('; ').find((c) => c.startsWith(prefix))
  return cookie ? decodeURIComponent(cookie.slice(prefix.length)) : undefined
}

/** The header to add to a write, or nothing. Exported for the XHR upload too. */
export function csrfHeader(): Record<string, string> {
  const token = csrfToken()
  return token ? { 'X-CSRF-Token': token } : {}
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { Accept: 'application/json' } })
  if (!response.ok) {
    throw await toApiError(response)
  }
  return (await response.json()) as T
}

export function apiPost<T>(path: string, body: unknown): Promise<T> {
  return sendJson<T>('POST', path, body)
}

export function apiPatch<T>(path: string, body: unknown): Promise<T> {
  return sendJson<T>('PATCH', path, body)
}

/** DELETE: the backend answers 204 No Content, so there is no body to read. SMA-31. */
export async function apiDelete(path: string): Promise<void> {
  const response = await fetch(path, {
    method: 'DELETE',
    headers: { Accept: 'application/json', ...csrfHeader() },
  })
  if (!response.ok) {
    throw await toApiError(response)
  }
}

/** PUT: replace something as a whole, e.g. a study chat's documents. SMA-49. */
export function apiPut<T>(path: string, body: unknown): Promise<T> {
  return sendJson<T>('PUT', path, body)
}

async function sendJson<T>(
  method: 'POST' | 'PATCH' | 'PUT',
  path: string,
  body: unknown,
): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...csrfHeader() },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    throw await toApiError(response)
  }
  if (response.status === 204) {
    return undefined as T // "No Content": e.g. logout (SMA-59) has nothing to send back
  }
  return (await response.json()) as T
}

async function toApiError(response: Response): Promise<ApiError> {
  try {
    const body = await response.json()
    if (body?.error?.message) {
      return new ApiError(response.status, body.error.code ?? 'error', body.error.message)
    }
  } catch {
    // Not JSON (e.g. a proxy error page): fall through to a generic message.
  }
  return new ApiError(response.status, 'error', `Request failed (HTTP ${response.status})`)
}
