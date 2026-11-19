// One message in the chat, as the page keeps it. SMA-25, badges SMA-26.
import type { AgentAction } from '@/api/actions'
import type { Citation, ToolCallOut } from '@/api/chat'

export type ChatMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string // the user's text, or the AI's Markdown
  meta?: AnswerMeta // only on AI answers
}

/** Who answered and how: shown as badges under the answer (guide §7.5). */
export type AnswerMeta = {
  modelName: string // the model that actually answered, e.g. "Gemini 3.5 Flash"
  fallbackReason: string | null // set when a backup model answered, e.g. "gemini...: rate-limited"
  toolCalls?: ToolCallOut[] // the tools the AI used for this answer (SMA-42)
  actions?: AgentAction[] // its writes: cards to confirm, creates to undo (SMA-43)
  // SMA-49: a study answer. Citations empty = "Not found in your documents".
  grounded?: { citations: Citation[] }
}
