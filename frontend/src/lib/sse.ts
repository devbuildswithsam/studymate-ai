// Reading Server-Sent Events from a fetch response (SMA-62).
// The server sends blocks like
//   event: token
//   data: {"text": "Entropy "}
// each ended by a blank line. The network may cut a block anywhere, so an unfinished
// block waits for the rest (like LineSplitter in upload.ts).
// Why not the browser's EventSource? It can only make GET requests, without our headers
// (CSRF token) or a JSON body; fetch can do POST and read the stream as it arrives.

export type SseEvent = { event: string; data: string }

export class SseSplitter {
  private rest = ''

  push(text: string): SseEvent[] {
    const blocks = (this.rest + text.replaceAll('\r\n', '\n')).split('\n\n')
    this.rest = blocks.pop() ?? '' // the last piece has no blank line yet
    return blocks.flatMap((block) => {
      let event = 'message'
      const data: string[] = []
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
      }
      return data.length ? [{ event, data: data.join('\n') }] : []
    })
  }
}
