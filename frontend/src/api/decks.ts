// Flashcard decks (backend: app/api/decks.py). SMA-64.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiDelete, apiGet, apiPost } from '@/api/client'

export type Card = {
  front: string
  back: string
  page: number | null
  last: 'knew' | 'didnt' | null // my latest mark for this card
}

export type DeckSummary = {
  id: string
  title: string
  source_type: 'document' | 'answer'
  source_name: string // the document's file name, or the chat's title
  created_at: string
  card_count: number
  reviewed: number
  known: number // cards whose latest mark is "knew it"
}

export type Deck = DeckSummary & { cards: Card[] }

const DECKS_KEY = ['decks'] as const

export function useDecks() {
  return useQuery({ queryKey: DECKS_KEY, queryFn: () => apiGet<DeckSummary[]>('/api/decks') })
}

export function useDeck(id: string) {
  return useQuery({ queryKey: [...DECKS_KEY, id], queryFn: () => apiGet<Deck>(`/api/decks/${id}`) })
}

/** From a document ({document_id}) or from one AI answer ({message_id}). */
export function useCreateDeck() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (source: { document_id: string } | { message_id: string }) =>
      apiPost<Deck>('/api/decks', source),
    onSuccess: (deck) => {
      queryClient.setQueryData([...DECKS_KEY, deck.id], deck) // opens at once
      return queryClient.invalidateQueries({ queryKey: DECKS_KEY, exact: true })
    },
  })
}

export function useReviewCard(deckId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (review: { card: number; knew: boolean }) =>
      apiPost(`/api/decks/${deckId}/reviews`, review),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: DECKS_KEY, exact: true }),
  })
}

export function useDeleteDeck() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/api/decks/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: DECKS_KEY, exact: true }),
  })
}
