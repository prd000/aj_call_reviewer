import ScoreCard from './ScoreCard'
import TranscriptPanel from './TranscriptPanel'
import FrameworkPanel from './FrameworkPanel'
import SearchableSelect from './SearchableSelect'
import { OUTCOME_OPTIONS } from '../lib/outcomes'
import './ReviewResults.css'

const OUTCOME_SELECT_OPTIONS = [{ value: '', label: 'Not set' }, ...OUTCOME_OPTIONS]

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

function getOverallScore(categories) {
  if (!categories || categories.length === 0) return null
  const scored = categories.filter((c) => typeof c.score === 'number')
  if (scored.length === 0) return null
  const totalScore = scored.reduce((a, c) => a + c.score, 0)
  const totalMax = scored.reduce((a, c) => a + (c.max_score || 10), 0)
  return { score: Math.round((totalScore / totalMax) * 100) / 10, maxScore: 10 }
}

function getOverallScoreClass(ratio) {
  if (ratio === null) return ''
  if (ratio >= 0.7) return 'review-results__avg-score--high'
  if (ratio >= 0.4) return 'review-results__avg-score--mid'
  return 'review-results__avg-score--low'
}

export default function ReviewResults({ review, onOutcomeChange, isSavingOutcome, outcomeError }) {
  const { metadata, review: reviewData, transcript, speaker_map, framework, created_at } = review
  const categories = reviewData?.categories || []
  const frameworkCriteria = framework?.criteria || []
  const summary = reviewData?.summary || ''
  const overallScore = getOverallScore(categories)

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
          <div className="review-results__meta-item">
            <span className="review-results__meta-label">Outcome</span>
            <SearchableSelect
              id="review-outcome"
              size="md"
              options={OUTCOME_SELECT_OPTIONS}
              value={metadata?.call_outcome || ''}
              onChange={onOutcomeChange}
              placeholder="Not set"
              disabled={isSavingOutcome}
            />
            {outcomeError && (
              <span className="review-results__meta-error">{outcomeError}</span>
            )}
          </div>
        </div>

        {overallScore !== null && (
          <div className="review-results__score-overview">
            <span className="review-results__score-label">Overall Score</span>
            <span className={`review-results__avg-score ${getOverallScoreClass(overallScore.score / overallScore.maxScore)}`}>
              {overallScore.score}
              <span className="review-results__avg-score-denom">/{overallScore.maxScore}</span>
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
                  maxScore={category.max_score || 10}
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
