// Sidebar "Recent chats" (wireframe 6.1): open, rename or delete a saved chat. SMA-31.
import { PencilIcon, Trash2Icon } from 'lucide-react'
import { useState } from 'react'
import { NavLink, useNavigate, useParams } from 'react-router'
import { toast } from 'sonner'

import {
  type ConversationSummary,
  useConversations,
  useDeleteConversation,
  useRenameConversation,
} from '@/api/conversations'
import { Button } from '@/components/ui/button'
import { friendlyError } from '@/lib/errors'
import { cn } from '@/lib/utils'

export function RecentChats() {
  const conversations = useConversations()

  return (
    <nav aria-label="Recent chats" className="flex min-h-0 flex-col gap-1">
      <p className="px-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">
        Recent chats
      </p>
      {conversations.isError && (
        <p className="px-2 text-sm text-muted-foreground">Couldn&apos;t load your chats</p>
      )}
      {conversations.data?.length === 0 && (
        <p className="px-2 text-sm text-muted-foreground">No chats yet</p>
      )}
      <ul className="flex flex-col gap-0.5 overflow-y-auto">
        {conversations.data?.map((conversation) => (
          <ChatItem key={conversation.id} conversation={conversation} />
        ))}
      </ul>
    </nav>
  )
}

type Mode = 'show' | 'rename' | 'confirm-delete'

function ChatItem({ conversation }: { conversation: ConversationSummary }) {
  const [mode, setMode] = useState<Mode>('show')
  const title = conversation.title ?? 'Untitled chat'
  const rename = useRenameConversation()
  const remove = useDeleteConversation()
  const navigate = useNavigate()
  const { conversationId: openId } = useParams()

  function saveTitle(newTitle: string) {
    setMode('show')
    const trimmed = newTitle.trim()
    if (!trimmed || trimmed === conversation.title) return // nothing to save
    rename.mutate(
      { id: conversation.id, title: trimmed },
      { onError: (error) => toast.error(friendlyError(error)) },
    )
  }

  function deleteChat() {
    remove.mutate(conversation.id, {
      onSuccess: () => {
        if (openId === conversation.id) navigate('/') // it was open: start a fresh chat
      },
      onError: (error) => {
        setMode('show')
        toast.error(friendlyError(error))
      },
    })
  }

  if (mode === 'rename') {
    return (
      <li>
        <input
          aria-label="Chat title"
          defaultValue={conversation.title ?? ''}
          maxLength={200} // same limit as the backend
          autoFocus
          className="w-full rounded-md border bg-background px-2 py-1 text-sm"
          onKeyDown={(event) => {
            if (event.key === 'Enter') saveTitle(event.currentTarget.value)
            if (event.key === 'Escape') setMode('show')
          }}
          // Only Enter saves. Clicking away cancels, like Escape: saving on blur would
          // also save when Escape removes the box (it blurs as it disappears).
          onBlur={() => setMode('show')}
        />
      </li>
    )
  }

  if (mode === 'confirm-delete') {
    return (
      <li className="rounded-md border bg-background p-2 text-sm">
        <p className="mb-2">Delete this chat?</p>
        <div className="flex gap-2">
          <Button size="xs" variant="destructive" onClick={deleteChat} disabled={remove.isPending}>
            Delete
          </Button>
          <Button size="xs" variant="ghost" onClick={() => setMode('show')}>
            Cancel
          </Button>
        </div>
      </li>
    )
  }

  return (
    <li className="group flex items-center gap-0.5">
      <NavLink
        to={conversation.mode === 'study' ? `/study/${conversation.id}` : `/c/${conversation.id}`}
        className={({ isActive }) =>
          cn(
            'min-w-0 flex-1 truncate rounded-md px-2 py-1.5 text-sm hover:bg-muted',
            isActive && 'bg-muted font-medium',
          )
        }
      >
        {title}
      </NavLink>
      {/* Shown on hover or keyboard focus, so the list stays calm. */}
      <div className="flex opacity-0 group-hover:opacity-100 focus-within:opacity-100">
        <Button
          size="icon-xs"
          variant="ghost"
          aria-label={`Rename ${title}`}
          onClick={() => setMode('rename')}
        >
          <PencilIcon aria-hidden />
        </Button>
        <Button
          size="icon-xs"
          variant="ghost"
          aria-label={`Delete ${title}`}
          onClick={() => setMode('confirm-delete')}
        >
          <Trash2Icon aria-hidden />
        </Button>
      </div>
    </li>
  )
}
