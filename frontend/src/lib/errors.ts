// Turn any error into a sentence a student understands. SMA-25.
import { ApiError } from '@/api/client'

const UNREACHABLE = "Can't reach the server. Is the backend running?"

export function friendlyError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 502 || error.status === 504) {
      // The dev proxy answers 502/504 (empty body) when FastAPI isn't running.
      return UNREACHABLE
    }
    if (error.status === 503 || error.status === 429) {
      // Backend: every model is rate-limited or down (AllModelsFailedError -> 503).
      return 'The AI is busy right now (free-tier limits). Please try again in a minute.'
    }
    return error.message // our backend's own message, e.g. a 422 validation error
  }
  // fetch itself failed: no answer at all (network down, server gone).
  return UNREACHABLE
}
