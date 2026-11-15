// One message in the chat, as the page keeps it. SMA-25, badges SMA-26.
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
}
