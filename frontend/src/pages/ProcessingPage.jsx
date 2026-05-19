import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import ProgressIndicator from '../components/ProgressIndicator'
import { getReview } from '../services/api'
import './ProcessingPage.css'

const POLL_INTERVAL_MS = 3000

export default function ProcessingPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [error, setError] = useState(null)
  const [reviewStatus, setReviewStatus] = useState('pending')

  useEffect(() => {
    let intervalId = null
    let isMounted = true

    async function checkStatus() {
      try {
        const review = await getReview(id)

        if (!isMounted) return

        setReviewStatus(review.status)

        if (review.status === 'complete') {
          clearInterval(intervalId)
          navigate(`/results/${id}`, { replace: true })
          return
        }

        if (review.status === 'error') {
          clearInterval(intervalId)
          setError(review.error || 'Processing failed. Please try uploading again.')
          return
        }
      } catch (err) {
        if (!isMounted) return
        clearInterval(intervalId)
        setError(err.message || 'Failed to check processing status.')
      }
    }

    // Poll immediately then on interval
    checkStatus()
    intervalId = setInterval(checkStatus, POLL_INTERVAL_MS)

    return () => {
      isMounted = false
      clearInterval(intervalId)
    }
  }, [id, navigate])

  if (error) {
    return (
      <div className="processing-page">
        <div className="processing-page__error-card">
          <span className="processing-page__error-icon" aria-hidden="true">&#9888;</span>
          <h2 className="processing-page__error-title">Processing Failed</h2>
          <p className="processing-page__error-message">{error}</p>
          <button
            className="processing-page__retry-btn"
            onClick={() => navigate('/')}
          >
            Try Another Upload
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="processing-page">
      <ProgressIndicator status={reviewStatus} />
    </div>
  )
}
