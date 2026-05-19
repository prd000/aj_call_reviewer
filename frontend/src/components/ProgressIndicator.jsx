import './ProgressIndicator.css'

const STEPS = [
  { id: 'upload', label: 'Uploading file' },
  { id: 'transcribe', label: 'Transcribing audio' },
  { id: 'review', label: 'Generating review' },
]

// Number of steps completed (not active) for each backend status
const STATUS_COMPLETED_COUNT = {
  pending: 1,
  transcribing: 1,
  reviewing: 2,
  complete: 3,
}

function getStepState(stepIndex, completedCount) {
  if (stepIndex < completedCount) return 'complete'
  if (stepIndex === completedCount) return 'active'
  return 'pending'
}

export default function ProgressIndicator({ status = 'pending' }) {
  const completedCount = STATUS_COMPLETED_COUNT[status] ?? 1

  return (
    <div className="progress-indicator">
      <div className="progress-indicator__card">
        <div className="progress-indicator__spinner" aria-hidden="true">
          <div className="progress-indicator__spinner-ring" />
        </div>
        <h2 className="progress-indicator__heading">Analyzing your call...</h2>
        <p className="progress-indicator__subtext">
          This may take a minute. Please keep this window open.
        </p>
        <ul className="progress-indicator__steps">
          {STEPS.map((step, index) => {
            const state = getStepState(index, completedCount)
            return (
              <li
                key={step.id}
                className={`progress-indicator__step progress-indicator__step--${state}`}
              >
                <span className="progress-indicator__step-bullet" aria-hidden="true">
                  {state === 'complete' ? '✓' : state === 'active' ? '●' : '○'}
                </span>
                <span className="progress-indicator__step-label">{step.label}</span>
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}
