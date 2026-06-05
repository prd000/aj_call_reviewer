import { useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeTimestamps from '../lib/rehypeTimestamps'

export default function MarkdownMessage({ content, onTimestampClick }) {
  const rehypePlugins = useMemo(
    () => (onTimestampClick ? [rehypeTimestamps] : []),
    [onTimestampClick],
  )

  const components = useMemo(
    () => ({
      // Custom element emitted by the rehype plugin
      timestamp({ node, ...props }) {
        const ts = node?.properties?.value ?? props.value
        if (!onTimestampClick) return ts
        return (
          <button
            className="chat-panel__ts"
            onClick={() => onTimestampClick(ts)}
          >
            {ts}
          </button>
        )
      },
      a({ href, children }) {
        return (
          <a href={href} target="_blank" rel="noopener noreferrer">
            {children}
          </a>
        )
      },
      table({ children }) {
        return (
          <div className="chat-panel__table-wrap">
            <table>{children}</table>
          </div>
        )
      },
    }),
    [onTimestampClick],
  )

  return (
    <div className="chat-panel__markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={rehypePlugins}
        components={components}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}
