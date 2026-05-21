import ScoreCard from './ScoreCard'
import TranscriptPanel from './TranscriptPanel'
import FrameworkPanel from './FrameworkPanel'
import './ReviewResults.css'

function formatDate(isoString) {
  if (!isoString) return '—'
  try {
    return new Date(isoString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    })
  } catch {
    return isoString
  }
}

function getAverageScore(categories) {
  if (!categories || categories.length === 0) return null
  const scores = categories
    .map((c) => c.score)
    .filter((s) => typeof s === 'number')
  if (scores.length === 0) return null
  return Math.round((scores.reduce((a, b) => a + b, 0) / scores.length) * 10) / 10
}

function getAverageScoreClass(score) {
  if (score === null) return ''
  if (score >= 7) return 'review-results__avg-score--high'
  if (score >= 4) return 'review-results__avg-score--mid'
  return 'review-results__avg-score--low'
}

export default function ReviewResults({ review }) {
  const { metadata, review: reviewData, transcript, speaker_map, framework, created_at } = review
  const categories = reviewData?.categories || []
  const frameworkCriteria = framework?.criteria || []
  const summary = reviewData?.summary || ''
  const avgScore = getAverageScore(categories)

  return (
    <div className="review-results">
      {/* Summary card */}
      <div className="review-results__summary-card">
        <div className="review-results__meta">
          <div className="review-results__meta-item">
            <span className="review-results__meta-label">Advisor</span>
            <span className="review-results__meta-value">{metadata?.advisor_name || '—'}</span>
          </div>
          <div className="review-results__meta-item">
            <span className="review-results__meta-label">Firm</span>
            <span className="review-results__meta-value">{metadata?.firm || '—'}</span>
          </div>
          <div className="review-results__meta-item">
            <span className="review-results__meta-label">Prospect</span>
            <span className="review-results__meta-value">{metadata?.prospect_name || '—'}</span>
          </div>
          <div className="review-results__meta-item">
            <span className="review-results__meta-label">Date</span>
            <span className="review-results__meta-value">{formatDate(created_at)}</span>
          </div>
        </div>

        {avgScore !== null && (
          <div className="review-results__score-overview">
            <span className="review-results__score-label">Overall Score</span>
            <span className={`review-results__avg-score ${getAverageScoreClass(avgScore)}`}>
              {avgScore}
              <span className="review-results__avg-score-denom">/10</span>
            </span>
          </div>
        )}

        {summary && (
          <div className="review-results__summary">
            <h2 className="review-results__summary-heading">Summary</h2>
            <p className="review-results__summary-text">{summary}</p>
          </div>
        )}
      </div>

      {/* Score grid */}
      {categories.length > 0 && (
        <section className="review-results__categories">
          <h2 className="review-results__section-heading">Category Scores</h2>
          <div className="review-results__scores-grid">
            {categories.map((category, index) => {
              const criterionTitle = frameworkCriteria[index]?.title
              return (
                <ScoreCard
                  key={category.name}
                  name={criterionTitle || category.name}
                  score={category.score}
                  feedback={category.feedback}
                />
              )
            })}
          </div>
        </section>
      )}

      {/* Framework */}
      {framework && (
        <section className="review-results__framework">
          <FrameworkPanel framework={framework} />
        </section>
      )}

      {/* Transcript */}
      {transcript && transcript.length > 0 && (
        <section className="review-results__transcript">
          <h2 className="review-results__section-heading">Transcript</h2>
          <TranscriptPanel transcript={transcript} speakerMap={speaker_map} />
        </section>
      )}
    </div>
  )
}
