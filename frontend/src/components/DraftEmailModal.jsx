import { useEffect, useState } from 'react'
import './DraftEmailModal.css'

export default function DraftEmailModal({
  isOpen,
  onClose,
  subject,
  body,
  isDrafting,
  draftError,
  onRegenerate,
}) {
  const [subjectText, setSubjectText] = useState(subject || '')
  const [bodyText, setBodyText] = useState(body || '')
  const [copied, setCopied] = useState(false)

  // Reseed the editable fields whenever a fresh draft arrives (open or regenerate).
  useEffect(() => {
    setSubjectText(subject || '')
  }, [subject])
  useEffect(() => {
    setBodyText(body || '')
  }, [body])

  // Clear the transient "Copied" flag when the draft changes or the modal reopens.
  useEffect(() => {
    setCopied(false)
  }, [isOpen, subject, body])

  if (!isOpen) return null

  function handleKeyDown(e) {
    if (e.key === 'Escape') onClose()
  }

  async function handleCopy() {
    const text = `Subject: ${subjectText}\n\n${bodyText}`
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }

  return (
    <div
      className="draft-email-modal__overlay"
      onClick={onClose}
      onKeyDown={handleKeyDown}
      role="dialog"
      aria-modal="true"
      aria-label="Draft coaching email"
    >
      <div className="draft-email-modal" onClick={(e) => e.stopPropagation()}>
        <div className="draft-email-modal__header">
          <h2 className="draft-email-modal__title">Draft Coaching Email</h2>
          <button
            type="button"
            className="draft-email-modal__close"
            onClick={onClose}
            aria-label="Close draft"
          >
            &#x2715;
          </button>
        </div>

        <p className="draft-email-modal__hint">
          An AI-drafted coaching email. Edit anything below, then copy it into your mail client.
          Nothing is saved or sent.
        </p>

        <label className="draft-email-modal__label" htmlFor="draft-email-subject">
          Subject
        </label>
        <input
          id="draft-email-subject"
          className="draft-email-modal__subject"
          type="text"
          value={subjectText}
          onChange={(e) => setSubjectText(e.target.value)}
          disabled={isDrafting}
        />

        <label className="draft-email-modal__label" htmlFor="draft-email-body">
          Body
        </label>
        <textarea
          id="draft-email-body"
          className="draft-email-modal__textarea"
          value={bodyText}
          onChange={(e) => setBodyText(e.target.value)}
          rows={14}
          disabled={isDrafting}
        />

        {draftError && <p className="draft-email-modal__error">{draftError}</p>}

        <div className="draft-email-modal__actions">
          <button
            type="button"
            className="draft-email-modal__cancel"
            onClick={onClose}
            disabled={isDrafting}
          >
            Close
          </button>
          <button
            type="button"
            className="draft-email-modal__regen"
            onClick={onRegenerate}
            disabled={isDrafting}
          >
            {isDrafting ? 'Regenerating…' : 'Regenerate'}
          </button>
          <button
            type="button"
            className="draft-email-modal__copy"
            onClick={handleCopy}
            disabled={isDrafting}
          >
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>
      </div>
    </div>
  )
}
