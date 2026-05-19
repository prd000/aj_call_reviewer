import './ScoreCard.css'

function getScoreColor(score) {
  if (score >= 7) return 'var(--color-success)'
  if (score >= 4) return 'var(--color-primary)'
  return 'var(--color-danger)'
}

function getScoreClass(score) {
  if (score >= 7) return 'score-card__score--high'
  if (score >= 4) return 'score-card__score--mid'
  return 'score-card__score--low'
}

export default function ScoreCard({ name, score, feedback }) {
  const color = getScoreColor(score)
  const scoreClass = getScoreClass(score)
  const barPercent = (score / 10) * 100

  return (
    <div className="score-card">
      <div className="score-card__header">
        <h3 className="score-card__name">{name}</h3>
        <span className={`score-card__score ${scoreClass}`}>
          {score}<span className="score-card__score-denom">/10</span>
        </span>
      </div>
      <div className="score-card__bar-track">
        <div
          className="score-card__bar-fill"
          style={{ width: `${barPercent}%`, backgroundColor: color }}
          role="progressbar"
          aria-valuenow={score}
          aria-valuemin={0}
          aria-valuemax={10}
          aria-label={`${name} score: ${score} out of 10`}
        />
      </div>
      <p className="score-card__feedback">{feedback}</p>
    </div>
  )
}
