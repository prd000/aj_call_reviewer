import { useEffect, useMemo, useState } from 'react'
import ReviewList from '../components/ReviewList'
import { deleteReview, listReviews } from '../services/api'
import './HistoryPage.css'

export default function HistoryPage() {
  const [reviews, setReviews] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState(null)
  const [filterRep, setFilterRep] = useState('')
  const [filterFirm, setFilterFirm] = useState('')
  const [filterAdvisor, setFilterAdvisor] = useState('')
  const [searchQuery, setSearchQuery] = useState('')

  const repOptions = useMemo(() => {
    const reps = reviews.map((r) => r.metadata?.bds_rep).filter(Boolean)
    return [...new Set(reps)].sort()
  }, [reviews])

  const firmOptions = useMemo(() => {
    const firms = reviews.map((r) => r.metadata?.firm).filter(Boolean)
    return [...new Set(firms)].sort()
  }, [reviews])

  const advisorOptions = useMemo(() => {
    const advisors = reviews.map((r) => r.metadata?.advisor_name).filter(Boolean)
    return [...new Set(advisors)].sort()
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

        {!isLoading && !error && reviews.length > 0 && (
          <div className="history-page__filters">
            <div className="history-page__filter">
              <label htmlFor="search-filter" className="history-page__filter-label">
                Search
              </label>
              <input
                id="search-filter"
                type="text"
                className="history-page__search"
                placeholder="Advisor, firm, prospect…"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>

            {advisorOptions.length > 0 && (
              <div className="history-page__filter">
                <label htmlFor="advisor-filter" className="history-page__filter-label">
                  Advisor
                </label>
                <select
                  id="advisor-filter"
                  className="history-page__filter-select"
                  value={filterAdvisor}
                  onChange={(e) => setFilterAdvisor(e.target.value)}
                >
                  <option value="">All</option>
                  {advisorOptions.map((a) => (
                    <option key={a} value={a}>{a}</option>
                  ))}
                </select>
              </div>
            )}

            {firmOptions.length > 0 && (
              <div className="history-page__filter">
                <label htmlFor="firm-filter" className="history-page__filter-label">
                  Firm
                </label>
                <select
                  id="firm-filter"
                  className="history-page__filter-select"
                  value={filterFirm}
                  onChange={(e) => setFilterFirm(e.target.value)}
                >
                  <option value="">All</option>
                  {firmOptions.map((f) => (
                    <option key={f} value={f}>{f}</option>
                  ))}
                </select>
              </div>
            )}

            {repOptions.length > 0 && (
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
          </div>
        )}

        {!isLoading && !error && (
          <ReviewList
            reviews={reviews}
            filterRep={filterRep}
            filterFirm={filterFirm}
            filterAdvisor={filterAdvisor}
            searchQuery={searchQuery}
            onDelete={handleDelete}
          />
        )}
      </div>
    </div>
  )
}
