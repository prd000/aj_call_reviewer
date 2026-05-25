import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  createUser,
  deleteFirm,
  deleteUser,
  getFirmDetail,
  listBdsReps,
  listTemplates,
  setUserActive,
  updateFirm,
} from '../services/api'
import { useLoadingWatchdog } from '../hooks/useLoadingWatchdog'
import './FirmDetailPage.css'

function UserRow({ user, onToggleActive, onDelete }) {
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
    <div className="user-row">
      <div className="user-row__info">
        <span className="user-row__name">{user.name}</span>
        <span className="user-row__email">{user.email}</span>
        <span
          className={`user-row__status${user.is_active ? ' user-row__status--active' : ' user-row__status--inactive'}`}
        >
          {user.is_active ? 'Active' : 'Inactive'}
        </span>
      </div>
      <div className="user-row__actions">
        <button className="mgmt-btn mgmt-btn--ghost" onClick={onToggleActive}>
          {user.is_active ? 'Deactivate' : 'Reactivate'}
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

export default function FirmDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()

  const [firm, setFirm] = useState(null)
  const [users, setUsers] = useState([])
  const [templates, setTemplates] = useState([])
  const [bdsReps, setBdsReps] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)
  useLoadingWatchdog(isLoading, setIsLoading, { label: 'firm-detail' })

  const [editName, setEditName] = useState('')
  const [editTemplateId, setEditTemplateId] = useState('')
  const [editBdsRepId, setEditBdsRepId] = useState('')
  const [isSavingFirm, setIsSavingFirm] = useState(false)
  const [firmSaveError, setFirmSaveError] = useState(null)

  const [showAddFa, setShowAddFa] = useState(false)
  const [faName, setFaName] = useState('')
  const [faEmail, setFaEmail] = useState('')
  const [isAddingFa, setIsAddingFa] = useState(false)
  const [faError, setFaError] = useState(null)

  const [showDeleteFirm, setShowDeleteFirm] = useState(false)
  const [isDeletingFirm, setIsDeletingFirm] = useState(false)

  useEffect(() => {
    Promise.all([getFirmDetail(id), listTemplates(), listBdsReps()])
      .then(([detail, tmpl, reps]) => {
        setFirm(detail.firm)
        setUsers(detail.users)
        setTemplates(tmpl)
        setBdsReps(reps)
        setEditName(detail.firm.name || '')
        setEditTemplateId(detail.firm.template_id || '')
        setEditBdsRepId(detail.firm.bds_rep_id || '')
      })
      .catch((err) => setLoadError(err.message || 'Failed to load firm.'))
      .finally(() => setIsLoading(false))
  }, [id])

  async function handleSaveFirm() {
    setIsSavingFirm(true)
    setFirmSaveError(null)
    try {
      const updated = await updateFirm(id, {
        name: editName.trim(),
        template_id: editTemplateId || null,
        bds_rep_id: editBdsRepId || null,
      })
      setFirm(updated)
    } catch (err) {
      setFirmSaveError(err.message || 'Failed to save.')
    } finally {
      setIsSavingFirm(false)
    }
  }

  async function handleAddFa() {
    if (!faName.trim() || !faEmail.trim()) {
      setFaError('Name and email are required.')
      return
    }
    setIsAddingFa(true)
    setFaError(null)
    try {
      const profile = await createUser({
        email: faEmail.trim(),
        name: faName.trim(),
        role: 'financial_advisor',
        firm_id: id,
      })
      setUsers((prev) => [...prev, profile])
      setFaName('')
      setFaEmail('')
      setShowAddFa(false)
    } catch (err) {
      setFaError(err.message || 'Failed to create advisor.')
    } finally {
      setIsAddingFa(false)
    }
  }

  async function handleToggleActive(userId, currentlyActive) {
    try {
      await setUserActive(userId, !currentlyActive)
      setUsers((prev) =>
        prev.map((u) => (u.id === userId ? { ...u, is_active: !currentlyActive } : u))
      )
    } catch {}
  }

  async function handleDeleteUser(userId) {
    try {
      await deleteUser(userId)
      setUsers((prev) => prev.filter((u) => u.id !== userId))
    } catch {}
  }

  async function handleDeleteFirm() {
    setIsDeletingFirm(true)
    try {
      await deleteFirm(id)
      navigate('/management')
    } catch {
      setIsDeletingFirm(false)
      setShowDeleteFirm(false)
    }
  }

  if (isLoading)
    return (
      <div className="firm-detail-page">
        <div className="page-container firm-detail-page__loading">Loading…</div>
      </div>
    )
  if (loadError)
    return (
      <div className="firm-detail-page">
        <div className="page-container firm-detail-page__load-error">{loadError}</div>
      </div>
    )
  if (!firm) return null

  const faUsers = users.filter((u) => u.role === 'financial_advisor')

  return (
    <div className="firm-detail-page">
      <div className="page-container">
        <button className="firm-detail-page__back" onClick={() => navigate('/management')}>
          ← Back to Management
        </button>

        <h1 className="firm-detail-page__title">{firm.name}</h1>

        {/* ── Firm settings ── */}
        <section className="firm-detail-page__section">
          <h2 className="firm-detail-page__section-title">Firm Settings</h2>
          <div className="firm-detail-page__settings-grid">
            <div className="upload-form__field">
              <label className="upload-form__label">Firm Name</label>
              <input
                className="upload-form__input"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
              />
            </div>
            <div className="upload-form__field">
              <label className="upload-form__label">Review Template</label>
              <select
                className="upload-form__input upload-form__select"
                value={editTemplateId}
                onChange={(e) => setEditTemplateId(e.target.value)}
              >
                <option value="">None</option>
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </select>
            </div>
            <div className="upload-form__field">
              <label className="upload-form__label">Assigned BDS Rep</label>
              <select
                className="upload-form__input upload-form__select"
                value={editBdsRepId}
                onChange={(e) => setEditBdsRepId(e.target.value)}
              >
                <option value="">Unassigned</option>
                {bdsReps.map((r) => (
                  <option key={r.id} value={r.id}>{r.name}</option>
                ))}
              </select>
            </div>
          </div>
          <div className="firm-detail-page__save-row">
            <button
              className="mgmt-btn mgmt-btn--primary"
              onClick={handleSaveFirm}
              disabled={isSavingFirm}
            >
              {isSavingFirm ? 'Saving…' : 'Save Changes'}
            </button>
            {firmSaveError && <span className="upload-form__error">{firmSaveError}</span>}
          </div>
        </section>

        {/* ── Financial Advisors ── */}
        <section className="firm-detail-page__section">
          <div className="firm-detail-page__section-header">
            <h2 className="firm-detail-page__section-title">Financial Advisors</h2>
            <button
              className="mgmt-btn mgmt-btn--primary"
              onClick={() => { setShowAddFa((v) => !v); setFaError(null) }}
            >
              {showAddFa ? 'Cancel' : '+ Add Advisor'}
            </button>
          </div>

          {showAddFa && (
            <div className="firm-detail-page__add-form">
              <div className="firm-detail-page__add-row">
                <input
                  className="upload-form__input"
                  placeholder="Full name"
                  value={faName}
                  onChange={(e) => { setFaName(e.target.value); setFaError(null) }}
                />
                <input
                  className="upload-form__input"
                  placeholder="Email address"
                  type="email"
                  value={faEmail}
                  onChange={(e) => { setFaEmail(e.target.value); setFaError(null) }}
                />
                <button
                  className="mgmt-btn mgmt-btn--primary"
                  onClick={handleAddFa}
                  disabled={isAddingFa}
                >
                  {isAddingFa ? 'Adding…' : 'Add'}
                </button>
              </div>
              {faError && <span className="upload-form__error">{faError}</span>}
            </div>
          )}

          {faUsers.length === 0 ? (
            <p className="firm-detail-page__empty">No advisors at this firm yet.</p>
          ) : (
            <div className="firm-detail-page__user-list">
              {faUsers.map((u) => (
                <UserRow
                  key={u.id}
                  user={u}
                  onToggleActive={() => handleToggleActive(u.id, u.is_active)}
                  onDelete={() => handleDeleteUser(u.id)}
                />
              ))}
            </div>
          )}
        </section>

        {/* ── Danger Zone ── */}
        <section className="firm-detail-page__section firm-detail-page__danger-zone">
          <h2 className="firm-detail-page__section-title">Danger Zone</h2>
          {showDeleteFirm ? (
            <div className="firm-detail-page__confirm">
              <p className="firm-detail-page__confirm-text">
                This will deactivate all {faUsers.length} advisor
                {faUsers.length !== 1 ? 's' : ''} at this firm. Reviews are preserved. Continue?
              </p>
              <div className="firm-detail-page__confirm-actions">
                <button
                  className="mgmt-btn mgmt-btn--danger"
                  onClick={handleDeleteFirm}
                  disabled={isDeletingFirm}
                >
                  {isDeletingFirm ? 'Deleting…' : 'Delete Firm'}
                </button>
                <button
                  className="mgmt-btn mgmt-btn--ghost"
                  onClick={() => setShowDeleteFirm(false)}
                  disabled={isDeletingFirm}
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <button
              className="mgmt-btn mgmt-btn--danger-outline"
              onClick={() => setShowDeleteFirm(true)}
            >
              Delete Firm
            </button>
          )}
        </section>
      </div>
    </div>
  )
}
