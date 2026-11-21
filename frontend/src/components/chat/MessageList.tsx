// The conversation: user bubbles on the right, AI answers on the left. SMA-25.
import type { ActionVerb, AgentAction } from '@/api/actions'
import type { LiveAnswer } from '@/api/chat'
import { ActionCards } from '@/components/chat/ActionCards'
import { CopyButton } from '@/components/chat/CopyButton'
import { FlashcardsButton } from '@/components/chat/FlashcardsButton'
import { Markdown } from '@/components/chat/Markdown'
import { MessageBadges } from '@/components/chat/MessageBadges'
import { SaveNoteButton } from '@/components/chat/SaveNoteButton'
import { GroundedExtras } from '@/components/chat/GroundedExtras'
import { ToolCalls } from '@/components/chat/ToolCalls'
import type { ChatMessage } from '@/components/chat/types'
import { cn } from '@/lib/utils'

type Props = {
  messages: ChatMessage[]
  isThinking?: boolean // waiting for the AI's answer
  // Shows "Save as note" on AI answers (SMA-32). Gets the answer and the question before it.
  onSaveAsNote?: (answer: ChatMessage, question: string | undefined) => Promise<unknown>
  // Confirm / Cancel / Undo on the AI's actions (SMA-43).
  onAction?: (action: AgentAction, verb: ActionVerb) => Promise<unknown>
  // SMA-64: "Make flashcards" from one answer.
  onMakeFlashcards?: (answer: ChatMessage) => Promise<unknown>
  // SMA-49, study answers: a citation chip was clicked; "Answer from general knowledge".
  onCitation?: (messageId: string, n: number) => void
  onAnswerGenerally?: (question: string) => void
  live?: LiveAnswer | null // SMA-62: the answer while it is being written
}

export function MessageList({
  messages,
  isThinking = false,
  onSaveAsNote,
  onAction,
  onMakeFlashcards,
  onCitation,
  onAnswerGenerally,
  live = null,
}: Props) {
  // "Thinking…" only until the first words (or tool steps) of the answer arrive.
  const writing = live !== null && (live.text !== '' || live.toolCalls.length > 0)
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
                    {message.meta?.grounded && (
                      <GroundedExtras
                        messageId={message.id}
                        citations={message.meta.grounded.citations}
                        question={messages[index - 1]?.content}
                        onCitation={onCitation}
                        onAnswerGenerally={onAnswerGenerally}
                      />
                    )}
                    {message.meta?.actions?.length && onAction ? (
                      <ActionCards actions={message.meta.actions} onAction={onAction} />
                    ) : null}
                    <div className="mt-2 flex items-center justify-between gap-2">
                      {message.meta ? <MessageBadges meta={message.meta} /> : <span />}
                      <div className="flex items-center">
                        {onMakeFlashcards && (
                          <FlashcardsButton onMake={() => onMakeFlashcards(message)} />
                        )}
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
        {writing && live && (
          // aria-busy: screen readers wait for the finished answer instead of reading
          // every new word aloud.
          <li className="flex justify-start" aria-busy="true">
            <div className="max-w-[80%] rounded-2xl bg-muted px-4 py-3">
              <p className="mb-1 text-xs font-medium opacity-70">StudyMate</p>
              {live.text && <Markdown>{live.text}</Markdown>}
              {live.toolCalls.length > 0 && <ToolCalls calls={live.toolCalls} />}
            </div>
          </li>
        )}
      </ol>
      {isThinking && !writing && (
        <p role="status" className="animate-pulse text-sm text-muted-foreground">
          StudyMate is thinking…
        </p>
      )}
    </div>
  )
}
