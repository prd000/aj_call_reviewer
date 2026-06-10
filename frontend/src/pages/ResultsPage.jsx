import { useEffect, useRef, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import ReviewResults from '../components/ReviewResults'
import ChatPanel from '../components/ChatPanel'
import { useLoadingWatchdog } from '../hooks/useLoadingWatchdog'
import { useAuth } from '../context/AuthContext'
import { chatAboutReview, downloadReviewPdf, getReview, retryReview, updateReviewMajorFocus, updateReviewOutcome } from '../services/api'
import { downloadBlob } from '../lib/download'
import './ResultsPage.css'

const IN_PROGRESS_STATUSES = ['pending', 'transcribing', 'reviewing']
const PROCESSING_LABELS = {
  pending: 'Queued for processing…',
  transcribing: 'Transcribing the call…',
  reviewing: 'Generating the review…',
}

function RobotIcon() {
  // Inline SVG (repo uses inline glyphs, no icon library). Strokes use currentColor so the
  // glyph reads dark on the yellow FAB via the parent's `color: var(--color-on-primary)`.
  return (
    <svg
      width="28"
      height="28"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="4" y="8" width="16" height="11" rx="2.5" />
      <path d="M12 4v4" />
      <circle cx="12" cy="3" r="1.2" fill="currentColor" stroke="none" />
      <path d="M4 12.5H2.5M20 12.5h1.5" />
      <circle cx="9" cy="13" r="1.3" fill="currentColor" stroke="none" />
      <circle cx="15" cy="13" r="1.3" fill="currentColor" stroke="none" />
      <path d="M9.5 16h5" />
    </svg>
  )
}

export default function ResultsPage() {
  const { id } = useParams()
  const { user } = useAuth()
  const isBds = user?.role === 'bds_rep'
  const [review, setReview] = useState(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState(null)
  const [isSavingOutcome, setIsSavingOutcome] = useState(false)
  const [outcomeError, setOutcomeError] = useState(null)
  const [isChatOpen, setIsChatOpen] = useState(false)
  const [chatMessages, setChatMessages] = useState([])
  const [isDownloading, setIsDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState(null)
  const [isGeneratingFocus, setIsGeneratingFocus] = useState(false)
  const [majorFocusError, setMajorFocusError] = useState(null)
  const [isRetrying, setIsRetrying] = useState(false)
  const [retryError, setRetryError] = useState(null)
  const transcriptRef = useRef(null)
  useLoadingWatchdog(isLoading, setIsLoading, { label: 'results' })

  async function handleDownloadPdf() {
    setIsDownloading(true)
    setDownloadError(null)
    try {
      const blob = await downloadReviewPdf(id)
      const meta = review?.metadata || {}
      const advisor = (meta.advisor_name || '').replace(/[^A-Za-z0-9]+/g, '-').replace(/^-|-$/g, '')
      const prospect = (meta.prospect_name || '').replace(/[^A-Za-z0-9]+/g, '-').replace(/^-|-$/g, '')
      const date = review?.created_at ? review.created_at.slice(0, 10) : ''
      const parts = [advisor, prospect, date].filter(Boolean)
      const filename = `Call-Review-${parts.length ? parts.join('-') : 'Review'}.pdf`
      downloadBlob(blob, filename)
    } catch (err) {
      setDownloadError(err.message || 'Failed to download PDF.')
    } finally {
      setIsDownloading(false)
    }
  }

  async function handleOutcomeChange(newOutcome) {
    const snapshot = review
    const nextOutcome = newOutcome || null
    setOutcomeError(null)
    setIsSavingOutcome(true)
    // Optimistic update so the dropdown reflects the choice immediately.
    setReview((prev) => ({
      ...prev,
      metadata: { ...prev.metadata, call_outcome: nextOutcome },
    }))
    try {
      const updated = await updateReviewOutcome(id, nextOutcome)
      setReview(updated)
    } catch (err) {
      setReview(snapshot)
      setOutcomeError(err.message || 'Failed to update outcome.')
    } finally {
      setIsSavingOutcome(false)
    }
  }

  async function handleGenerateMajorFocus(criterionId) {
    const snapshot = review
    setMajorFocusError(null)
    setIsGeneratingFocus(true)
    try {
      const updated = await updateReviewMajorFocus(id, criterionId)
      setReview(updated)
    } catch (err) {
      setReview(snapshot)
      setMajorFocusError(err.message || 'Failed to generate major focus.')
    } finally {
      setIsGeneratingFocus(false)
    }
  }

  async function handleRetry() {
    setRetryError(null)
    setIsRetrying(true)
    try {
      const updated = await retryReview(id)
      setReview(updated) // status is now 'pending' → the polling effect below kicks in
    } catch (err) {
      setRetryError(err.message || 'Failed to resubmit the review.')
    } finally {
      setIsRetrying(false)
    }
  }

  useEffect(() => {
    let isMounted = true

    async function fetchReview() {
      setIsLoading(true)
      setError(null)
      // Reset chat when navigating to a different review.
      setChatMessages([])
      setIsChatOpen(false)
      try {
        const data = await getReview(id)
        if (isMounted) {
          setReview(data)
        }
      } catch (err) {
        if (isMounted) {
          setError(err.message || 'Failed to load this review.')
        }
      } finally {
        if (isMounted) {
          setIsLoading(false)
        }
      }
    }

    fetchReview()

    return () => {
      isMounted = false
    }
  }, [id])

  // Poll while the review is processing (e.g. right after a retry) so the page
  // updates to the finished result without a manual refresh.
  useEffect(() => {
    if (!review || !IN_PROGRESS_STATUSES.includes(review.status)) return
    let active = true
    const interval = setInterval(async () => {
      try {
        const data = await getReview(id)
        if (!active) return
        setReview(data)
        if (!IN_PROGRESS_STATUSES.includes(data.status)) {
          clearInterval(interval)
        }
      } catch {
        // silent — retries on next tick
      }
    }, 5000)
    return () => {
      active = false
      clearInterval(interval)
    }
  }, [review?.status, id])

  const hasTranscript = Boolean(review?.transcript?.length)

  return (
    <div className="results-page">
      <div className="page-container">
        <div className="results-page__nav">
          <Link to="/history" className="results-page__back-link">
            &#8592; Back to History
          </Link>
        </div>

        {isLoading && (
          <div className="results-page__loading">
            <div className="results-page__spinner" aria-label="Loading review" />
            <p>Loading review...</p>
          </div>
        )}

        {error && (
          <div className="results-page__error" role="alert">
            <span className="results-page__error-icon" aria-hidden="true">&#9888;</span>
            <div>
              <p className="results-page__error-title">Could not load this review</p>
              <p className="results-page__error-message">{error}</p>
            </div>
          </div>
        )}

        {!isLoading && !error && review && (
          <>
            <div className="results-page__header-row">
              <h1 className="results-page__title">Call Review</h1>
              {review.status === 'complete' && review.review?.categories?.length > 0 && (
                <div className="results-page__header-actions">
                  <button
                    className="results-page__download-btn"
                    onClick={handleDownloadPdf}
                    disabled={isDownloading}
                  >
                    {isDownloading ? 'Generating…' : 'Download PDF'}
                  </button>
                  {downloadError && (
                    <p className="results-page__download-error">{downloadError}</p>
                  )}
                </div>
              )}
            </div>
            {review.status === 'failed' ? (
              <div className="results-page__failed" role="alert">
                <span className="results-page__failed-icon" aria-hidden="true">&#9888;</span>
                <div className="results-page__failed-body">
                  <p className="results-page__failed-title">This review failed to process</p>
                  <p className="results-page__failed-message">
                    {review.error_message || 'An unexpected error occurred while processing this call.'}
                  </p>
                  <div className="results-page__failed-actions">
                    <button
                      className="results-page__retry-btn"
                      onClick={handleRetry}
                      disabled={isRetrying}
                    >
                      {isRetrying ? 'Resubmitting…' : 'Retry review'}
                    </button>
                  </div>
                  {retryError && <p className="results-page__retry-error">{retryError}</p>}
                </div>
              </div>
            ) : IN_PROGRESS_STATUSES.includes(review.status) ? (
              <div className="results-page__processing">
                <div className="results-page__spinner" aria-label="Processing review" />
                <p className="results-page__processing-text">
                  {PROCESSING_LABELS[review.status] || 'Processing…'}
                </p>
                <p className="results-page__processing-sub">This page updates automatically.</p>
              </div>
            ) : (
              <ReviewResults
                review={review}
                onOutcomeChange={handleOutcomeChange}
                isSavingOutcome={isSavingOutcome}
                outcomeError={outcomeError}
                transcriptRef={transcriptRef}
                isBds={isBds}
                majorFocus={review.major_focus}
                onGenerateMajorFocus={handleGenerateMajorFocus}
                isGeneratingFocus={isGeneratingFocus}
                majorFocusError={majorFocusError}
              />
            )}
          </>
        )}
      </div>

      {review && (
        <>
          <button
            className={`results-page__fab${isChatOpen ? ' results-page__fab--hidden' : ''}`}
            onClick={() => setIsChatOpen(true)}
            disabled={!hasTranscript}
            title={hasTranscript ? 'Chat about this call' : 'No transcript available'}
            aria-label="Ask AI about this call"
          >
            <RobotIcon />
          </button>
          <ChatPanel
            onSend={(msgs) => chatAboutReview(id, msgs)}
            messages={chatMessages}
            setMessages={setChatMessages}
            isOpen={isChatOpen}
            onClose={() => setIsChatOpen(false)}
            onTimestampClick={(ts) => transcriptRef.current?.jumpTo(ts)}
          />
        </>
      )}
    </div>
  )
}
