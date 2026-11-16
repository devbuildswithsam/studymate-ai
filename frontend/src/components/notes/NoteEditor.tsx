// Edit one note: title, tags, content; Save and Delete (wireframe 6.7). SMA-32.
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { toast } from 'sonner'

import { type Note, useCreateNote, useDeleteNote, useUpdateNote } from '@/api/notes'
import { Button } from '@/components/ui/button'
import { friendlyError } from '@/lib/errors'

/** "physics, , exam " -> ["physics", "exam"] */
function parseTags(text: string): string[] {
  return text
    .split(',')
    .map((tag) => tag.trim())
    .filter(Boolean)
}

/** "10 Nov" */
function formatDay(iso: string): string {
  return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short' }).format(new Date(iso))
}

type Props = {
  note?: Note // undefined = a new note, created on Save
}

export function NoteEditor({ note }: Props) {
  const [title, setTitle] = useState(note?.title ?? '')
  const [tagsText, setTagsText] = useState(note?.tags.join(', ') ?? '')
  const [content, setContent] = useState(note?.content ?? '')
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const navigate = useNavigate()
  const create = useCreateNote()
  const update = useUpdateNote(note?.id ?? '')
  const remove = useDeleteNote(note?.id ?? '')

  const tags = parseTags(tagsText)
  const changed =
    !note ||
    title !== note.title ||
    content !== note.content ||
    tags.join('\n') !== note.tags.join('\n')
  const saving = create.isPending || update.isPending
  const canSave = title.trim() !== '' && changed && !saving

  function save() {
    const values = { title: title.trim(), content, tags }
    const onError = (error: unknown) => toast.error(friendlyError(error))
    if (note) {
      update.mutate(values, { onSuccess: () => toast.success('Note saved'), onError })
    } else {
      create.mutate(values, {
        onSuccess: (created) => {
          toast.success('Note saved')
          navigate(`/notes/${created.id}`, { replace: true }) // "new" becomes this note
        },
        onError,
      })
    }
  }

  function deleteNote() {
    remove.mutate(undefined, {
      onSuccess: () => navigate('/notes'),
      onError: (error) => toast.error(friendlyError(error)),
    })
  }

  return (
    <form
      className="flex h-full flex-col gap-3"
      onSubmit={(event) => {
        event.preventDefault() // a form, so Enter in the title also saves
        if (canSave) save()
      }}
    >
      <input
        aria-label="Title"
        placeholder="Title"
        value={title}
        maxLength={200} // same limits as the backend
        onChange={(event) => setTitle(event.target.value)}
        className="rounded-md border bg-background px-3 py-2 text-lg font-semibold"
      />
      <input
        aria-label="Tags"
        placeholder="Tags, separated by commas"
        value={tagsText}
        onChange={(event) => setTagsText(event.target.value)}
        className="rounded-md border bg-background px-3 py-1.5 text-sm"
      />
      {note?.source && (
        <p className="text-sm text-muted-foreground">
          From:{' '}
          <Link to={`/c/${note.source.conversation_id}`} className="underline">
            {note.source.conversation_title ?? 'a chat'}
          </Link>
          , {formatDay(note.created_at)}
        </p>
      )}
      <textarea
        aria-label="Content"
        placeholder="Write your note…"
        value={content}
        maxLength={50_000}
        onChange={(event) => setContent(event.target.value)}
        className="min-h-64 flex-1 resize-y rounded-md border bg-background p-3 text-sm"
      />
      <div className="flex items-center gap-2">
        <Button type="submit" disabled={!canSave}>
          {saving ? 'Saving…' : 'Save'}
        </Button>
        {note && !confirmingDelete && (
          <Button type="button" variant="ghost" onClick={() => setConfirmingDelete(true)}>
            Delete
          </Button>
        )}
        {note && confirmingDelete && (
          <div className="flex items-center gap-2 rounded-md border px-2 py-1 text-sm">
            <span>Delete this note?</span>
            <Button
              type="button"
              size="xs"
              variant="destructive"
              onClick={deleteNote}
              disabled={remove.isPending}
            >
              Delete
            </Button>
            <Button
              type="button"
              size="xs"
              variant="ghost"
              onClick={() => setConfirmingDelete(false)}
            >
              Cancel
            </Button>
          </div>
        )}
      </div>
    </form>
  )
}
