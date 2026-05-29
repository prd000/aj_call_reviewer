import { useState, useEffect, useRef } from 'react'
import {
  listTemplates,
  getTemplate,
  createTemplate,
  updateTemplate,
  deleteTemplate,
} from '../services/api'
import { useLoadingWatchdog } from '../hooks/useLoadingWatchdog'
import CriteriaCard from './CriteriaCard'
import './TemplateManager.css'

const ALLOWED_TEMPLATE_KEYS = new Set(['name', 'criteria'])
const ALLOWED_CRITERION_KEYS = new Set(['id', 'title', 'description', 'success_condition', 'max_score'])

function validateImportedTemplate(parsed) {
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return { ok: false, error: 'JSON must be an object with "name" and "criteria".' }
  }
  for (const key of Object.keys(parsed)) {
    if (!ALLOWED_TEMPLATE_KEYS.has(key)) {
      return { ok: false, error: `Unknown top-level field "${key}". Allowed: name, criteria.` }
    }
  }
  if (typeof parsed.name !== 'string' || parsed.name.trim() === '') {
    return { ok: false, error: '"name" must be a non-empty string.' }
  }
  if (!Array.isArray(parsed.criteria) || parsed.criteria.length === 0) {
    return { ok: false, error: '"criteria" must be a non-empty array.' }
  }
  const criteria = []
  for (let i = 0; i < parsed.criteria.length; i++) {
    const c = parsed.criteria[i]
    if (c === null || typeof c !== 'object' || Array.isArray(c)) {
      return { ok: false, error: `criteria[${i}] must be an object.` }
    }
    for (const key of Object.keys(c)) {
      if (!ALLOWED_CRITERION_KEYS.has(key)) {
        return { ok: false, error: `criteria[${i}] has unknown field "${key}".` }
      }
    }
    if (typeof c.description !== 'string' || c.description.trim() === '') {
      return { ok: false, error: `criteria[${i}].description must be a non-empty string.` }
    }
    if (typeof c.success_condition !== 'string' || c.success_condition.trim() === '') {
      return { ok: false, error: `criteria[${i}].success_condition must be a non-empty string.` }
    }
    if (c.title !== undefined && typeof c.title !== 'string') {
      return { ok: false, error: `criteria[${i}].title must be a string if present.` }
    }
    if (c.max_score !== undefined) {
      if (!Number.isInteger(c.max_score) || c.max_score < 1) {
        return { ok: false, error: `criteria[${i}].max_score must be a positive integer if present.` }
      }
    }
    criteria.push({
      id: crypto.randomUUID(),
      ...(c.title !== undefined ? { title: c.title } : {}),
      description: c.description,
      success_condition: c.success_condition,
      max_score: c.max_score ?? 10,
    })
  }
  return { ok: true, template: { name: parsed.name, criteria } }
}

