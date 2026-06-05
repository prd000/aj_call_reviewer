import { useEffect, useRef, useState } from 'react'
import MarkdownMessage from './MarkdownMessage'
import './ChatPanel.css'

const MAX_ATTEMPTS = 3
const BACKOFF_MS = [600, 1500]

// Drag-to-resize bounds for the panel width (px).
const MIN_WIDTH = 320
const MAX_WIDTH = 760
const DEFAULT_WIDTH = 420
const WIDTH_STORAGE_KEY = 'chatPanelWidth'

function clampWidth(w) {
  return Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, w))
}

export default function ChatPanel({
  onSend,
  messages,
  setMessages,
  isOpen,
  onClose,
  onTimestampClick,
  title = 'Ask about this call',
  subtitle,
  emptyStateText = "Ask anything about this call's transcript.",
  inputPlaceholder = 'Ask a question about this call…',
}) {
  const [status, setStatus] = useState('idle') // idle | sending | retrying | unavailable | failed
  const [retryAttempt, setRetryAttempt] = useState(0)
  const [input, setInput] = useState('')
  const bottomRef = useRef(null)
  const textareaRef = useRef(null)

  // Drag-to-resize width (persisted across sessions).
  const [width, setWidth] = useState(() => {
    const saved = Number(localStorage.getItem(WIDTH_STORAGE_KEY))
    return saved ? clampWidth(saved) : DEFAULT_WIDTH
  })
  const widthRef = useRef(width)
  const isResizingRef = useRef(false)

  useEffect(() => {
    widthRef.current = width
  }, [width])

  // Drag the left edge to resize. Width grows as the cursor moves left
  // (panel is docked to the right), clamped to [MIN_WIDTH, MAX_WIDTH].
  useEffect(() => {
    function onMove(e) {
      if (!isResizingRef.current) return
      setWidth(clampWidth(window.innerWidth - e.clientX))
    }
    function onUp() {
      if (!isResizingRef.current) return
      isResizingRef.current = false
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      localStorage.setItem(WIDTH_STORAGE_KEY, String(widthRef.current))
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [])

  function startResize(e) {
    e.preventDefault()
    isResizingRef.current = true
    document.body.style.cursor = 'ew-resize'
    document.body.style.userSelect = 'none'
  }

  // Auto-scroll to bottom when messages change or status changes.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, status])

  // Auto-grow the textarea upward to fit its content; shrink back when cleared.
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
  }, [input])

  async function send(text) {
    if (!text.trim()) return
    const userMsg = { role: 'user', content: text.trim() }
    const nextMessages = [...messages, userMsg]
    setMessages(nextMessages)
    setInput('')
    setStatus('sending')
    setRetryAttempt(0)

    for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
      if (attempt > 0) {
        await new Promise((r) => setTimeout(r, BACKOFF_MS[attempt - 1] ?? 1500))
        setStatus('retrying')
        setRetryAttempt(attempt)
      }
      try {
        const { answer } = await onSend(nextMessages)
        setMessages([...nextMessages, { role: 'assistant', content: answer }])
        setStatus('idle')
        return
      } catch (err) {
        // 503 = no provider configured — terminal, no retry
        if (err.status === 503) {
          setStatus('unavailable')
          return
        }
        // 401 = api.js already redirected; treat as terminal
        if (err.status === 401) {
          setStatus('failed')
          return
        }
        // All other errors: retry unless this was the last attempt
        if (attempt === MAX_ATTEMPTS - 1) {
          setStatus('failed')
        }
      }
    }
  }

  function handleSubmit(e) {
    e.preventDefault()
    if (status === 'sending' || status === 'retrying' || !input.trim()) return
    send(input)
  }

  function handleKeyDown(e) {
    // Enter sends; Shift+Enter inserts a newline.
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  const isBusy = status === 'sending' || status === 'retrying'

  return (
    <div
      className={`chat-panel${isOpen ? ' chat-panel--open' : ''}`}
      style={{ '--chat-panel-width': `${width}px` }}
      aria-hidden={!isOpen}
    >
      <div
        className="chat-panel__resize-handle"
        onMouseDown={startResize}
        role="separator"
        aria-orientation="vertical"
        aria-label="Drag to resize chat panel"
      />
      <div className="chat-panel__header">
        <div className="chat-panel__header-text">
          <span className="chat-panel__title">{title}</span>
          {subtitle && <span className="chat-panel__subtitle">{subtitle}</span>}
        </div>
        <button className="chat-panel__close" onClick={onClose} aria-label="Close chat">
          &#10005;
        </button>
      </div>

      <div className="chat-panel__messages">
        {messages.length === 0 && status !== 'unavailable' && (
          <p className="chat-panel__empty">{emptyStateText}</p>
        )}

        {messages.map((msg, i) => (
          <div
            key={i}
            className={`chat-panel__bubble chat-panel__bubble--${msg.role}`}
          >
            {msg.role === 'assistant'
              ? <MarkdownMessage content={msg.content} onTimestampClick={onTimestampClick} />
              : msg.content}
          </div>
        ))}

        {status === 'sending' && (
          <div className="chat-panel__bubble chat-panel__bubble--assistant chat-panel__bubble--pending">
            …
          </div>
        )}
        {status === 'retrying' && (
          <div className="chat-panel__bubble chat-panel__bubble--assistant chat-panel__bubble--pending">
            retrying… (attempt {retryAttempt + 1})
          </div>
        )}
        {status === 'failed' && (
          <div className="chat-panel__bubble chat-panel__bubble--assistant chat-panel__bubble--error">
            Couldn&rsquo;t get an answer. Please try again later.
          </div>
        )}
        {status === 'unavailable' && (
          <div className="chat-panel__unavailable">
            Chat is unavailable: no AI provider is configured.
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      <form className="chat-panel__input-row" onSubmit={handleSubmit}>
        <textarea
          ref={textareaRef}
          className="chat-panel__input"
          rows={1}
          placeholder={inputPlaceholder}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isBusy || status === 'unavailable'}
          aria-label="Chat input"
        />
        <button
          className="chat-panel__send"
          type="submit"
          disabled={isBusy || status === 'unavailable' || !input.trim()}
        >
          Send
        </button>
      </form>
    </div>
  )
}
