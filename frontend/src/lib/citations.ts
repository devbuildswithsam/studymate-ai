// How a citation is named everywhere (chips and the Sources panel). SMA-49.
import type { Citation } from '@/api/chat'

/** "[1] Physics.pdf p.12" (no page for TXT / MD files). */
export function citationLabel(citation: Citation): string {
  const page = citation.page === null ? '' : ` p.${citation.page}`
  return `[${citation.n}] ${citation.filename}${page}`
}
