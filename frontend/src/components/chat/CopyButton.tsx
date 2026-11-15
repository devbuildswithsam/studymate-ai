// Copies an answer's original Markdown (better for pasting into notes than rendered HTML).
import { CheckIcon, CopyIcon } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'

export function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000) // back to "Copy" after 2 s
  }

  return (
    <Button
      variant="ghost"
      size="icon-sm"
      onClick={copy}
      aria-label={copied ? 'Copied' : 'Copy answer'}
    >
      {copied ? <CheckIcon /> : <CopyIcon />}
    </Button>
  )
}
