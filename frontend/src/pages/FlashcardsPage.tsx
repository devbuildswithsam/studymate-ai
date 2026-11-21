// Flashcards: make a deck from a document, and the list of mine (SMA-64).
// Decks can also be made from any AI answer ("Make flashcards" under it in Chat or Study).
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'

import { useCreateDeck, useDecks, useDeleteDeck } from '@/api/decks'
import { useDocuments } from '@/api/documents'
import { Button } from '@/components/ui/button'
import { friendlyError, generationError } from '@/lib/errors'

export function FlashcardsPage() {
  return (
    <section className="max-w-3xl">
      <h1 className="text-2xl font-semibold">Flashcards</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Cards written by the AI from one of your documents, or from any answer in a chat
        (&ldquo;Make flashcards&rdquo; under it). Flip each card and say whether you knew it.
      </p>
      <NewDeck />
      <DeckList />
    </section>
  )
}

function NewDeck() {
  const navigate = useNavigate()
  const documents = useDocuments()
  const create = useCreateDeck()
  const ready = (documents.data ?? []).filter((d) => d.status === 'ready')
  const [picked, setPicked] = useState<string>()
  const documentId = picked ?? ready[0]?.id

  function submit(event: FormEvent) {
    event.preventDefault()
    if (!documentId) return
    create.mutate(
      { document_id: documentId },
      { onSuccess: (deck) => navigate(`/flashcards/${deck.id}`) },
    )
  }

  if (documents.isSuccess && ready.length === 0) return null // chat answers still work
  return (
    <form onSubmit={submit} className="mt-6 flex flex-wrap items-end gap-3">
      <label className="flex flex-col gap-1 text-sm">
        Document
        <select
          value={documentId ?? ''}
          onChange={(event) => setPicked(event.target.value)}
          className="rounded-md border bg-background px-3 py-2"
        >
          {ready.map((d) => (
            <option key={d.id} value={d.id}>
              {d.filename}
            </option>
          ))}
        </select>
      </label>
      <Button type="submit" disabled={!documentId || create.isPending}>
        {create.isPending ? 'Writing your cards…' : 'Make flashcards'}
      </Button>
      {create.isError && (
        <p role="alert" className="w-full text-sm text-red-600">
          {generationError(create.error)}
        </p>
      )}
    </form>
  )
}

function DeckList() {
  const decks = useDecks()
  const remove = useDeleteDeck()

  if (decks.error) return <p className="mt-6 text-sm text-red-600">{friendlyError(decks.error)}</p>
  if (!decks.data) return null
  if (decks.data.length === 0) {
    return <p className="mt-6 text-sm text-muted-foreground">No decks yet.</p>
  }
  return (
    <ul className="mt-6 flex flex-col divide-y rounded-md border">
      {decks.data.map((deck) => (
        <li key={deck.id} aria-label={deck.title} className="flex items-center gap-3 p-3">
          <div className="min-w-0 flex-1">
            <Link to={`/flashcards/${deck.id}`} className="font-medium hover:underline">
              {deck.title}
            </Link>
            <p className="text-xs text-muted-foreground">
              {deck.source_type === 'answer' ? 'From a chat: ' : ''}
              {deck.source_name} · {deck.card_count} cards ·{' '}
              {deck.reviewed === 0 ? 'not reviewed yet' : `known ${deck.known}/${deck.card_count}`}
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            disabled={remove.isPending}
            onClick={() => remove.mutate(deck.id)}
          >
            Delete
          </Button>
        </li>
      ))}
    </ul>
  )
}
