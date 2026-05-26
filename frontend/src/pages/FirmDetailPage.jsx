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
  const [rowError, setRowError] = useState(null)

  async function handleDelete() {
    setIsDeleting(true)
    setRowError(null)
    try {
      await onDelete()
      setShowConfirm(false)
    } catch (err) {
      setRowError(err?.message || 'Failed to delete user.')
    } finally {
      setIsDeleting(false)
    }
  }

  async function handleToggle() {
    setRowError(null)
    try {
      await onToggleActive()
    } catch (err) {
      setRowError(err?.message || 'Failed to update user.')
    }
  }

  const isAdvisorOnly = user.is_platform_user === false

  return (
    <div className="user-row">
      <div className="user-row__info">
        <span className="user-row__name">{user.name}</span>
        {!isAdvisorOnly && <span className="user-row__email">{user.email}</span>}
        {isAdvisorOnly ? (
          <span className="user-row__status user-row__status--advisor-only">Advisor</span>
        ) : (
          <span
            className={`user-row__status${user.is_active ? ' user-row__status--active' : ' user-row__status--inactive'}`}
          >
            {user.is_active ? 'Active' : 'Inactive'}
          </span>
        )}
        {rowError && <span className="upload-form__error">{rowError}</span>}
      </div>
      <div className="user-row__actions">
        {!isAdvisorOnly && (
          <button className="mgmt-btn mgmt-btn--ghost" onClick={handleToggle}>
            {user.is_active ? 'Deactivate' : 'Reactivate'}
          </button>
        )}
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
              onClick={() => { setShowConfirm(false); setRowError(null) }}
              disabled={isDeleting}
            >
              Cancel
            </button>
          </>
        ) : (
          <button
            className="mgmt-btn mgmt-btn--danger-outline"
            onClick={() => { setShowConfirm(true); setRowError(null) }}
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
  const [sendInvite, setSendInvite] = useState(true)
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
    if (!faName.trim()) {
      setFaError('Name is required.')
      return
    }
    if (sendInvite && !faEmail.trim()) {
      setFaError('Email is required when sending a platform invitation.')
      return
    }
    setIsAddingFa(true)
    setFaError(null)
    try {
      const payload = {
        name: faName.trim(),
        role: 'financial_advisor',
        firm_id: id,
        send_invite: sendInvite,
        ...(sendInvite ? { email: faEmail.trim() } : {}),
      }
      const profile = await createUser(payload)
      setUsers((prev) => [...prev, profile])
      setFaName('')
      setFaEmail('')
      setSendInvite(true)
      setShowAddFa(false)
    } catch (err) {
      setFaError(err.message || 'Failed to create advisor.')
    } finally {
      setIsAddingFa(false)
    }
  }

  async function handleToggleActive(userId, currentlyActive) {
    // Errors propagate to UserRow so the row can display them.
    await setUserActive(userId, !currentlyActive)
    setUsers((prev) =>
      prev.map((u) => (u.id === userId ? { ...u, is_active: !currentlyActive } : u))
    )
  }

  async function handleDeleteUser(userId) {
    await deleteUser(userId)
    setUsers((prev) => prev.filter((u) => u.id !== userId))
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
              onClick={() => {
                setShowAddFa((v) => !v)
                setFaError(null)
                setSendInvite(true)
              }}
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
                {sendInvite && (
                  <input
                    className="upload-form__input"
                    placeholder="Email address"
                    type="email"
                    value={faEmail}
                    onChange={(e) => { setFaEmail(e.target.value); setFaError(null) }}
                  />
                )}
                <button
                  className="mgmt-btn mgmt-btn--primary"
                  onClick={handleAddFa}
                  disabled={isAddingFa}
                >
                  {isAddingFa ? 'Adding…' : 'Add'}
                </button>
              </div>
              <label className="firm-detail-page__invite-toggle">
                <input
                  type="checkbox"
                  checked={sendInvite}
                  onChange={(e) => { setSendInvite(e.target.checked); setFaError(null) }}
                />
                Send platform invitation
              </label>
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
