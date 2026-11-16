// Notes (backend: app/api/notes.py). SMA-32.
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError, apiDelete, apiGet, apiPatch, apiPost } from '@/api/client'

/** Same fields as the backend's NoteOut. */
export type Note = {
  id: string
  title: string
  content: string
  tags: string[]
  source: NoteSource | null // set when the note was saved from a chat answer
  created_at: string
  updated_at: string
}

export type NoteSource = {
  message_id: string
  conversation_id: string
  conversation_title: string | null
}

/** What you send to create a note. */
export type NewNote = {
  title: string
  content: string
  tags: string[]
  source_message_id?: string
}

export type NoteChanges = Partial<Pick<Note, 'title' | 'content' | 'tags'>>

// Every list and search lives under ['notes', ...]: one invalidation refreshes them all.
const NOTES_KEY = ['notes'] as const
const noteKey = (id: string) => ['note', id] as const

/** All my notes, or only those matching `search` (empty search = all). */
export function useNotes(search: string) {
  const q = search.trim()
  return useQuery({
    queryKey: [...NOTES_KEY, q],
    queryFn: () =>
      apiGet<Note[]>(q ? `/api/notes/search?q=${encodeURIComponent(q)}` : '/api/notes'),
    // A new search is a new query with no data yet: keep showing the previous list until
    // the results arrive, instead of flashing an empty list.
    placeholderData: keepPreviousData,
  })
}

export function useNote(id: string | undefined) {
  return useQuery({
    queryKey: noteKey(id ?? ''),
    queryFn: () => apiGet<Note>(`/api/notes/${id}`),
    enabled: id !== undefined,
    retry: (failures, error) =>
      !(error instanceof ApiError && error.status === 404) && failures < 3,
  })
}

export function useCreateNote() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (note: NewNote) => apiPost<Note>('/api/notes', note),
    onSuccess: (created) => {
      queryClient.setQueryData(noteKey(created.id), created)
      return queryClient.invalidateQueries({ queryKey: NOTES_KEY })
    },
  })
}

export function useUpdateNote(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (changes: NoteChanges) => apiPatch<Note>(`/api/notes/${id}`, changes),
    onSuccess: (updated) => {
      queryClient.setQueryData(noteKey(id), updated)
      return queryClient.invalidateQueries({ queryKey: NOTES_KEY })
    },
  })
}

export function useDeleteNote(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => apiDelete(`/api/notes/${id}`),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: noteKey(id) })
      return queryClient.invalidateQueries({ queryKey: NOTES_KEY })
    },
  })
}
