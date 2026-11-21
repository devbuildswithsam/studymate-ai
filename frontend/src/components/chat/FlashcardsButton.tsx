// "Make flashcards" under an AI answer (SMA-64). The page does the work (onMake); this
// button only shows idle → making → made, like SaveNoteButton.
import { CheckIcon, LayersIcon } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'

type Props = {
  onMake: () => Promise<unknown> // rejects if it failed: the button lets you try again
}

export function FlashcardsButton({ onMake }: Props) {
  const [state, setState] = useState<'idle' | 'making' | 'made'>('idle')

  async function make() {
    setState('making')
    try {
      await onMake()
      setState('made')
    } catch {
      setState('idle') // the page already showed why (toast)
    }
  }

  const label = state === 'made' ? 'Flashcards made' : 'Make flashcards'
  return (
    <Button
      variant="ghost"
      size="icon-sm"
      onClick={make}
      disabled={state !== 'idle'}
      aria-label={label}
      title={state === 'making' ? 'Writing your cards…' : label}
    >
      {state === 'made' ? <CheckIcon /> : <LayersIcon />}
    </Button>
  )
}
