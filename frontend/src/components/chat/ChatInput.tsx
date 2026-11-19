// The message box: Enter sends, Shift+Enter adds a new line. SMA-25.
import { SendIcon } from 'lucide-react'
import type { FormEvent, KeyboardEvent } from 'react'

import { Button } from '@/components/ui/button'

export const MAX_MESSAGE_CHARS = 4000 // same limit as the backend (app/api/chat.py)

type Props = {
  value: string
  onChange: (value: string) => void
  onSend: () => void
  disabled?: boolean // e.g. while waiting for an answer
  placeholder?: string // SMA-49: the study chat asks about its documents
}

export function ChatInput({
  value,
  onChange,
  onSend,
  disabled = false,
  placeholder = 'Ask StudyMate anything… (Enter to send, Shift+Enter for a new line)',
}: Props) {
  const canSend = !disabled && value.trim().length > 0

  function submit(event?: FormEvent) {
    event?.preventDefault()
    if (canSend) onSend()
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // isComposing: don't send while typing with an input method (e.g. Hindi, Japanese).
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <form onSubmit={submit} className="flex items-end gap-2">
      <textarea
        aria-label="Message"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={onKeyDown}
        maxLength={MAX_MESSAGE_CHARS}
        rows={2}
        placeholder={placeholder}
        className="min-h-12 flex-1 resize-none rounded-md border bg-background px-3 py-2 text-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      />
      <Button type="submit" disabled={!canSend} aria-label="Send">
        <SendIcon />
      </Button>
    </form>
  )
}
