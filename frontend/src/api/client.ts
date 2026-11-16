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
  const response = await fetch(path, { method: 'DELETE', headers: { Accept: 'application/json' } })
  if (!response.ok) {
    throw await toApiError(response)
  }
}

async function sendJson<T>(method: 'POST' | 'PATCH', path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    throw await toApiError(response)
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
