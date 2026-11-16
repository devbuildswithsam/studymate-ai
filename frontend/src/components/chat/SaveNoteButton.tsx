// "Save as note" under an AI answer (wireframe 6.1). SMA-32.
// The page does the saving (onSave); this button only shows idle → saving → saved.
import { BookmarkCheckIcon, BookmarkPlusIcon } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'

type Props = {
  onSave: () => Promise<unknown> // rejects if saving failed: the button lets you try again
}

export function SaveNoteButton({ onSave }: Props) {
  const [state, setState] = useState<'idle' | 'saving' | 'saved'>('idle')

  async function save() {
    setState('saving')
    try {
      await onSave()
      setState('saved')
    } catch {
      setState('idle') // the page already showed why (toast)
    }
  }

  const saved = state === 'saved'
  return (
    <Button
      variant="ghost"
      size="icon-sm"
      onClick={save}
      disabled={state !== 'idle'}
      aria-label={saved ? 'Saved to notes' : 'Save as note'}
      title={saved ? 'Saved to notes' : 'Save as note'}
    >
      {saved ? <BookmarkCheckIcon /> : <BookmarkPlusIcon />}
    </Button>
  )
}
