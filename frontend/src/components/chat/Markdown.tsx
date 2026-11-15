// Renders an AI answer: Markdown, tables/code (GFM) and maths (KaTeX). SMA-25.
import 'katex/dist/katex.min.css'

import ReactMarkdown from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'

export function Markdown({ children }: { children: string }) {
  return (
    <div className="prose prose-sm max-w-none dark:prose-invert">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        // Security (XSS): raw HTML in an answer is dropped, never rendered as real elements.
        // AI output is untrusted text: "<img onerror=...>" must not run in the user's browser.
        skipHtml
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}
