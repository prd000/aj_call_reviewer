import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { outcomeColorClass } from '../lib/outcomes'
import './ReviewList.css'

const IN_PROGRESS_STATUSES = ['pending', 'transcribing', 'reviewing']
const STATUS_LABELS = {
  pending: 'Queued',
  transcribing: 'Transcribing…',
  reviewing: 'Reviewing…',
}

function formatDate(isoString) {
  if (!isoString) return '—'
  try {
    return new Date(isoString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  } catch {
    return isoString
  }
}

function ScoreBadge({ score, maxScore }) {
  if (score === null || score === undefined) {
    return <span className="review-list-item__badge review-list-item__badge--pending">Pending</span>
  }
  const effectiveMax = maxScore || 10
  const ratio = score / effectiveMax
  let cls = 'review-list-item__badge'
  if (ratio >= 0.7) cls += ' review-list-item__badge--high'
  else if (ratio >= 0.4) cls += ' review-list-item__badge--mid'
  else cls += ' review-list-item__badge--low'

  return <span className={cls}>{score}/{effectiveMax}</span>
}

function OutcomePill({ outcome }) {
  if (!outcome) return null
  const color = outcomeColorClass(outcome)
  return (
    <span className={`review-list-item__outcome review-list-item__outcome--${color}`}>
      {outcome}
    </span>
  )
}

function TrashIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <path d="M1.75 3.5h10.5M5.25 3.5V2.333a.583.583 0 0 1 .583-.583h2.334a.583.583 0 0 1 .583.583V3.5M11.083 3.5l-.583 7.583a.583.583 0 0 1-.583.584H4.083a.583.583 0 0 1-.583-.584L2.917 3.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  )
}

function ReviewListItem({ review, onClick, onDelete }) {
  const { metadata, created_at, overall_score, overall_max_score, status } = review
  const [showConfirm, setShowConfirm] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)

  const isInProgress = IN_PROGRESS_STATUSES.includes(status)
  const isFailed = status === 'failed'
  const isInteractive = !isInProgress && !isFailed

  function handleDeleteClick(e) {
    e.stopPropagation()
    setShowConfirm(true)
  }

  function handleCancel(e) {
    e.stopPropagation()
    setShowConfirm(false)
  }

  async function handleConfirmDelete(e) {
    e.stopPropagation()
    setIsDeleting(true)
    try {
      await onDelete(review.id)
    } catch {
      setIsDeleting(false)
      setShowConfirm(false)
    }
  }

  let itemClass = 'review-list-item'
  if (isInProgress) itemClass += ' review-list-item--in-progress'
  if (isFailed) itemClass += ' review-list-item--failed'
  if (showConfirm) itemClass += ' review-list-item--confirming'

  return (
    <div
      className={itemClass}
      onClick={isInteractive && !showConfirm ? onClick : undefined}
      role={isInteractive ? 'button' : undefined}
      tabIndex={isInteractive ? 0 : undefined}
      onKeyDown={(e) => {
        if (isInteractive && !showConfirm && (e.key === 'Enter' || e.key === ' ')) {
          e.preventDefault()
          onClick?.()
        }
      }}
      aria-label={`${isInteractive ? 'View review' : 'Review'} for ${metadata?.advisor_name} — ${metadata?.prospect_name}`}
    >
      <div className="review-list-item__body">
        <div className="review-list-item__primary">
          <span className="review-list-item__advisor">{metadata?.advisor_name || 'Unknown Advisor'}</span>
          <span className="review-list-item__separator">·</span>
          <span className="review-list-item__firm">{metadata?.firm || '—'}</span>
        </div>
        <div className="review-list-item__secondary">
          <span className="review-list-item__prospect">Prospect: {metadata?.prospect_name || '—'}</span>
          <span className="review-list-item__date">{formatDate(created_at)}</span>
          {metadata?.uploaded_by_name && (
            <span className="review-list-item__uploader">Uploaded by {metadata.uploaded_by_name}</span>
          )}
          <OutcomePill outcome={metadata?.call_outcome} />
        </div>
      </div>

      {showConfirm ? (
        <div className="review-list-item__confirm-row" onClick={(e) => e.stopPropagation()}>
          <span className="review-list-item__confirm-text">Delete this review?</span>
          <button
            className="review-list-item__btn review-list-item__btn--danger"
            onClick={handleConfirmDelete}
            disabled={isDeleting}
          >
            {isDeleting ? 'Deleting…' : 'Delete'}
          </button>
          <button
            className="review-list-item__btn review-list-item__btn--ghost"
            onClick={handleCancel}
            disabled={isDeleting}
          >
            Cancel
          </button>
        </div>
      ) : isInProgress ? (
        <div className="review-list-item__right">
          <div className="review-list-item__spinner" aria-hidden="true" />
          <span className="review-list-item__status-label">{STATUS_LABELS[status] || status}</span>
        </div>
      ) : isFailed ? (
        <div className="review-list-item__right">
          <span className="review-list-item__badge review-list-item__badge--failed">Failed</span>
          <button
            className="review-list-item__delete-btn review-list-item__delete-btn--visible"
            onClick={handleDeleteClick}
            aria-label={`Delete review for ${metadata?.advisor_name}`}
          >
            <TrashIcon />
          </button>
        </div>
      ) : (
        <div className="review-list-item__right">
          <ScoreBadge score={overall_score} maxScore={overall_max_score} />
          <button
            className="review-list-item__delete-btn"
            onClick={handleDeleteClick}
            aria-label={`Delete review for ${metadata?.advisor_name}`}
          >
            <TrashIcon />
          </button>
          <span className="review-list-item__arrow" aria-hidden="true">&#8250;</span>
        </div>
      )}
    </div>
  )
}

// reviews: pre-filtered list from HistoryPage (sorted here)
// hasAnyReviews: whether any reviews exist in the DB at all (for the empty-state copy)
export default function ReviewList({ reviews, hasAnyReviews, onDelete }) {
  const navigate = useNavigate()

  const sorted = [...(reviews || [])].sort(
    (a, b) => new Date(b.created_at) - new Date(a.created_at)
  )

  if (!hasAnyReviews) {
    return (
      <div className="review-list__empty">
        <p className="review-list__empty-title">No reviews yet</p>
        <p className="review-list__empty-text">
          Upload a call recording to generate your first review.
        </p>
      </div>
    )
  }

  if (sorted.length === 0) {
    return (
      <div className="review-list__empty">
        <p className="review-list__empty-title">No matching reviews</p>
        <p className="review-list__empty-text">
          Try adjusting your filters or search query.
        </p>
      </div>
    )
  }

  return (
    <div className="review-list">
      {sorted.map((review) => (
        <ReviewListItem
          key={review.id}
          review={review}
          onClick={review.status === 'complete' ? () => navigate(`/results/${review.id}`) : undefined}
          onDelete={onDelete}
        />
      ))}
    </div>
  )
}
