// General chat (wireframe 6.1): messages, input, loading and friendly errors. SMA-25.
// Model selector, "Use fallback" toggle and answer badges (wireframe 6.9). SMA-26.
import { useState } from 'react'
import { toast } from 'sonner'

import { type ChatReply, useSendMessage } from '@/api/chat'
import { type ModelInfo, useModels } from '@/api/models'
import { ChatInput } from '@/components/chat/ChatInput'
import { MessageList } from '@/components/chat/MessageList'
import { ModelSelector } from '@/components/chat/ModelSelector'
import type { AnswerMeta, ChatMessage } from '@/components/chat/types'
import { friendlyError } from '@/lib/errors'

let nextId = 0
const newId = () => `msg-${++nextId}`

/** Badge data for an answer: the model that ACTUALLY answered (may be a fallback). */
function answerMeta(reply: ChatReply, models: ModelInfo[]): AnswerMeta {
  const answeredBy = models.find((m) => m.id === reply.model)
  return {
    modelName: answeredBy?.display_name ?? reply.model, // raw id if the list isn't loaded
    fallbackReason: reply.fallback_used ? (reply.fallback_reason ?? 'fallback used') : null,
  }
}

export function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [conversationId, setConversationId] = useState<string>()
  const [draft, setDraft] = useState('')
  const [chosenModel, setChosenModel] = useState<string>()
  const [allowFallback, setAllowFallback] = useState(true)
  const sendMessage = useSendMessage(setConversationId) // SMA-30: remembered even if the AI fails
  const models = useModels()

  const modelList = models.data?.models ?? []
  // What you picked, otherwise the registry's default. Computed each render, so no
  // effect is needed to copy the default into state once the list loads.
  const model = chosenModel ?? models.data?.default_model ?? undefined

  function send() {
    const text = draft
    const question: ChatMessage = { id: newId(), role: 'user', content: text }
    setMessages((current) => [...current, question]) // show it at once, before the answer
    setDraft('')

    sendMessage.mutate(
      {
        message: text,
        conversation_id: conversationId,
        model, // left out when unknown: the backend uses its default
        allow_fallback: allowFallback,
      },
      {
        onSuccess: (reply) => {
          setConversationId(reply.conversation_id) // so the next message continues it
          setMessages((current) => [
            ...current,
            {
              id: newId(),
              role: 'assistant',
              content: reply.reply,
              meta: answerMeta(reply, modelList),
            },
          ])
        },
        onError: (error) => {
          // Undo the optimistic bubble and give the text back, ready to retry.
          setMessages((current) => current.filter((m) => m.id !== question.id))
          setDraft(text)
          toast.error(friendlyError(error))
        },
      },
    )
  }

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col gap-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Chat</h1>
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
        {messages.length === 0 && !sendMessage.isPending ? (
          <p className="text-muted-foreground">
            Ask a study question to get started, e.g. “Explain Newton&apos;s second law”.
          </p>
        ) : null}
        <MessageList messages={messages} isThinking={sendMessage.isPending} />
      </div>
      <ChatInput value={draft} onChange={setDraft} onSend={send} disabled={sendMessage.isPending} />
    </div>
  )
}
