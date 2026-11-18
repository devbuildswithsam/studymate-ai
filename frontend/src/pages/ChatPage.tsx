// General chat (wireframe 6.1): messages, input, loading and friendly errors. SMA-25.
// Model selector, "Use fallback" toggle and answer badges (wireframe 6.9). SMA-26.
// Saved chats: reopen at /c/:id, continue with the same model, auto title (SMA-31).
// "Save as note" on AI answers (SMA-32). "Used tool: …" lines under answers (SMA-42).
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { toast } from 'sonner'

import { useSendMessage } from '@/api/chat'
import { ApiError } from '@/api/client'
import { addTurn, requestTitle, type SavedMessage, useConversation } from '@/api/conversations'
import { type ModelInfo, useModels } from '@/api/models'
import { useCreateNote } from '@/api/notes'
import { ChatInput } from '@/components/chat/ChatInput'
import { MessageList } from '@/components/chat/MessageList'
import { ModelSelector } from '@/components/chat/ModelSelector'
import type { ChatMessage } from '@/components/chat/types'
import { friendlyError } from '@/lib/errors'
import { firstWords } from '@/lib/text'

/** A saved message as the message list shows it, with badges on answers. */
function toChatMessage(message: SavedMessage, models: ModelInfo[]): ChatMessage {
  const role = message.role === 'user' ? 'user' : 'assistant'
  if (role === 'user' || !message.model) return { id: message.id, role, content: message.content }
  const answeredBy = models.find((m) => m.id === message.model)
  return {
    id: message.id,
    role,
    content: message.content,
    meta: {
      modelName: answeredBy?.display_name ?? message.model, // raw id if the list isn't loaded
      // The reason is only known for answers given while the page was open.
      fallbackReason: message.fallback_used ? (message.fallback_reason ?? 'fallback used') : null,
      toolCalls: message.tool_calls ?? [], // SMA-42: "Used tool: …" lines
    },
  }
}

type Props = {
  conversationId?: string // undefined = a new chat
  pageKey?: string // passed on when a new chat moves to its own address (see App.tsx)
}

export function ChatPage({ conversationId, pageKey }: Props) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  // A new chat's id, as soon as it exists, so a failed first answer is retried in it.
  const [createdId, setCreatedId] = useState<string>()
  // Show the chat from the address, or the one just created here. The second is read
  // from the cache only: this page owns its messages, so there is nothing to fetch. That
  // way the first answer shows at once, before the address changes (no empty flash).
  const conversation = useConversation(conversationId ?? createdId, {
    load: conversationId !== undefined,
  })
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [chosenModel, setChosenModel] = useState<string>()
  const [allowFallback, setAllowFallback] = useState(true)
  const sendMessage = useSendMessage(setCreatedId)
  const createNote = useCreateNote()
  const models = useModels()

  const modelList = models.data?.models ?? []
  // What you picked now, else the model this chat used last (SMA-31), else the default.
  // Computed each render, so no effect is needed to copy them into state.
  const model = chosenModel ?? conversation.data?.model ?? models.data?.default_model ?? undefined
  const saved = conversation.data?.messages ?? []
  const messages: ChatMessage[] = saved.map((m) => toChatMessage(m, modelList))
  if (pendingQuestion !== null) {
    messages.push({ id: 'pending', role: 'user', content: pendingQuestion }) // shown at once
  }

  function send() {
    const text = draft
    const isFirstAnswer = saved.length === 0
    setPendingQuestion(text)
    setDraft('')

    sendMessage.mutate(
      {
        message: text,
        conversation_id: conversationId ?? createdId,
        model, // left out when unknown: the backend uses its default
        allow_fallback: allowFallback,
      },
      {
        onSuccess: (reply) => {
          const id = reply.conversation_id
          addTurn(queryClient, id, text, reply, model) // the cache is what the page shows
          setPendingQuestion(null)
          if (isFirstAnswer) void requestTitle(queryClient, id) // in the background
          if (!conversationId) {
            // Give the new chat its own address (reload- and bookmark-safe). The same
            // pageKey keeps this page on screen instead of starting a fresh one.
            navigate(`/c/${id}`, { replace: true, state: { pageKey } })
          }
        },
        onError: (error) => {
          // Remove the waiting bubble and give the text back, ready to retry.
          setPendingQuestion(null)
          setDraft(text)
          toast.error(friendlyError(error))
        },
      },
    )
  }

  /** Save an answer as a note, linked to its message so the note shows where it came from. */
  async function saveAsNote(answer: ChatMessage, question: string | undefined) {
    const title = conversation.data?.title ?? (question ? firstWords(question) : 'Saved answer')
    try {
      const note = await createNote.mutateAsync({
        title,
        content: answer.content,
        tags: [],
        source_message_id: answer.id,
      })
      toast.success('Saved to Notes', {
        action: { label: 'Open', onClick: () => navigate(`/notes/${note.id}`) },
      })
    } catch (error) {
      toast.error(friendlyError(error))
      throw error // so the button lets you try again
    }
  }

  if (conversation.isError) {
    const gone = conversation.error instanceof ApiError && conversation.error.status === 404
    return (
      <div className="mx-auto max-w-3xl space-y-3">
        <h1 className="text-2xl font-semibold">Chat</h1>
        <p className="text-muted-foreground">
          {gone
            ? "This chat doesn't exist (maybe it was deleted)."
            : friendlyError(conversation.error)}
        </p>
        <Link to="/" className="text-sm underline">
          Start a new chat
        </Link>
      </div>
    )
  }

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col gap-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">{conversation.data?.title ?? 'Chat'}</h1>
        {model && modelList.length > 0 && (
          <ModelSelector
            models={modelList}
            model={model}
            onModelChange={setChosenModel}
            allowFallback={allowFallback}
            onAllowFallbackChange={setAllowFallback}
          />
        )}
      </header>
      <div className="flex-1">
        {conversation.isLoading && <p className="text-muted-foreground">Loading chat…</p>}
        {!conversationId && messages.length === 0 && (
          <p className="text-muted-foreground">
            Ask a study question to get started, e.g. “Explain Newton&apos;s second law”.
          </p>
        )}
        <MessageList
          messages={messages}
          isThinking={sendMessage.isPending}
          onSaveAsNote={saveAsNote}
        />
      </div>
      <ChatInput
        value={draft}
        onChange={setDraft}
        onSend={send}
        disabled={sendMessage.isPending || conversation.isLoading}
      />
    </div>
  )
}
