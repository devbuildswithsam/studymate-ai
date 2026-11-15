// friendlyError: every failure becomes a sentence a student understands. SMA-25 (test-first).
import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api/client'
import { friendlyError } from '@/lib/errors'

const UNREACHABLE = "Can't reach the server. Is the backend running?"
const BUSY = 'The AI is busy right now (free-tier limits). Please try again in a minute.'

describe('friendlyError', () => {
  it.each([503, 429])('HTTP %i (every model busy or rate-limited) -> busy', (status) => {
    expect(friendlyError(new ApiError(status, 'x', 'technical detail'))).toBe(BUSY)
  })

  it.each([502, 504])(
    'HTTP %i from the dev proxy (backend not running) -> unreachable',
    (status) => {
      expect(friendlyError(new ApiError(status, 'error', `Request failed (HTTP ${status})`))).toBe(
        UNREACHABLE,
      )
    },
  )

  it('fetch itself failing (no answer at all) -> unreachable', () => {
    expect(friendlyError(new TypeError('Failed to fetch'))).toBe(UNREACHABLE)
  })

  it("other API errors -> the backend's own message", () => {
    expect(friendlyError(new ApiError(422, 'validation_error', 'body.message: too long'))).toBe(
      'body.message: too long',
    )
  })
})
