// Shared by the Login and Register pages (SMA-59). Kept out of the component files:
// Vite's fast refresh needs files that export only components.
import { ApiError } from '@/api/client'
import { friendlyError } from '@/lib/errors'

export const INPUT_CLASS = 'rounded-md border bg-background px-3 py-2'

// The same limits as the backend (app/services/auth.py): checked here first, so the user
// gets a clear message instead of a validation error from the server.
export const MIN_PASSWORD = 8
export const MAX_PASSWORD = 128

export function passwordProblem(password: string): string | null {
  if (password.length < MIN_PASSWORD) return `Use at least ${MIN_PASSWORD} characters.`
  if (password.length > MAX_PASSWORD) return `Use at most ${MAX_PASSWORD} characters.`
  return null
}

/**
 * The message for a failed login or register. The backend's own words (wrong password,
 * too many tries, email in use), NOT friendlyError's "the AI is busy" for a 429.
 * Unreachable servers (no answer, 502/504) still get the friendly sentence.
 */
export function authErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status < 500) {
    // 422 = the backend didn't accept the input; passwords are checked here first, so it's
    // almost always the email.
    return error.status === 422 ? 'Please enter a valid email address.' : error.message
  }
  return friendlyError(error)
}
