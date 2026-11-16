// Notes (wireframe 6.7): search + list on the left, the open note on the right. SMA-32.
// /notes = nothing open, /notes/new = a new note, /notes/:id = that note.
import { PlusIcon } from 'lucide-react'
import { useState } from 'react'
import { Link, NavLink, useParams } from 'react-router'

import { ApiError } from '@/api/client'
import { useNote, useNotes } from '@/api/notes'
import { NoteEditor } from '@/components/notes/NoteEditor'
import { Button } from '@/components/ui/button'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { friendlyError } from '@/lib/errors'
import { cn } from '@/lib/utils'

const SEARCH_DELAY_MS = 300

export function NotesPage() {
  const { noteId } = useParams()
  const [search, setSearch] = useState('')
  const searchText = useDebouncedValue(search, SEARCH_DELAY_MS).trim()
  const notes = useNotes(searchText)

  return (
    <div className="flex h-full gap-6">
      <section className="flex w-72 shrink-0 flex-col gap-3">
        <h1 className="text-2xl font-semibold">Notes</h1>
        <input
          type="search"
          aria-label="Search notes"
          placeholder="Search notes…"
          value={search}
          maxLength={200}
          onChange={(event) => setSearch(event.target.value)}
          className="rounded-md border bg-background px-3 py-1.5 text-sm"
        />
        <Button asChild variant="outline" size="sm" className="justify-start">
          <Link to="/notes/new">
            <PlusIcon aria-hidden />
            New note
          </Link>
        </Button>
        <nav aria-label="Notes list" className="flex flex-col gap-0.5 overflow-y-auto">
          {notes.data?.map((note) => (
            <NavLink
              key={note.id}
              to={`/notes/${note.id}`}
              className={({ isActive }) =>
                cn(
                  'truncate rounded-md px-2 py-1.5 text-sm hover:bg-muted',
                  isActive && 'bg-muted font-medium',
                )
              }
            >
              {note.title}
            </NavLink>
          ))}
        </nav>
        {notes.isError && (
          <p className="text-sm text-muted-foreground">Couldn&apos;t load your notes</p>
        )}
        {notes.data?.length === 0 && (
          <p className="text-sm text-muted-foreground">
            {searchText ? `No notes match “${searchText}”` : 'No notes yet'}
          </p>
        )}
      </section>
      <section className="min-w-0 flex-1">
        {noteId === 'new' && <NoteEditor key="new" />}
        {noteId && noteId !== 'new' && <OpenNote id={noteId} />}
        {!noteId && <p className="text-muted-foreground">Select a note, or create a new one.</p>}
      </section>
    </div>
  )
}

function OpenNote({ id }: { id: string }) {
  const note = useNote(id)

  if (note.isPending) return <p className="text-muted-foreground">Loading note…</p>
  if (note.isError) {
    const gone = note.error instanceof ApiError && note.error.status === 404
    return (
      <p className="text-muted-foreground">
        {gone ? "This note doesn't exist (maybe it was deleted)." : friendlyError(note.error)}
      </p>
    )
  }
  // key: opening another note starts the editor afresh with that note's values.
  return <NoteEditor key={note.data.id} note={note.data} />
}
