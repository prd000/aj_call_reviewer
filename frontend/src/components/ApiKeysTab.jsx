import { useEffect, useState } from 'react'
import { createApiKey, listApiKeys, revokeApiKey } from '../services/api'
import { useLoadingWatchdog } from '../hooks/useLoadingWatchdog'
import './ApiKeysTab.css'

function formatDate(iso) {
  if (!iso) return null
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? null : d.toLocaleDateString()
}

function ApiKeyRow({ apiKey, onRevoke }) {
  const [showConfirm, setShowConfirm] = useState(false)
  const [isRevoking, setIsRevoking] = useState(false)
  const [rowError, setRowError] = useState(null)
  const revoked = Boolean(apiKey.revoked_at)

  async function handleRevoke() {
    setIsRevoking(true)
    setRowError(null)
    try {
      await onRevoke()
      setShowConfirm(false)
    } catch (err) {
      setRowError(err?.message || 'Failed to revoke key.')
    } finally {
      setIsRevoking(false)
    }
  }

  const created = formatDate(apiKey.created_at)
  const lastUsed = formatDate(apiKey.last_used_at)

  return (
    <div className={`api-keys-tab__row${revoked ? ' api-keys-tab__row--revoked' : ''}`}>
      <div className="api-keys-tab__row-info">
        <span className="api-keys-tab__label">{apiKey.label}</span>
        <code className="api-keys-tab__prefix">{apiKey.key_prefix}…</code>
        <span className="api-keys-tab__meta">
          {created ? `Created ${created}` : 'Created —'}
          {' · '}
          {lastUsed ? `Last used ${lastUsed}` : 'Never used'}
        </span>
        {revoked && <span className="api-keys-tab__badge">Revoked</span>}
        {rowError && <span className="upload-form__error">{rowError}</span>}
      </div>
      {!revoked && (
        <div className="api-keys-tab__actions">
          {showConfirm ? (
            <>
              <button
                className="mgmt-btn mgmt-btn--danger"
                onClick={handleRevoke}
                disabled={isRevoking}
              >
                {isRevoking ? 'Revoking…' : 'Confirm'}
              </button>
              <button
                className="mgmt-btn mgmt-btn--ghost"
                onClick={() => { setShowConfirm(false); setRowError(null) }}
                disabled={isRevoking}
              >
                Cancel
              </button>
            </>
          ) : (
            <button
              className="mgmt-btn mgmt-btn--danger-outline"
              onClick={() => { setShowConfirm(true); setRowError(null) }}
            >
              Revoke
            </button>
          )}
        </div>
      )}
    </div>
  )
}

// Shown once, right after creation — the full secret is never recoverable later.
function NewKeyReveal({ newKey, onDismiss }) {
  const [copied, setCopied] = useState(false)

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(newKey.full_key)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }

  return (
    <div className="api-keys-tab__reveal">
      <div className="api-keys-tab__reveal-header">
        <span className="api-keys-tab__reveal-title">
          Key created — copy it now
        </span>
        <button className="mgmt-btn mgmt-btn--ghost" onClick={onDismiss}>Dismiss</button>
      </div>
      <p className="api-keys-tab__reveal-note">
        This is the only time the full key for “{newKey.label}” is shown. Store it somewhere safe — you can’t see it again.
      </p>
      <div className="api-keys-tab__reveal-key">
        <code className="api-keys-tab__reveal-code">{newKey.full_key}</code>
        <button className="mgmt-btn mgmt-btn--primary" onClick={handleCopy}>
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
    </div>
  )
}

export default function ApiKeysTab() {
  const [keys, setKeys] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  useLoadingWatchdog(isLoading, setIsLoading, { label: 'api-keys' })
  const [showAddForm, setShowAddForm] = useState(false)
  const [newLabel, setNewLabel] = useState('')
  const [addError, setAddError] = useState(null)
  const [isAdding, setIsAdding] = useState(false)
  const [newKey, setNewKey] = useState(null)

  useEffect(() => {
    listApiKeys()
      .then(setKeys)
      .catch(() => {})
      .finally(() => setIsLoading(false))
  }, [])

  async function handleAdd() {
    if (!newLabel.trim()) {
      setAddError('A label is required.')
      return
    }
    setIsAdding(true)
    setAddError(null)
    try {
      const created = await createApiKey(newLabel.trim())
      setNewKey(created)
      // The list shows metadata only; strip the one-time secret before storing.
      const { full_key: _omit, ...meta } = created
      setKeys((prev) => [meta, ...prev])
      setNewLabel('')
      setShowAddForm(false)
    } catch (err) {
      setAddError(err.message || 'Failed to create key.')
    } finally {
      setIsAdding(false)
    }
  }

  async function handleRevoke(keyId) {
    await revokeApiKey(keyId)
    setKeys((prev) =>
      prev.map((k) => (k.id === keyId ? { ...k, revoked_at: new Date().toISOString() } : k))
    )
  }

  if (isLoading) return <div className="api-keys-tab__loading">Loading API keys…</div>

  return (
    <div className="api-keys-tab">
      <p className="api-keys-tab__intro">
        API keys let external tools (like a Claude Skill or MCP connector) act on your behalf.
        A key inherits your role, so treat it like a password. Revoke any key immediately if it leaks.
      </p>

      <div className="api-keys-tab__toolbar">
        <button
          className="mgmt-btn mgmt-btn--primary"
          onClick={() => { setShowAddForm((v) => !v); setAddError(null) }}
        >
          {showAddForm ? 'Cancel' : '+ Create API Key'}
        </button>
      </div>

      {showAddForm && (
        <div className="api-keys-tab__add-form">
          <div className="api-keys-tab__add-row">
            <input
              className="upload-form__input api-keys-tab__add-input"
              placeholder="Label (e.g. Claude on my laptop)"
              value={newLabel}
              onChange={(e) => { setNewLabel(e.target.value); setAddError(null) }}
              onKeyDown={(e) => { if (e.key === 'Enter') handleAdd() }}
            />
            <button className="mgmt-btn mgmt-btn--primary" onClick={handleAdd} disabled={isAdding}>
              {isAdding ? 'Creating…' : 'Create'}
            </button>
          </div>
          {addError && <span className="upload-form__error">{addError}</span>}
        </div>
      )}

      {newKey && <NewKeyReveal newKey={newKey} onDismiss={() => setNewKey(null)} />}

      {keys.length === 0 ? (
        <p className="api-keys-tab__empty">No API keys yet. Create one above to connect Claude.</p>
      ) : (
        <div className="api-keys-tab__list">
          {keys.map((apiKey) => (
            <ApiKeyRow
              key={apiKey.id}
              apiKey={apiKey}
              onRevoke={() => handleRevoke(apiKey.id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
