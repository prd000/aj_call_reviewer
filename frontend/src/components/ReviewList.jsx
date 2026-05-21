import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import './ReviewList.css'

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

function ScoreBadge({ score }) {
  if (score === null || score === undefined) {
    return <span className="review-list-item__badge review-list-item__badge--pending">Pending</span>
  }
  let cls = 'review-list-item__badge'
  if (score >= 7) cls += ' review-list-item__badge--high'
  else if (score >= 4) cls += ' review-list-item__badge--mid'
  else cls += ' review-list-item__badge--low'

  return <span className={cls}>{score}/10</span>
}

function TrashIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <path d="M1.75 3.5h10.5M5.25 3.5V2.333a.583.583 0 0 1 .583-.583h2.334a.583.583 0 0 1 .583.583V3.5M11.083 3.5l-.583 7.583a.583.583 0 0 1-.583.584H4.083a.583.583 0 0 1-.583-.584L2.917 3.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  )
}

function ReviewListItem({ review, onClick, onDelete }) {
  const { metadata, created_at, overall_score, status } = review
  const [showConfirm, setShowConfirm] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)

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

  return (
    <div
      className={`review-list-item${showConfirm ? ' review-list-item--confirming' : ''}`}
      onClick={showConfirm ? undefined : onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (!showConfirm && (e.key === 'Enter' || e.key === ' ')) {
          e.preventDefault()
          onClick()
        }
      }}
      aria-label={`View review for ${metadata?.advisor_name} — ${metadata?.prospect_name}`}
    >
      <div className="review-list-item__body">
        <div className="review-list-item__primary">
          <span className="review-list-item__advisor">{metadata?.advisor_name || 'Unknown Advisor'}</span>
          <span className="review-list-item__separator">·</span>
          <span className="review-list-item__firm">{metadata?.firm || '—'}</span>
        </div>
        <div className="review-list-item__secondary">
          <span className="review-list-item__prospect">Prospect: {metadata?.prospect_name || '—'}</span>
          {metadata?.bds_rep && (
            <span className="review-list-item__bds-rep">BDS: {metadata.bds_rep}</span>
          )}
          <span className="review-list-item__date">{formatDate(created_at)}</span>
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
      ) : (
        <div className="review-list-item__right">
          {status === 'processing' ? (
            <span className="review-list-item__badge review-list-item__badge--processing">Processing</span>
          ) : status === 'error' ? (
            <span className="review-list-item__badge review-list-item__badge--error">Error</span>
          ) : (
            <ScoreBadge score={overall_score} />
          )}
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

export default function ReviewList({ reviews, filterRep, filterFirm, filterAdvisor, searchQuery, onDelete }) {
  const navigate = useNavigate()

  const filtered = reviews.filter((r) => {
    if (filterRep && r.metadata?.bds_rep !== filterRep) return false
    if (filterFirm && r.metadata?.firm !== filterFirm) return false
    if (filterAdvisor && r.metadata?.advisor_name !== filterAdvisor) return false
    if (searchQuery) {
      const q = searchQuery.toLowerCase()
      const searchable = [
        r.metadata?.advisor_name,
        r.metadata?.firm,
        r.metadata?.prospect_name,
        r.metadata?.bds_rep,
      ].filter(Boolean).join(' ').toLowerCase()
      if (!searchable.includes(q)) return false
    }
    return true
  })

  const sorted = [...filtered].sort(
    (a, b) => new Date(b.created_at) - new Date(a.created_at)
  )

  if (!reviews || reviews.length === 0) {
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
          onClick={() => navigate(`/results/${review.id}`)}
          onDelete={onDelete}
        />
      ))}
    </div>
  )
}
