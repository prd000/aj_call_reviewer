import { forwardRef, useImperativeHandle, useRef, useState } from 'react'
import './TranscriptPanel.css'

function resolveIndex(transcript, ts) {
  // Parse HH:MM:SS into total seconds
  function toSeconds(t) {
    if (!t) return 0
    const parts = t.split(':').map(Number)
    if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if (parts.length === 2) return parts[0] * 60 + parts[1]
    return parts[0]
  }
  const target = toSeconds(ts)
  // Exact match first
  const exact = transcript.findIndex((s) => s.timestamp === ts)
  if (exact !== -1) return exact
  // Nearest by seconds
  let best = 0
  let bestDiff = Infinity
  transcript.forEach((s, i) => {
    const diff = Math.abs(toSeconds(s.timestamp) - target)
    if (diff < bestDiff) { bestDiff = diff; best = i }
  })
  return best
}

const TranscriptPanel = forwardRef(function TranscriptPanel(
  { transcript, speakerMap = {} },
  ref,
) {
  const [isOpen, setIsOpen] = useState(false)
  const [highlightIdx, setHighlightIdx] = useState(null)
  const segmentRefs = useRef([])

  useImperativeHandle(ref, () => ({
    jumpTo(ts) {
      setIsOpen(true)
      const idx = resolveIndex(transcript, ts)
      setHighlightIdx(idx)
      // Double RAF: first RAF waits for isOpen→true to commit; second waits for
      // the content div to render and measure before scrolling.
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          const el = segmentRefs.current[idx]
          if (el) el.scrollIntoView({ block: 'center', behavior: 'smooth' })
        })
      })
      setTimeout(() => setHighlightIdx(null), 1600)
    },
  }))

  if (!transcript || transcript.length === 0) {
    return null
  }

  return (
    <div className="transcript-panel">
      <button
        className="transcript-panel__toggle"
        onClick={() => setIsOpen((prev) => !prev)}
        aria-expanded={isOpen}
      >
        <span className="transcript-panel__toggle-label">
          Full Transcript
          <span className="transcript-panel__count">({transcript.length} segments)</span>
        </span>
        <span
          className={`transcript-panel__chevron${isOpen ? ' transcript-panel__chevron--open' : ''}`}
          aria-hidden="true"
        >
          &#8964;
        </span>
      </button>

      {isOpen && (
        <div className="transcript-panel__content" role="region" aria-label="Call transcript">
          {transcript.map((segment, index) => (
            <div
              key={index}
              ref={(el) => (segmentRefs.current[index] = el)}
              className={`transcript-panel__segment${highlightIdx === index ? ' transcript-panel__segment--highlight' : ''}`}
            >
              <span className="transcript-panel__timestamp">{segment.timestamp}</span>
              <div className="transcript-panel__body">
                {segment.speaker !== undefined && (
                  <span className="transcript-panel__speaker">
                    {speakerMap[segment.speaker] ?? `Speaker ${segment.speaker + 1}`}
                  </span>
                )}
                <span className="transcript-panel__text">{segment.text}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
})

export default TranscriptPanel
