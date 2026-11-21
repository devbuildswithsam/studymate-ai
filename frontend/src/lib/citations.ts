// How a citation is named everywhere (chips and the Sources panel). SMA-49.
import type { Citation } from '@/api/chat'

/**
 * Where in a document: "p. 12" in a PDF, "section 2" in a DOCX (SMA-66: Word has no fixed
 * pages, so a DOCX is cut at its headings), nothing for TXT / MD. The name can be trusted:
 * the backend checked that a .docx really is a DOCX.
 */
export function location(filename: string, page: number | null): string {
  if (page === null) return ''
  return filename.toLowerCase().endsWith('.docx') ? `section ${page}` : `p. ${page}`
}

/** "[1] Physics.pdf p. 12", "[2] Lecture.docx section 2", "[3] notes.md". */
export function citationLabel(citation: Citation): string {
  const where = location(citation.filename, citation.page)
  return `[${citation.n}] ${citation.filename}${where ? ` ${where}` : ''}`
}
