import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import ReviewResults from '../components/ReviewResults'
import { useLoadingWatchdog } from '../hooks/useLoadingWatchdog'
import { getReview, updateReviewOutcome } from '../services/api'
import './ResultsPage.css'

export default function ResultsPage() {
  const { id } = useParams()
  const [review, setReview] = useState(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState(null)
  const [isSavingOutcome, setIsSavingOutcome] = useState(false)
  const [outcomeError, setOutcomeError] = useState(null)
  useLoadingWatchdog(isLoading, setIsLoading, { label: 'results' })

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

  useEffect(() => {
    let isMounted = true

    async function fetchReview() {
      setIsLoading(true)
      setError(null)
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
            <div className="results-page__header">
              <h1 className="results-page__title">Call Review</h1>
            </div>
            <ReviewResults
              review={review}
              onOutcomeChange={handleOutcomeChange}
              isSavingOutcome={isSavingOutcome}
              outcomeError={outcomeError}
            />
          </>
        )}
      </div>
    </div>
  )
}
