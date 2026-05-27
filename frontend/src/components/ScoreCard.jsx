import './ScoreCard.css'

function getScoreColor(ratio) {
  if (ratio >= 0.7) return 'var(--color-success)'
  if (ratio >= 0.4) return 'var(--color-primary)'
  return 'var(--color-danger)'
}

function getScoreClass(ratio) {
  if (ratio >= 0.7) return 'score-card__score--high'
  if (ratio >= 0.4) return 'score-card__score--mid'
  return 'score-card__score--low'
}

export default function ScoreCard({ name, score, feedback, maxScore = 10 }) {
  const ratio = score / maxScore
  const color = getScoreColor(ratio)
  const scoreClass = getScoreClass(ratio)
  const barPercent = ratio * 100

  return (
    <div className="score-card">
      <div className="score-card__header">
        <h3 className="score-card__name">{name}</h3>
        <span className={`score-card__score ${scoreClass}`}>
          {score}<span className="score-card__score-denom">/{maxScore}</span>
        </span>
      </div>
      <div className="score-card__bar-track">
        <div
          className="score-card__bar-fill"
          style={{ width: `${barPercent}%`, backgroundColor: color }}
          role="progressbar"
          aria-valuenow={score}
          aria-valuemin={0}
          aria-valuemax={maxScore}
          aria-label={`${name} score: ${score} out of ${maxScore}`}
        />
      </div>
      <p className="score-card__feedback">{feedback}</p>
    </div>
  )
}
