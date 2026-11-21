// friendlyError: every failure becomes a sentence a student understands. SMA-25 (test-first).
import { describe, expect, it } from 'vitest'

import { StreamError } from '@/api/chat'
import { ApiError } from '@/api/client'
import { friendlyError } from '@/lib/errors'

const UNREACHABLE = "Can't reach the server. Is the backend running?"
const BUSY = 'The AI is busy right now (free-tier limits). Please try again in a minute.'

describe('friendlyError', () => {
  it('HTTP 503 (every model busy or rate-limited) -> busy', () => {
    expect(friendlyError(new ApiError(503, 'x', 'technical detail'))).toBe(BUSY)
  })

  it('HTTP 429 (SMA-67: my own rate limit) -> the message, which says when to retry', () => {
    const limited = 'Too many messages in a short time. Please try again in 23 seconds.'
    expect(friendlyError(new ApiError(429, 'rate_limited', limited))).toBe(limited)
  })

  it.each([502, 504])(
    'HTTP %i from the dev proxy (backend not running) -> unreachable',
    (status) => {
      expect(friendlyError(new ApiError(status, 'error', `Request failed (HTTP ${status})`))).toBe(
        UNREACHABLE,
      )
    },
  )

  it('an answer cut off halfway (SMA-62) -> its own message, not "busy"', () => {
    const cutOff = new StreamError('service_unavailable', 'The answer was cut off.', 'm1', 'c1')
    expect(friendlyError(cutOff)).toBe('The answer was cut off.')
    // Nothing saved (every model failed before a word): still the usual "busy".
    const failed = new StreamError('service_unavailable', 'technical', null, 'c1')
    expect(friendlyError(failed)).toBe(BUSY)
  })

  it('fetch itself failing (no answer at all) -> unreachable', () => {
    expect(friendlyError(new TypeError('Failed to fetch'))).toBe(UNREACHABLE)
  })

  it("other API errors -> the backend's own message", () => {
    expect(friendlyError(new ApiError(422, 'validation_error', 'body.message: too long'))).toBe(
      'body.message: too long',
    )
  })
})
