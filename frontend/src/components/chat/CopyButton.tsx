// Copies an answer's original Markdown (better for pasting into notes than rendered HTML).
import { CheckIcon, CopyIcon } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'

// `label`: what screen readers hear (SMA-61 reuses it for tokens: "Copy token").
export function CopyButton({ text, label = 'Copy answer' }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000) // back to "Copy" after 2 s
  }

  return (
    <Button variant="ghost" size="icon-sm" onClick={copy} aria-label={copied ? 'Copied' : label}>
      {copied ? <CheckIcon /> : <CopyIcon />}
    </Button>
  )
}
