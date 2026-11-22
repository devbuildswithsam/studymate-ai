// Turn any error into a sentence a student understands. SMA-25.
import { StreamError } from '@/api/chat'
import { ApiError } from '@/api/client'

const UNREACHABLE = "Can't reach the server. Is the backend running?"

export function friendlyError(error: unknown): string {
  const message = sentence(error)
  // SMA-68: a server failure names its request, so it can be found in the logs. Our own
  // mistakes (4xx: a wrong field, a missing page) don't need one.
  if (error instanceof ApiError && error.status >= 500 && error.requestId) {
    return `${message} (Reference: ${error.requestId.slice(0, 8)})`
  }
  return message
}

function sentence(error: unknown): string {
  if (error instanceof StreamError && error.messageId) {
    // SMA-62: an answer cut off halfway was saved; its own message says what happened.
    return error.message
  }
  if (error instanceof ApiError) {
    if (error.status === 502 || error.status === 504) {
      // The dev proxy answers 502/504 (empty body) when FastAPI isn't running.
      return UNREACHABLE
    }
    if (error.status === 503) {
      // Backend: every model is rate-limited or down (AllModelsFailedError -> 503).
      return 'The AI is busy right now (free-tier limits). Please try again in a minute.'
    }
    // Our backend's own message, e.g. a 422 validation error, or a 429 from our own rate
    // limits (SMA-67), which says how many seconds to wait.
    return error.message
  }
  // fetch itself failed: no answer at all (network down, server gone).
  return UNREACHABLE
}

/**
 * For things the AI writes (quizzes, flashcards: SMA-63, SMA-64). Their 503 messages are
 * written for students ("broke the rules twice... try another document") and say more
 * than the general "AI is busy", so they are shown as they are.
 */
export function generationError(error: unknown): string {
  return error instanceof ApiError && error.status === 503 ? error.message : friendlyError(error)
}
