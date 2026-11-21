// Reading Server-Sent Events (SMA-62), test-first.
import { describe, expect, it } from 'vitest'

import { SseSplitter } from '@/lib/sse'

describe('SseSplitter', () => {
  it('turns complete events into objects', () => {
    const events = new SseSplitter().push(
      'event: token\ndata: {"text":"Hi "}\n\nevent: done\ndata: {"reply":"Hi"}\n\n',
    )

    expect(events).toEqual([
      { event: 'token', data: '{"text":"Hi "}' },
      { event: 'done', data: '{"reply":"Hi"}' },
    ])
  })

  it('waits for the rest of an event cut in half by the network', () => {
    const splitter = new SseSplitter()

    expect(splitter.push('event: token\ndata: {"te')).toEqual([])
    expect(splitter.push('xt":"Hi"}\n\n')).toEqual([{ event: 'token', data: '{"text":"Hi"}' }])
  })

  it('accepts Windows line endings', () => {
    expect(new SseSplitter().push('event: token\r\ndata: {}\r\n\r\n')).toEqual([
      { event: 'token', data: '{}' },
    ])
  })
})
