import { useState } from 'react'
import './TranscriptPanel.css'

export default function TranscriptPanel({ transcript, speakerMap = {} }) {
  const [isOpen, setIsOpen] = useState(false)

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
            <div key={index} className="transcript-panel__segment">
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
}
