// The conversation: user bubbles on the right, AI answers on the left. SMA-25.
import { CopyButton } from '@/components/chat/CopyButton'
import { Markdown } from '@/components/chat/Markdown'
import { MessageBadges } from '@/components/chat/MessageBadges'
import { SaveNoteButton } from '@/components/chat/SaveNoteButton'
import { ToolCalls } from '@/components/chat/ToolCalls'
import type { ChatMessage } from '@/components/chat/types'
import { cn } from '@/lib/utils'

type Props = {
  messages: ChatMessage[]
  isThinking?: boolean // waiting for the AI's answer
  // Shows "Save as note" on AI answers (SMA-32). Gets the answer and the question before it.
  onSaveAsNote?: (answer: ChatMessage, question: string | undefined) => Promise<unknown>
}

export function MessageList({ messages, isThinking = false, onSaveAsNote }: Props) {
  return (
    <div className="flex flex-col gap-4">
      <ol aria-label="Messages" className="flex flex-col gap-4">
        {messages.map((message, index) => {
          const fromUser = message.role === 'user'
          return (
            <li key={message.id} className={cn('flex', fromUser ? 'justify-end' : 'justify-start')}>
              <div
                className={cn(
                  'max-w-[80%] rounded-2xl px-4 py-3',
                  fromUser ? 'bg-primary text-primary-foreground' : 'bg-muted',
                )}
              >
                <p className="mb-1 text-xs font-medium opacity-70">
                  {fromUser ? 'You' : 'StudyMate'}
                </p>
                {fromUser ? (
                  // Plain text, exactly as typed (React escapes it; no Markdown).
                  <p className="whitespace-pre-wrap">{message.content}</p>
                ) : (
                  <>
                    <Markdown>{message.content}</Markdown>
                    {message.meta?.toolCalls?.length ? (
                      <ToolCalls calls={message.meta.toolCalls} />
                    ) : null}
                    <div className="mt-2 flex items-center justify-between gap-2">
                      {message.meta ? <MessageBadges meta={message.meta} /> : <span />}
                      <div className="flex items-center">
                        {onSaveAsNote && (
                          <SaveNoteButton
                            onSave={() => onSaveAsNote(message, messages[index - 1]?.content)}
                          />
                        )}
                        <CopyButton text={message.content} />
                      </div>
                    </div>
                  </>
                )}
              </div>
            </li>
          )
        })}
      </ol>
      {isThinking && (
        <p role="status" className="animate-pulse text-sm text-muted-foreground">
          StudyMate is thinking…
        </p>
      )}
    </div>
  )
}
