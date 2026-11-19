// Under a study answer (SMA-49, guide 7.5): citation chips, or the not-found button.
import type { Citation } from '@/api/chat'
import { Button } from '@/components/ui/button'
import { citationLabel } from '@/lib/citations'

type Props = {
  messageId: string
  citations: Citation[]
  question: string | undefined // the student's question this answers
  onCitation?: (messageId: string, n: number) => void
  onAnswerGenerally?: (question: string) => void
}

export function GroundedExtras({
  messageId,
  citations,
  question,
  onCitation,
  onAnswerGenerally,
}: Props) {
  if (citations.length === 0) {
    // Not found: the model never mixes in general knowledge silently, the student chooses.
    return question && onAnswerGenerally ? (
      <Button
        size="sm"
        variant="outline"
        className="mt-2"
        onClick={() => onAnswerGenerally(question)}
      >
        Answer from general knowledge
      </Button>
    ) : null
  }
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {citations.map((citation) => (
        <Button
          key={citation.n}
          size="xs"
          variant="outline"
          onClick={() => onCitation?.(messageId, citation.n)}
        >
          {citationLabel(citation)}
        </Button>
      ))}
    </div>
  )
}
