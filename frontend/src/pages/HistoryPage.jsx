import { useEffect, useMemo, useRef, useState } from 'react'
import ChatPanel from '../components/ChatPanel'
import ReviewList from '../components/ReviewList'
import SearchableSelect from '../components/SearchableSelect'
import { useAuth } from '../context/AuthContext'
import { useLoadingWatchdog } from '../hooks/useLoadingWatchdog'
import { NO_OUTCOME, OUTCOME_FILTER_OPTIONS } from '../lib/outcomes'
import { chatOverHistory, deleteReview, listFirms, listReviews } from '../services/api'
import './HistoryPage.css'

const IN_PROGRESS_STATUSES = ['pending', 'transcribing', 'reviewing']

function RobotIcon() {
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

export default function HistoryPage() {
  const { user } = useAuth()
  const isBds = user?.role === 'bds_rep'

  const [reviews, setReviews] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState(null)
  // Filters are multi-select: each holds an array of selected values ([] = All).
  const [filterFirm, setFilterFirm] = useState([])
  useLoadingWatchdog(isLoading, setIsLoading, { label: 'history' })
  const [filterAdvisor, setFilterAdvisor] = useState([])
  const [filterTemplate, setFilterTemplate] = useState([])
  const [filterBdsRep, setFilterBdsRep] = useState([])
  const [filterOutcome, setFilterOutcome] = useState([])
  const [searchQuery, setSearchQuery] = useState('')
  const [firms, setFirms] = useState([])
  const pollingRef = useRef(null)

  // History chat state
  const [isHistoryChatOpen, setIsHistoryChatOpen] = useState(false)
  const [historyChatMessages, setHistoryChatMessages] = useState([])

  // For BDS reps: firm options come from the API so all firms appear even with no reviews yet
  const firmOptions = useMemo(() => {
    if (isBds) return firms.map((f) => f.name).sort()
    return []
  }, [isBds, firms])

  const advisorOptions = useMemo(() => {
    const advisors = reviews.map((r) => r.metadata?.advisor_name).filter(Boolean)
    return [...new Set(advisors)].sort()
  }, [reviews])

  // BDS-only filters; derived from loaded reviews like the advisor filter
  const templateOptions = useMemo(() => {
    if (!isBds) return []
    const templates = reviews.map((r) => r.metadata?.template_name).filter(Boolean)
    return [...new Set(templates)].sort()
  }, [isBds, reviews])

  const bdsRepOptions = useMemo(() => {
    if (!isBds) return []
    const reps = reviews.map((r) => r.metadata?.bds_rep_name).filter(Boolean)
    return [...new Set(reps)].sort()
  }, [isBds, reviews])

  // Lift filtering here so we can derive visibleIds for the history chat.
  const visibleReviews = useMemo(() => {
    return reviews.filter((r) => {
      // Each filter is an OR within itself; an empty array means "no filter".
      if (filterFirm.length && !filterFirm.includes(r.metadata?.firm)) return false
      if (filterAdvisor.length && !filterAdvisor.includes(r.metadata?.advisor_name)) return false
      if (filterTemplate.length && !filterTemplate.includes(r.metadata?.template_name)) return false
      if (filterBdsRep.length && !filterBdsRep.includes(r.metadata?.bds_rep_name)) return false
      if (filterOutcome.length) {
        const oc = r.metadata?.call_outcome
        const matches = filterOutcome.some((sel) =>
          sel === NO_OUTCOME ? !oc : oc === sel
        )
        if (!matches) return false
      }
      if (searchQuery) {
        const q = searchQuery.toLowerCase()
        const searchable = [
          r.metadata?.advisor_name,
          r.metadata?.firm,
          r.metadata?.prospect_name,
          r.metadata?.call_outcome,
          r.metadata?.template_name,
          r.metadata?.bds_rep_name,
        ].filter(Boolean).join(' ').toLowerCase()
        if (!searchable.includes(q)) return false
      }
      return true
    })
  }, [reviews, filterFirm, filterAdvisor, filterTemplate, filterBdsRep, filterOutcome, searchQuery])

  const visibleIds = useMemo(() => visibleReviews.map((r) => r.id), [visibleReviews])

  async function handleDelete(id) {
    await deleteReview(id)
    setReviews((prev) => prev.filter((r) => r.id !== id))
  }

  useEffect(() => {
    let isMounted = true

    function startPolling() {
      if (pollingRef.current) return
      pollingRef.current = setInterval(async () => {
        if (!isMounted) return
        try {
          const data = await listReviews()
          if (!isMounted) return
          setReviews(data)
          if (!data.some((r) => IN_PROGRESS_STATUSES.includes(r.status))) {
            clearInterval(pollingRef.current)
            pollingRef.current = null
          }
        } catch {
          // silent — retries on next tick
        }
      }, 5000)
    }

    async function fetchAll() {
      setIsLoading(true)
      setError(null)
      try {
        const requests = [listReviews()]
        if (isBds) requests.push(listFirms())
        const [data, firmData] = await Promise.all(requests)
        if (!isMounted) return
        setReviews(data)
        if (firmData) setFirms(firmData)
        if (data.some((r) => IN_PROGRESS_STATUSES.includes(r.status))) {
          startPolling()
        }
      } catch (err) {
        if (isMounted) setError(err.message || 'Failed to load reviews.')
      } finally {
        if (isMounted) setIsLoading(false)
      }
    }

    fetchAll()

    return () => {
      isMounted = false
      if (pollingRef.current) {
        clearInterval(pollingRef.current)
        pollingRef.current = null
      }
    }
  }, [isBds])

  const chatSubtitle = `Asking about ${visibleIds.length} call${visibleIds.length === 1 ? '' : 's'} matching your filters`

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
            <p>Loading reviews…</p>
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
              <div className="history-page__filter history-page__filter--select">
                <label htmlFor="advisor-filter" className="history-page__filter-label">
                  Advisor
                </label>
                <SearchableSelect
                  id="advisor-filter"
                  size="sm"
                  multiple
                  options={[
                    { value: '', label: 'All' },
                    ...advisorOptions.map((a) => ({ value: a, label: a })),
                  ]}
                  value={filterAdvisor}
                  onChange={setFilterAdvisor}
                  placeholder="All"
                />
              </div>
            )}

            {isBds && firmOptions.length > 0 && (
              <div className="history-page__filter history-page__filter--select">
                <label htmlFor="firm-filter" className="history-page__filter-label">
                  Firm
                </label>
                <SearchableSelect
                  id="firm-filter"
                  size="sm"
                  multiple
                  options={[
                    { value: '', label: 'All' },
                    ...firmOptions.map((f) => ({ value: f, label: f })),
                  ]}
                  value={filterFirm}
                  onChange={setFilterFirm}
                  placeholder="All"
                />
              </div>
            )}

            {isBds && templateOptions.length > 0 && (
              <div className="history-page__filter history-page__filter--select">
                <label htmlFor="template-filter" className="history-page__filter-label">
                  Template
                </label>
                <SearchableSelect
                  id="template-filter"
                  size="sm"
                  multiple
                  options={[
                    { value: '', label: 'All' },
                    ...templateOptions.map((t) => ({ value: t, label: t })),
                  ]}
                  value={filterTemplate}
                  onChange={setFilterTemplate}
                  placeholder="All"
                />
              </div>
            )}

            {isBds && bdsRepOptions.length > 0 && (
              <div className="history-page__filter history-page__filter--select">
                <label htmlFor="bds-rep-filter" className="history-page__filter-label">
                  BDS Rep
                </label>
                <SearchableSelect
                  id="bds-rep-filter"
                  size="sm"
                  multiple
                  options={[
                    { value: '', label: 'All' },
                    ...bdsRepOptions.map((r) => ({ value: r, label: r })),
                  ]}
                  value={filterBdsRep}
                  onChange={setFilterBdsRep}
                  placeholder="All"
                />
              </div>
            )}

            <div className="history-page__filter history-page__filter--select">
              <label htmlFor="outcome-filter" className="history-page__filter-label">
                Outcome
              </label>
              <SearchableSelect
                id="outcome-filter"
                size="sm"
                multiple
                options={OUTCOME_FILTER_OPTIONS}
                value={filterOutcome}
                onChange={setFilterOutcome}
                placeholder="All"
              />
            </div>
          </div>
        )}

        {!isLoading && !error && (
          <ReviewList
            reviews={visibleReviews}
            hasAnyReviews={reviews.length > 0}
            onDelete={handleDelete}
          />
        )}
      </div>

      {!isLoading && !error && (
        <>
          <button
            className={`history-page__fab${isHistoryChatOpen ? ' history-page__fab--hidden' : ''}`}
            onClick={() => setIsHistoryChatOpen(true)}
            disabled={visibleIds.length === 0}
            title={visibleIds.length > 0 ? 'Ask AI about these calls' : 'No calls to analyze'}
            aria-label="Ask AI about visible calls"
          >
            <RobotIcon />
          </button>
          <ChatPanel
            title="History Analysis"
            subtitle={chatSubtitle}
            onSend={(msgs) => chatOverHistory(visibleIds, msgs)}
            messages={historyChatMessages}
            setMessages={setHistoryChatMessages}
            isOpen={isHistoryChatOpen}
            onClose={() => setIsHistoryChatOpen(false)}
            emptyStateText="Ask anything about the calls matching your current filters."
            inputPlaceholder="Ask about patterns across these calls…"
          />
        </>
      )}
    </div>
  )
}
