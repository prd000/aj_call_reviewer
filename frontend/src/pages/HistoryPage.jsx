import { useEffect, useMemo, useState } from 'react'
import ReviewList from '../components/ReviewList'
import { deleteReview, listReviews } from '../services/api'
import './HistoryPage.css'

export default function HistoryPage() {
  const [reviews, setReviews] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState(null)
  const [filterRep, setFilterRep] = useState('')

  const repOptions = useMemo(() => {
    const reps = reviews
      .map((r) => r.metadata?.bds_rep)
      .filter(Boolean)
    return [...new Set(reps)].sort()
  }, [reviews])

  async function handleDelete(id) {
    await deleteReview(id)
    setReviews((prev) => prev.filter((r) => r.id !== id))
  }

  useEffect(() => {
    let isMounted = true

    async function fetchReviews() {
      setIsLoading(true)
      setError(null)
      try {
        const data = await listReviews()
        if (isMounted) {
          setReviews(data)
        }
      } catch (err) {
        if (isMounted) {
          setError(err.message || 'Failed to load reviews.')
        }
      } finally {
        if (isMounted) {
          setIsLoading(false)
        }
      }
    }

    fetchReviews()

    return () => {
      isMounted = false
    }
  }, [])

  return (
    <div className="history-page">
      <div className="page-container">
        <div className="history-page__header">
          <h1 className="history-page__title">Past Reviews</h1>
          <p className="history-page__subtitle">
            {!isLoading && !error && reviews.length > 0
              ? `${reviews.length} review${reviews.length === 1 ? '' : 's'} on file`
              : 'Your completed call reviews appear here.'}
          </p>
        </div>

        {isLoading && (
          <div className="history-page__loading">
            <div className="history-page__spinner" aria-label="Loading reviews" />
            <p>Loading reviews...</p>
          </div>
        )}

        {error && (
          <div className="history-page__error" role="alert">
            <span className="history-page__error-icon" aria-hidden="true">&#9888;</span>
            {error}
          </div>
        )}

        {!isLoading && !error && repOptions.length > 0 && (
          <div className="history-page__filter">
            <label htmlFor="rep-filter" className="history-page__filter-label">
              BDS Rep
            </label>
            <select
              id="rep-filter"
              className="history-page__filter-select"
              value={filterRep}
              onChange={(e) => setFilterRep(e.target.value)}
            >
              <option value="">All</option>
              {repOptions.map((rep) => (
                <option key={rep} value={rep}>{rep}</option>
              ))}
            </select>
          </div>
        )}

        {!isLoading && !error && (
          <ReviewList reviews={reviews} filterRep={filterRep} onDelete={handleDelete} />
        )}
      </div>
    </div>
  )
}
