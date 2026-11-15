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
