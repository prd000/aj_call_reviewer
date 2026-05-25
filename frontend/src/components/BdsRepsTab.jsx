import { useEffect, useState } from 'react'
import { createUser, deleteUser, listBdsReps, setUserActive } from '../services/api'
import { useLoadingWatchdog } from '../hooks/useLoadingWatchdog'
import './BdsRepsTab.css'

function BdsRepRow({ rep, onToggleActive, onDelete }) {
  const [showConfirm, setShowConfirm] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)

  async function handleDelete() {
    setIsDeleting(true)
    try {
      await onDelete()
    } finally {
      setIsDeleting(false)
      setShowConfirm(false)
    }
  }

  return (
    <div className="bds-reps-tab__row">
      <div className="bds-reps-tab__row-info">
        <span className="bds-reps-tab__name">{rep.name}</span>
        <span className="bds-reps-tab__email">{rep.email}</span>
        <span
          className={`bds-reps-tab__status${rep.is_active ? ' bds-reps-tab__status--active' : ' bds-reps-tab__status--inactive'}`}
        >
          {rep.is_active ? 'Active' : 'Inactive'}
        </span>
      </div>
      <div className="bds-reps-tab__actions">
        <button className="mgmt-btn mgmt-btn--ghost" onClick={onToggleActive}>
          {rep.is_active ? 'Deactivate' : 'Reactivate'}
        </button>
        {showConfirm ? (
          <>
            <button
              className="mgmt-btn mgmt-btn--danger"
              onClick={handleDelete}
              disabled={isDeleting}
            >
              {isDeleting ? 'Deleting…' : 'Confirm'}
            </button>
            <button
              className="mgmt-btn mgmt-btn--ghost"
              onClick={() => setShowConfirm(false)}
              disabled={isDeleting}
            >
              Cancel
            </button>
          </>
        ) : (
          <button
            className="mgmt-btn mgmt-btn--danger-outline"
            onClick={() => setShowConfirm(true)}
          >
            Delete
          </button>
        )}
      </div>
    </div>
  )
}

export default function BdsRepsTab() {
  const [reps, setReps] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [showAddForm, setShowAddForm] = useState(false)
  useLoadingWatchdog(isLoading, setIsLoading, { label: 'bds-reps' })
  const [newName, setNewName] = useState('')
  const [newEmail, setNewEmail] = useState('')
  const [addError, setAddError] = useState(null)
  const [isAdding, setIsAdding] = useState(false)

  useEffect(() => {
    listBdsReps()
      .then(setReps)
      .catch(() => {})
      .finally(() => setIsLoading(false))
  }, [])

  async function handleAdd() {
    if (!newName.trim() || !newEmail.trim()) {
      setAddError('Name and email are required.')
      return
    }
    setIsAdding(true)
    setAddError(null)
    try {
      const profile = await createUser({
        email: newEmail.trim(),
        name: newName.trim(),
        role: 'bds_rep',
      })
      setReps((prev) => [...prev, profile].sort((a, b) => a.name.localeCompare(b.name)))
      setNewName('')
      setNewEmail('')
      setShowAddForm(false)
    } catch (err) {
      setAddError(err.message || 'Failed to create BDS rep.')
    } finally {
      setIsAdding(false)
    }
  }

  async function handleToggleActive(userId, currentlyActive) {
    try {
      await setUserActive(userId, !currentlyActive)
      setReps((prev) =>
        prev.map((r) => (r.id === userId ? { ...r, is_active: !currentlyActive } : r))
      )
    } catch {}
  }

  async function handleDelete(userId) {
    try {
      await deleteUser(userId)
      setReps((prev) => prev.filter((r) => r.id !== userId))
    } catch {}
  }

  if (isLoading) return <div className="bds-reps-tab__loading">Loading BDS reps…</div>

  return (
    <div className="bds-reps-tab">
      <div className="bds-reps-tab__toolbar">
        <button
          className="mgmt-btn mgmt-btn--primary"
          onClick={() => { setShowAddForm((v) => !v); setAddError(null) }}
        >
          {showAddForm ? 'Cancel' : '+ Add BDS Rep'}
        </button>
      </div>

      {showAddForm && (
        <div className="bds-reps-tab__add-form">
          <div className="bds-reps-tab__add-row">
            <input
              className="upload-form__input bds-reps-tab__add-input"
              placeholder="Full name"
              value={newName}
              onChange={(e) => { setNewName(e.target.value); setAddError(null) }}
            />
            <input
              className="upload-form__input bds-reps-tab__add-input"
              placeholder="Email address"
              type="email"
              value={newEmail}
              onChange={(e) => { setNewEmail(e.target.value); setAddError(null) }}
            />
            <button className="mgmt-btn mgmt-btn--primary" onClick={handleAdd} disabled={isAdding}>
              {isAdding ? 'Adding…' : 'Add'}
            </button>
          </div>
          {addError && <span className="upload-form__error">{addError}</span>}
        </div>
      )}

      {reps.length === 0 ? (
        <p className="bds-reps-tab__empty">No BDS reps yet. Add one above.</p>
      ) : (
        <div className="bds-reps-tab__list">
          {reps.map((rep) => (
            <BdsRepRow
              key={rep.id}
              rep={rep}
              onToggleActive={() => handleToggleActive(rep.id, rep.is_active)}
              onDelete={() => handleDelete(rep.id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
