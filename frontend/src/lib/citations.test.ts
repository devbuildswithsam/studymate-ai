// Where a cited piece of text is: a page in a PDF, a section in a DOCX (SMA-66).
import { describe, expect, it } from 'vitest'

import { citationLabel, location } from '@/lib/citations'

const citation = (filename: string, page: number | null) => ({
  n: 1,
  chunk_id: 'c1',
  document_id: 'd1',
  filename,
  page,
  text: 'Entropy rises.',
})

describe('location', () => {
  it('is a page in a PDF and a section in a DOCX', () => {
    expect(location('Physics.pdf', 12)).toBe('p. 12')
    expect(location('Lecture.docx', 2)).toBe('section 2')
    expect(location('LECTURE.DOCX', 3)).toBe('section 3')
  })

  it('is empty when there is no number (TXT, MD, a DOCX without headings)', () => {
    expect(location('notes.md', null)).toBe('')
    expect(location('Lecture.docx', null)).toBe('')
  })
})

describe('citationLabel', () => {
  it('names the file and where in it', () => {
    expect(citationLabel(citation('Physics.pdf', 12))).toBe('[1] Physics.pdf p. 12')
    expect(citationLabel(citation('Lecture.docx', 2))).toBe('[1] Lecture.docx section 2')
    expect(citationLabel(citation('notes.md', null))).toBe('[1] notes.md')
  })
})
