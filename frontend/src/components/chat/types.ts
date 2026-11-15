// One message in the chat, as the page keeps it. SMA-25.
export type ChatMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string // the user's text, or the AI's Markdown
}
