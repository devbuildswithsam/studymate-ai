// Study chat (wireframe 6.2): ask your documents, get answers with citations. SMA-49.
//
// Pick documents -> ask -> the answer is built only from them (guide 7.3), labelled
// "From your documents · n sources" with chips that open the cited chunk in the Sources
// panel, or "Not found in your documents" with a button to answer from general knowledge.
import { useQueryClient } from '@tanstack/react-query'
import { XIcon } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { toast } from 'sonner'

import { type Citation, useSendMessage } from '@/api/chat'
import { apiPut, ApiError } from '@/api/client'
import {
  addTurn,
  type ConversationDetail,
  detailKey,
  type DocumentRef,
  requestTitle,
  type SavedMessage,
  useConversation,
} from '@/api/conversations'
import { useDocuments } from '@/api/documents'
import { type ModelInfo, useModels } from '@/api/models'
import { ChatInput } from '@/components/chat/ChatInput'
import { MessageList } from '@/components/chat/MessageList'
import type { ChatMessage } from '@/components/chat/types'
import { Button } from '@/components/ui/button'
import { citationLabel } from '@/lib/citations'
import { friendlyError } from '@/lib/errors'

function toChatMessage(message: SavedMessage, models: ModelInfo[]): ChatMessage {
  const role = message.role === 'user' ? 'user' : 'assistant'
  if (role === 'user' || !message.model) return { id: message.id, role, content: message.content }
  return {
    id: message.id,
    role,
    content: message.content,
    meta: {
      modelName: models.find((m) => m.id === message.model)?.display_name ?? message.model,
      fallbackReason: message.fallback_used ? (message.fallback_reason ?? 'fallback used') : null,
      grounded: message.mode === 'grounded' ? { citations: message.citations ?? [] } : undefined,
    },
  }
}

type Props = {
  conversationId?: string // undefined = a new study chat
  pageKey?: string // kept when a new chat moves to its own address (see App.tsx)
  initialDocuments?: DocumentRef[] // SMA-50: "Chat with this document"
}

