// Reviewing one deck: one card at a time, flip it, say whether you knew it (SMA-64).
// Each mark is saved (for Progress); the end shows how many you knew this round.
import { useState } from 'react'
import { Link, useParams } from 'react-router'

import { useDeck, useReviewCard } from '@/api/decks'
import { Button } from '@/components/ui/button'
import { location } from '@/lib/citations'
import { friendlyError } from '@/lib/errors'

export function DeckPage() {
  const { deckId = '' } = useParams()
  const deck = useDeck(deckId)
  const review = useReviewCard(deckId)
  const [current, setCurrent] = useState(0) // the card on screen
  const [flipped, setFlipped] = useState(false) // its back is showing
  const [knewCount, setKnewCount] = useState(0) // this round

  if (deck.isLoading) return <p className="text-muted-foreground">Loading flashcards…</p>
  if (deck.error || !deck.data) {
    return (
      <section className="space-y-3">
        <h1 className="text-2xl font-semibold">Flashcards</h1>
        <p className="text-muted-foreground">{friendlyError(deck.error)}</p>
        <Link to="/flashcards" className="text-sm underline">
          Back to flashcards
        </Link>
      </section>
    )
  }

  const { cards } = deck.data
  const finished = current >= cards.length
  const card = cards[current]

  function mark(knew: boolean) {
    review.mutate({ card: current, knew }) // saved in the background, for Progress
    if (knew) setKnewCount((n) => n + 1)
    setCurrent((n) => n + 1)
    setFlipped(false)
  }

  function again() {
    setCurrent(0)
    setFlipped(false)
    setKnewCount(0)
  }

  return (
    <section className="max-w-2xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">{deck.data.title}</h1>
        <p className="text-sm text-muted-foreground">
          {deck.data.source_type === 'answer' ? 'From a chat: ' : 'From '}
          {deck.data.source_name} ·{' '}
          <Link to="/flashcards" className="underline">
            all decks
          </Link>
        </p>
      </header>

      {finished ? (
        <div role="status" className="space-y-4 rounded-xl border p-6 text-center">
          <p className="text-lg font-semibold">
            You knew {knewCount} of {cards.length}
          </p>
          <Button onClick={again}>Review again</Button>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Card {current + 1} of {cards.length}
          </p>
          <div className="min-h-40 rounded-xl border p-6">
            <p className="text-lg font-medium">{card.front}</p>
            {flipped && (
              <div className="mt-4 border-t pt-4">
                <p>{card.back}</p>
                {card.page !== null && (
                  <p className="mt-2 text-xs text-muted-foreground">
                    ({location(deck.data.source_name, card.page)})
                  </p>
                )}
              </div>
            )}
          </div>
          {flipped ? (
            <div className="flex gap-2">
              <Button onClick={() => mark(true)}>Knew it</Button>
              <Button variant="outline" onClick={() => mark(false)}>
                Didn&apos;t know
              </Button>
            </div>
          ) : (
            <Button onClick={() => setFlipped(true)}>Show answer</Button>
          )}
        </div>
      )}
    </section>
  )
}