export default function TemplateManager({ onCriteriaChange }) {
  const [templates, setTemplates] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [activeName, setActiveName] = useState('')
  const [activeCriteria, setActiveCriteria] = useState([])
  const [originalName, setOriginalName] = useState('')
  const [originalCriteria, setOriginalCriteria] = useState([])
  const [isDirty, setIsDirty] = useState(false)
  const [isAddingCriteria, setIsAddingCriteria] = useState(false)
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState(null)
  const fileInputRef = useRef(null)
  useLoadingWatchdog(isLoading, setIsLoading, { label: 'template-manager' })

  useEffect(() => {
    initTemplates()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  async function initTemplates() {
    try {
      const data = await listTemplates()
      setTemplates(data)
      if (data.length > 0) {
        const full = await getTemplate(data[0].id)
        applyTemplate(full, data)
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setIsLoading(false)
    }
  }

  function applyTemplate(template, templateList) {
    if (templateList !== undefined) {
      setTemplates(templateList)
    }
    setSelectedId(template.id)
    setActiveName(template.name)
    setActiveCriteria(template.criteria)
    setOriginalName(template.name)
    setOriginalCriteria(template.criteria)
    setIsDirty(false)
    setDeleteConfirmOpen(false)
    setIsAddingCriteria(false)
    onCriteriaChange(template.criteria, template.name, template.id)
  }

  async function reloadAndSelect(selectId) {
    const data = await listTemplates()
    const target = data.find(t => t.id === selectId) || data[0]
    if (target) {
      const full = await getTemplate(target.id)
      applyTemplate(full, data)
    } else {
      setTemplates(data)
    }
  }

  async function handleSelectChange(e) {
    const value = e.target.value
    if (value === 'new') {
      setSelectedId('new')
      setActiveName('')
      setActiveCriteria([])
      setOriginalName('')
      setOriginalCriteria([])
      setIsDirty(true)
      setDeleteConfirmOpen(false)
      setIsAddingCriteria(false)
      onCriteriaChange([], '', null)
    } else {
      try {
        const full = await getTemplate(value)
        applyTemplate(full)
      } catch (err) {
        setError(err.message)
      }
    }
  }

  function checkDirty(name, criteria, currentSelectedId) {
    if (currentSelectedId === 'new') return true
    return (
      name !== originalName ||
      JSON.stringify(criteria) !== JSON.stringify(originalCriteria)
    )
  }

  function handleNameChange(e) {
    const name = e.target.value
    setActiveName(name)
    setIsDirty(checkDirty(name, activeCriteria, selectedId))
    onCriteriaChange(activeCriteria, name, selectedId === 'new' ? null : selectedId)
  }

  function handleCriteriaUpdate(updatedCriterion) {
    const updated = activeCriteria.map(c =>
      c.id === updatedCriterion.id ? updatedCriterion : c
    )
    setActiveCriteria(updated)
    setIsDirty(checkDirty(activeName, updated, selectedId))
    onCriteriaChange(updated, activeName, selectedId === 'new' ? null : selectedId)
  }

  function handleCriteriaDelete(criterionId) {
    const updated = activeCriteria.filter(c => c.id !== criterionId)
    setActiveCriteria(updated)
    setIsDirty(checkDirty(activeName, updated, selectedId))
    onCriteriaChange(updated, activeName, selectedId === 'new' ? null : selectedId)
  }

  function handleCriteriaAdd(newCriterion) {
    const updated = [...activeCriteria, newCriterion]
    setActiveCriteria(updated)
    setIsAddingCriteria(false)
    setIsDirty(true)
    onCriteriaChange(updated, activeName, selectedId === 'new' ? null : selectedId)
  }

  async function handleSave() {
    try {
      let savedId
      if (selectedId === 'new') {
        const result = await createTemplate({ name: activeName, criteria: activeCriteria })
        savedId = result.id
      } else {
        await updateTemplate(selectedId, { name: activeName, criteria: activeCriteria })
        savedId = selectedId
      }
      await reloadAndSelect(savedId)
    } catch (err) {
      setError(err.message)
    }
  }

  function handleDiscard() {
    setActiveName(originalName)
    setActiveCriteria(originalCriteria)
    setIsDirty(false)
    setIsAddingCriteria(false)
    onCriteriaChange(
      originalCriteria,
      originalName,
      selectedId === 'new' ? null : selectedId
    )
  }

  async function handleDeleteConfirm() {
    try {
      await deleteTemplate(selectedId)
      setDeleteConfirmOpen(false)
      const remaining = templates.filter(t => t.id !== selectedId)
      await reloadAndSelect(remaining.length > 0 ? remaining[0].id : null)
    } catch (err) {
      setError(err.message)
      setDeleteConfirmOpen(false)
    }
  }

  function handleImportClick() {
    fileInputRef.current?.click()
  }

  async function handleFileChange(e) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setError(null)
    try {
      const text = await file.text()
      let parsed
      try {
        parsed = JSON.parse(text)
      } catch (parseErr) {
        setError(`Invalid JSON: ${parseErr.message}`)
        return
      }
      const result = validateImportedTemplate(parsed)
      if (!result.ok) {
        setError(`Import failed: ${result.error}`)
        return
      }
      setSelectedId('new')
      setActiveName(result.template.name)
      setActiveCriteria(result.template.criteria)
      setOriginalName('')
      setOriginalCriteria([])
      setIsDirty(true)
      setDeleteConfirmOpen(false)
      setIsAddingCriteria(false)
      onCriteriaChange(result.template.criteria, result.template.name, null)
    } catch (err) {
      setError(`Could not read file: ${err.message}`)
    }
  }

  function handleExport() {
    const payload = {
      name: activeName,
      criteria: activeCriteria.map(c => ({
        ...(c.title !== undefined ? { title: c.title } : {}),
        description: c.description,
        success_condition: c.success_condition,
        max_score: c.max_score ?? 10,
      })),
    }
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${(activeName || 'template').replace(/[^a-z0-9_-]+/gi, '_').toLowerCase() || 'template'}.json`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  const canSave = isDirty && activeName.trim().length > 0 && activeCriteria.length > 0
  const canDiscard = isDirty && selectedId !== 'new'

  if (isLoading) {
    return <div className="template-manager__loading">Loading templates...</div>
  }

  return (
    <div className="template-manager">
      <div className="template-manager__header">
        <h2 className="template-manager__title">Review Framework</h2>
      </div>

      {error && (
        <div className="template-manager__error" role="alert">
          {error}
        </div>
      )}

      <div className="template-manager__io">
        <input
          ref={fileInputRef}
          type="file"
          accept="application/json,.json"
          onChange={handleFileChange}
          style={{ display: 'none' }}
        />
        <button
          className="template-manager__btn template-manager__btn--secondary"
          onClick={handleImportClick}
        >
          Import JSON
        </button>
        <button
          className="template-manager__btn template-manager__btn--secondary"
          onClick={handleExport}
          disabled={selectedId === 'new' || activeCriteria.length === 0}
          title="Download this template as JSON"
        >
          Download JSON
        </button>
      </div>

      <div className="template-manager__controls">
        <select
          className="template-manager__dropdown"
          value={selectedId || ''}
          onChange={handleSelectChange}
        >
          {templates.map(t => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
          <option value="new">+ New Template</option>
        </select>

        <input
          className="template-manager__name-input"
          type="text"
          placeholder="Template name"
          value={activeName}
          onChange={handleNameChange}
        />

        <button
          className="template-manager__delete-btn"
          onClick={() => setDeleteConfirmOpen(true)}
          disabled={templates.length <= 1 || selectedId === 'new'}
          title="Delete template"
          aria-label="Delete template"
        >
          ✕
        </button>
      </div>

      {deleteConfirmOpen && (
        <div className="template-manager__delete-confirm">
          <span>Are you sure you want to delete &ldquo;{activeName}&rdquo;?</span>
          <button
            className="template-manager__btn template-manager__btn--danger"
            onClick={handleDeleteConfirm}
          >
            Delete
          </button>
          <button
            className="template-manager__btn template-manager__btn--secondary"
            onClick={() => setDeleteConfirmOpen(false)}
          >
            Cancel
          </button>
        </div>
      )}

      <div className="template-manager__criteria-list">
        {activeCriteria.map(criterion => (
          <CriteriaCard
            key={criterion.id}
            criterion={criterion}
            onUpdate={handleCriteriaUpdate}
            onDelete={handleCriteriaDelete}
          />
        ))}
        {isAddingCriteria && (
          <CriteriaCard
            criterion={null}
            onSave={handleCriteriaAdd}
            onCancel={() => setIsAddingCriteria(false)}
          />
        )}
      </div>

      <div className="template-manager__actions">
        <button
          className="template-manager__btn template-manager__btn--secondary"
          onClick={() => setIsAddingCriteria(true)}
          disabled={isAddingCriteria}
        >
          + Add Criterion
        </button>
        {canSave && (
          <button
            className="template-manager__btn template-manager__btn--primary"
            onClick={handleSave}
          >
            Save Template
          </button>
        )}
        {canDiscard && (
          <button
            className="template-manager__btn template-manager__btn--secondary"
            onClick={handleDiscard}
          >
            Discard Changes
          </button>
        )}
      </div>
    </div>
  )
}
