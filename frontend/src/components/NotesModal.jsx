import { useEffect, useState } from 'react'
import './NotesModal.css'

export default function NotesModal({ isOpen, onClose, initialNotes, onSave, isSaving, saveError }) {
  const [text, setText] = useState(initialNotes || '')

  // Reseed text from initialNotes each time the modal opens.
  useEffect(() => {
    if (isOpen) {
      setText(initialNotes || '')
    }
  }, [isOpen, initialNotes])

  if (!isOpen) return null

  function handleSave() {
    onSave(text.trim() || null)
  }

  function handleKeyDown(e) {
    if (e.key === 'Escape') onClose()
  }

  return (
    <div className="notes-modal__overlay" onClick={onClose} onKeyDown={handleKeyDown} role="dialog" aria-modal="true" aria-label="Review notes">
      <div className="notes-modal" onClick={(e) => e.stopPropagation()}>
        <div className="notes-modal__header">
          <h2 className="notes-modal__title">Internal Notes</h2>
          <button
            type="button"
            className="notes-modal__close"
            onClick={onClose}
            aria-label="Close notes"
          >
            &#x2715;
          </button>
        </div>

        <p className="notes-modal__hint">
          Notes are internal only and never included in the PDF or visible to advisors.
        </p>

        <textarea
          className="notes-modal__textarea"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Add notes about this call…"
          rows={8}
          disabled={isSaving}
        />

        {saveError && <p className="notes-modal__error">{saveError}</p>}

        <div className="notes-modal__actions">
          <button
            type="button"
            className="notes-modal__cancel"
            onClick={onClose}
            disabled={isSaving}
          >
            Cancel
          </button>
          <button
            type="button"
            className="notes-modal__save"
            onClick={handleSave}
            disabled={isSaving}
          >
            {isSaving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