export function StudyPage({ conversationId, pageKey, initialDocuments = [] }: Props) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [createdId, setCreatedId] = useState<string>()
  const chatId = conversationId ?? createdId
  const conversation = useConversation(chatId, { load: conversationId !== undefined })
  const documents = useDocuments()
  const models = useModels()
  const [picked, setPicked] = useState<DocumentRef[]>(initialDocuments) // a new chat's documents
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [shown, setShown] = useState<{ messageId: string; n: number }>()

  // A saved chat's documents come from the server; a new chat's from this page.
  const selected = conversation.data?.documents ?? picked
  const sendMessage = useSendMessage(setCreatedId, {
    mode: 'study',
    document_ids: selected.map((d) => d.id),
  })
  const ready = (documents.data ?? []).filter((d) => d.status === 'ready')
  const addable = ready.filter((d) => !selected.some((s) => s.id === d.id))

  const saved = conversation.data?.messages ?? []
  const modelList = models.data?.models ?? []
  const messages = saved.map((m) => toChatMessage(m, modelList))
  if (pendingQuestion !== null) {
    messages.push({ id: 'pending', role: 'user', content: pendingQuestion })
  }

  // The Sources panel: the clicked answer, else the latest answer that has sources.
  const withSources = [...saved].reverse().find((m) => m.citations?.length)
  const sourceMessage = saved.find((m) => m.id === shown?.messageId) ?? withSources
  const sources: Citation[] = sourceMessage?.citations ?? []

  async function changeDocuments(next: DocumentRef[]) {
    if (!chatId) {
      setPicked(next) // nothing saved yet: the chat is created with them
      return
    }
    try {
      const updated = await apiPut<ConversationDetail>(`/api/conversations/${chatId}/documents`, {
        document_ids: next.map((d) => d.id),
      })
      queryClient.setQueryData<ConversationDetail>(
        detailKey(chatId),
        (old) => old && { ...old, documents: updated.documents ?? [] },
      )
    } catch (error) {
      toast.error(friendlyError(error))
    }
  }

  function send(text: string, extra: { general?: boolean } = {}) {
    const isFirstAnswer = saved.length === 0
    const documentsNow = selected
    setPendingQuestion(text)
    setDraft('')
    sendMessage.mutate(
      { message: text, conversation_id: chatId, ...extra },
      {
        onSuccess: (reply) => {
          const id = reply.conversation_id
          addTurn(queryClient, id, text, reply, undefined)
          // A new chat's cache starts from this page: give it its documents too.
          queryClient.setQueryData<ConversationDetail>(
            detailKey(id),
            (old) => old && { ...old, mode: 'study', documents: old.documents ?? documentsNow },
          )
          setPendingQuestion(null)
          if (isFirstAnswer) void requestTitle(queryClient, id)
          if (!conversationId) navigate(`/study/${id}`, { replace: true, state: { pageKey } })
        },
        onError: (error) => {
          setPendingQuestion(null)
          setDraft(text)
          toast.error(friendlyError(error))
        },
      },
    )
  }

  if (conversation.isError) {
    const gone = conversation.error instanceof ApiError && conversation.error.status === 404
    return (
      <div className="mx-auto max-w-3xl space-y-3">
        <h1 className="text-2xl font-semibold">Study</h1>
        <p className="text-muted-foreground">
          {gone
            ? "This chat doesn't exist (maybe it was deleted)."
            : friendlyError(conversation.error)}
        </p>
        <Link to="/study" className="text-sm underline">
          Start a new study chat
        </Link>
      </div>
    )
  }

  return (
    <div className="mx-auto flex h-full max-w-6xl gap-6">
      <div className="flex min-w-0 flex-1 flex-col gap-4">
        <h1 className="text-2xl font-semibold">{conversation.data?.title ?? 'Study'}</h1>

        <div className="flex flex-wrap items-center gap-2" aria-label="Documents of this chat">
          <span className="text-sm text-muted-foreground">Documents:</span>
          {selected.map((d) => (
            <span
              key={d.id}
              className="flex items-center gap-1 rounded-full border px-3 py-1 text-sm"
            >
              {d.filename}
              <button
                type="button"
                aria-label={`Remove ${d.filename}`}
                className="rounded-full hover:bg-muted"
                onClick={() => void changeDocuments(selected.filter((s) => s.id !== d.id))}
              >
                <XIcon aria-hidden className="size-3.5" />
              </button>
            </span>
          ))}
          {addable.length > 0 && (
            <select
              aria-label="Add document"
              value=""
              className="rounded-md border bg-background px-2 py-1 text-sm"
              onChange={(e) => {
                const document = ready.find((d) => d.id === e.target.value)
                if (document) {
                  void changeDocuments([
                    ...selected,
                    { id: document.id, filename: document.filename },
                  ])
                }
              }}
            >
              <option value="">+ add document</option>
              {addable.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.filename}
                </option>
              ))}
            </select>
          )}
        </div>

        {documents.data && ready.length === 0 && (
          <p className="text-muted-foreground">
            Upload a document first on the{' '}
            <Link to="/documents" className="underline">
              Documents page
            </Link>
            .
          </p>
        )}

        <div className="flex-1">
          {conversation.isLoading && <p className="text-muted-foreground">Loading chat…</p>}
          <MessageList
            messages={messages}
            isThinking={sendMessage.isPending}
            onCitation={(messageId, n) => setShown({ messageId, n })}
            onAnswerGenerally={(question) => send(question, { general: true })}
          />
        </div>
        <ChatInput
          value={draft}
          onChange={setDraft}
          onSend={() => send(draft)}
          disabled={selected.length === 0 || sendMessage.isPending || conversation.isLoading}
          placeholder={
            selected.length ? 'Ask about these documents…' : 'Add a document to start asking'
          }
        />
      </div>

      <aside aria-label="Sources" className="hidden w-80 shrink-0 space-y-3 md:block">
        <h2 className="font-semibold">Sources</h2>
        {sources.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            The pages an answer comes from show up here.
          </p>
        ) : (
          <ul className="space-y-3">
            {sources.map((source) => {
              const current = sourceMessage?.id === shown?.messageId && source.n === shown?.n
              return (
                <li
                  key={source.n}
                  aria-label={citationLabel(source)}
                  aria-current={current ? 'true' : undefined}
                  className={
                    current ? 'rounded-lg border-2 border-primary p-3' : 'rounded-lg border p-3'
                  }
                >
                  <p className="text-sm font-medium">{citationLabel(source)}</p>
                  <p className="mt-1 line-clamp-[12] text-sm whitespace-pre-line text-muted-foreground">
                    {source.text}
                  </p>
                </li>
              )
            })}
          </ul>
        )}
        {sources.length > 0 && shown && (
          <Button size="xs" variant="ghost" onClick={() => setShown(undefined)}>
            Clear highlight
          </Button>
        )}
      </aside>
    </div>
  )
}
