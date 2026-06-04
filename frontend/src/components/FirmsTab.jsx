import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { createFirm, listFirms, listTemplates } from '../services/api'
import { useLoadingWatchdog } from '../hooks/useLoadingWatchdog'
import './FirmsTab.css'

export default function FirmsTab() {
  const [firms, setFirms] = useState([])
  const [templates, setTemplates] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [showAddForm, setShowAddForm] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  useLoadingWatchdog(isLoading, setIsLoading, { label: 'firms' })
  const [newName, setNewName] = useState('')
  const [newTemplateId, setNewTemplateId] = useState('')
  const [addError, setAddError] = useState(null)
  const [isSaving, setIsSaving] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    Promise.all([listFirms(), listTemplates()])
      .then(([f, t]) => {
        setFirms(f)
        setTemplates(t)
      })
      .catch(() => {})
      .finally(() => setIsLoading(false))
  }, [])

  async function handleAdd() {
    if (!newName.trim()) {
      setAddError('Firm name is required.')
      return
    }
    setIsSaving(true)
    setAddError(null)
    try {
      const firm = await createFirm({
        name: newName.trim(),
        template_id: newTemplateId || null,
      })
      setFirms((prev) => [...prev, firm].sort((a, b) => a.name.localeCompare(b.name)))
      setNewName('')
      setNewTemplateId('')
      setShowAddForm(false)
    } catch (err) {
      setAddError(err.message || 'Failed to create firm.')
    } finally {
      setIsSaving(false)
    }
  }

  const filteredFirms = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    if (!q) return firms
    return firms.filter((firm) => {
      const name = firm.name?.toLowerCase() || ''
      const template = firm.templates?.name?.toLowerCase() || ''
      return name.includes(q) || template.includes(q)
    })
  }, [firms, searchQuery])

  if (isLoading) return <div className="firms-tab__loading">Loading firms…</div>

  return (
    <div className="firms-tab">
      <div className="firms-tab__toolbar">
        <input
          type="text"
          className="firms-tab__search"
          placeholder="Search firms…"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          aria-label="Search firms"
        />
        <button
          className="mgmt-btn mgmt-btn--primary"
          onClick={() => { setShowAddForm((v) => !v); setAddError(null) }}
        >
          {showAddForm ? 'Cancel' : '+ Add Firm'}
        </button>
      </div>

      {showAddForm && (
        <div className="firms-tab__add-form">
          <div className="firms-tab__add-row">
            <input
              className="upload-form__input firms-tab__add-input"
              placeholder="Firm name"
              value={newName}
              onChange={(e) => { setNewName(e.target.value); setAddError(null) }}
            />
            <select
              className="upload-form__input upload-form__select firms-tab__add-select"
              value={newTemplateId}
              onChange={(e) => setNewTemplateId(e.target.value)}
            >
              <option value="">No template</option>
              {templates.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
            <button className="mgmt-btn mgmt-btn--primary" onClick={handleAdd} disabled={isSaving}>
              {isSaving ? 'Saving…' : 'Save'}
            </button>
          </div>
          {addError && <span className="upload-form__error">{addError}</span>}
        </div>
      )}

      {firms.length === 0 ? (
        <p className="firms-tab__empty">No firms yet. Add one above.</p>
      ) : filteredFirms.length === 0 ? (
        <p className="firms-tab__empty">No firms match “{searchQuery.trim()}”.</p>
      ) : (
        <div className="firms-tab__list">
          {filteredFirms.map((firm) => (
            <div
              key={firm.id}
              className="firms-tab__row"
              onClick={() => navigate(`/management/firms/${firm.id}`)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ')
                  navigate(`/management/firms/${firm.id}`)
              }}
            >
              <div className="firms-tab__row-info">
                <span className="firms-tab__name">{firm.name}</span>
                {firm.templates?.name && (
                  <span className="firms-tab__template-badge">{firm.templates.name}</span>
                )}
              </div>
              <span className="firms-tab__arrow" aria-hidden="true">&#8250;</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
