// General chat (wireframe 6.1): messages, input, loading and friendly errors. SMA-25.
import { useState } from 'react'
import { toast } from 'sonner'

import { useSendMessage } from '@/api/chat'
import { ChatInput } from '@/components/chat/ChatInput'
import { MessageList } from '@/components/chat/MessageList'
import type { ChatMessage } from '@/components/chat/types'
import { friendlyError } from '@/lib/errors'

let nextId = 0
const newId = () => `msg-${++nextId}`

export function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [conversationId, setConversationId] = useState<string>()
  const [draft, setDraft] = useState('')
  const sendMessage = useSendMessage()

  function send() {
    const text = draft
    const question: ChatMessage = { id: newId(), role: 'user', content: text }
    setMessages((current) => [...current, question]) // show it at once, before the answer
    setDraft('')

    sendMessage.mutate(
      { message: text, conversation_id: conversationId },
      {
        onSuccess: (reply) => {
          setConversationId(reply.conversation_id) // so the next message continues it
          setMessages((current) => [
            ...current,
            { id: newId(), role: 'assistant', content: reply.reply },
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
      <h1 className="text-2xl font-semibold">Chat</h1>
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
