import { useState } from 'react'
import './CriteriaCard.css'

export default function CriteriaCard({ criterion, onUpdate, onDelete, onSave, onCancel }) {
  const isAddMode = criterion === null
  const [isEditing, setIsEditing] = useState(isAddMode)
  const [title, setTitle] = useState(criterion?.title ?? '')
  const [description, setDescription] = useState(criterion?.description ?? '')
  const [successCondition, setSuccessCondition] = useState(criterion?.success_condition ?? '')
  const [maxScore, setMaxScore] = useState(criterion?.max_score ?? 10)

  function handleSave() {
    const trimmedTitle = title.trim()
    const trimmedDesc = description.trim()
    const trimmedCond = successCondition.trim()
    const parsedMax = Math.min(10, Math.max(1, parseInt(maxScore, 10) || 10))
    if (isAddMode) {
      onSave({
        id: crypto.randomUUID(),
        title: trimmedTitle,
        description: trimmedDesc,
        success_condition: trimmedCond,
        max_score: parsedMax,
      })
    } else {
      onUpdate({ ...criterion, title: trimmedTitle, description: trimmedDesc, success_condition: trimmedCond, max_score: parsedMax })
      setIsEditing(false)
    }
  }

  function handleCancel() {
    if (isAddMode) {
      onCancel()
    } else {
      setTitle(criterion.title ?? '')
      setDescription(criterion.description)
      setSuccessCondition(criterion.success_condition)
      setMaxScore(criterion.max_score ?? 10)
      setIsEditing(false)
    }
  }

  const canSave = title.trim().length > 0 && description.trim().length > 0 && successCondition.trim().length > 0

  if (isEditing) {
    return (
      <div className="criteria-card criteria-card--editing">
        <div className="criteria-card__field">
          <label className="criteria-card__label">Title</label>
          <input
            className="criteria-card__input"
            value={title}
            onChange={e => setTitle(e.target.value)}
            placeholder="Short name for this criterion..."
          />
        </div>
        <div className="criteria-card__field">
          <label className="criteria-card__label">Criteria</label>
          <textarea
            className="criteria-card__textarea"
            value={description}
            onChange={e => setDescription(e.target.value)}
            placeholder="Describe what the advisor should do..."
            rows={3}
          />
        </div>
        <div className="criteria-card__field">
          <label className="criteria-card__label">Success when</label>
          <textarea
            className="criteria-card__textarea"
            value={successCondition}
            onChange={e => setSuccessCondition(e.target.value)}
            placeholder="Describe what success looks like and how to score it..."
            rows={3}
          />
        </div>
        <div className="criteria-card__field">
          <label className="criteria-card__label">Max Score</label>
          <input
            className="criteria-card__input criteria-card__input--max-score"
            type="number"
            min={1}
            max={10}
            value={maxScore}
            onChange={e => setMaxScore(e.target.value)}
          />
        </div>
        <div className="criteria-card__edit-actions">
          <button
            className="criteria-card__btn criteria-card__btn--primary"
            onClick={handleSave}
            disabled={!canSave}
          >
            Save
          </button>
          <button
            className="criteria-card__btn criteria-card__btn--secondary"
            onClick={handleCancel}
          >
            Cancel
          </button>
        </div>
      </div>
    )
  }

  return (
    <div
      className="criteria-card"
      onClick={() => setIsEditing(true)}
      role="button"
      tabIndex={0}
      onKeyDown={e => e.key === 'Enter' && setIsEditing(true)}
    >
      <div className="criteria-card__content">
        {criterion.title && (
          <p className="criteria-card__title">{criterion.title}</p>
        )}
        <p className="criteria-card__description">{criterion.description}</p>
        <p className="criteria-card__success-condition">
          <span className="criteria-card__success-label">Success when: </span>
          {criterion.success_condition}
        </p>
        <p className="criteria-card__max-score-label">Out of {criterion.max_score || 10}</p>
      </div>
      <button
        className="criteria-card__delete-btn"
        onClick={e => { e.stopPropagation(); onDelete(criterion.id) }}
        title="Delete criterion"
        aria-label="Delete criterion"
      >
        ✕
      </button>
    </div>
  )
}
