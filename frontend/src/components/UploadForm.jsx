import { useRef, useState } from 'react'
import SearchableSelect from './SearchableSelect'
import { OUTCOME_OPTIONS } from '../lib/outcomes'
import './UploadForm.css'

const OUTCOME_SELECT_OPTIONS = [{ value: '', label: 'Not set' }, ...OUTCOME_OPTIONS]

const ACCEPTED_EXTENSIONS = ['.mp3', '.mp4', '.m4a', '.wav']
const ACCEPTED_MIME_TYPES = 'audio/mpeg,audio/mp4,audio/m4a,audio/wav,audio/x-wav,video/mp4'

function validateFileExtension(filename) {
  if (!filename) return false
  const ext = filename.slice(filename.lastIndexOf('.')).toLowerCase()
  return ACCEPTED_EXTENSIONS.includes(ext)
}

export default function UploadForm({
  onSubmit,
  isLoading,
  userRole,
  userName,
  userFirmName,
  firms = [],
  firmAdvisors = [],
  onFirmChange,
  selectedFirmId = '',
  selectedAdvisorId = '',
  onSelectFirm,
  onSelectAdvisor,
  onCreateFirm,
  onCreateAdvisor,
}) {
  const isBds = userRole === 'bds_rep'
  const [prospectName, setProspectName] = useState('')
  const [callOutcome, setCallOutcome] = useState('')
  const [file, setFile] = useState(null)
  const [errors, setErrors] = useState({})
  const [isDragOver, setIsDragOver] = useState(false)
  const fileInputRef = useRef(null)

  const [showAddFirm, setShowAddFirm] = useState(false)
  const [newFirmName, setNewFirmName] = useState('')
  const [isCreatingFirm, setIsCreatingFirm] = useState(false)
  const [firmAddError, setFirmAddError] = useState(null)

  const [showAddAdvisor, setShowAddAdvisor] = useState(false)
  const [newAdvisorName, setNewAdvisorName] = useState('')
  const [isCreatingAdvisor, setIsCreatingAdvisor] = useState(false)
  const [advisorAddError, setAdvisorAddError] = useState(null)

  function clearError(key) {
    setErrors((prev) => (prev[key] ? { ...prev, [key]: '' } : prev))
  }

  function applyFile(selected) {
    if (!selected) return
    if (!validateFileExtension(selected.name)) {
      setErrors((prev) => ({
        ...prev,
        file: `Unsupported file type. Accepted formats: ${ACCEPTED_EXTENSIONS.join(', ')}`,
      }))
      setFile(null)
      return
    }
    setFile(selected)
    clearError('file')
  }

  function toggleAddFirm() {
    setShowAddFirm((v) => !v)
    setNewFirmName('')
    setFirmAddError(null)
  }

  function toggleAddAdvisor() {
    setShowAddAdvisor((v) => !v)
    setNewAdvisorName('')
    setAdvisorAddError(null)
  }

  async function handleCreateFirm() {
    const name = newFirmName.trim()
    if (!name) {
      setFirmAddError('Firm name is required.')
      return
    }
    if (!onCreateFirm) return
    setIsCreatingFirm(true)
    setFirmAddError(null)
    try {
      await onCreateFirm(name)
      setNewFirmName('')
      setShowAddFirm(false)
    } catch (err) {
      setFirmAddError(err?.message || 'Failed to create firm.')
    } finally {
      setIsCreatingFirm(false)
    }
  }

  async function handleCreateAdvisor() {
    const name = newAdvisorName.trim()
    if (!name) {
      setAdvisorAddError('Advisor name is required.')
      return
    }
    if (!selectedFirmId) {
      setAdvisorAddError('Select a firm first.')
      return
    }
    if (!onCreateAdvisor) return
    setIsCreatingAdvisor(true)
    setAdvisorAddError(null)
    try {
      await onCreateAdvisor(name, selectedFirmId)
      setNewAdvisorName('')
      setShowAddAdvisor(false)
    } catch (err) {
      setAdvisorAddError(err?.message || 'Failed to create advisor.')
    } finally {
      setIsCreatingAdvisor(false)
    }
  }

  function validate() {
    const errs = {}
    if (isBds) {
      if (!selectedFirmId) errs.firm = 'Please select a firm.'
      if (!selectedAdvisorId) errs.advisor = 'Please select an advisor.'
    }
    if (!prospectName.trim()) errs.prospectName = 'Prospect name is required.'
    if (!file) errs.file = 'Please select a recording file.'
    return errs
  }

  function handleSubmit(e) {
    e.preventDefault()
    const validationErrors = validate()
    if (Object.keys(validationErrors).length > 0) {
      setErrors(validationErrors)
      return
    }
    const formData = new FormData()
    formData.append('prospect_name', prospectName.trim())
    formData.append('file', file)
    if (isBds) {
      formData.append('firm_id', selectedFirmId)
      formData.append('advisor_user_id', selectedAdvisorId)
    }
    if (callOutcome) formData.append('call_outcome', callOutcome)
    onSubmit(formData)
  }

  return (
    <form className="upload-form" onSubmit={handleSubmit} noValidate>
      <div className="upload-form__fields">
        {isBds ? (
          <>
            <div className="upload-form__field">
              <div className="upload-form__field-header">
                <label htmlFor="firm-select" className="upload-form__label">Firm</label>
                <button
                  type="button"
                  className="upload-form__inline-add"
                  onClick={toggleAddFirm}
                  disabled={isLoading}
                >
                  {showAddFirm ? 'Cancel' : '+ New'}
                </button>
              </div>
              <SearchableSelect
                id="firm-select"
                options={firms.map((f) => ({ value: f.id, label: f.name }))}
                value={selectedFirmId}
                onChange={(firmId) => {
                  onSelectFirm?.(firmId)
                  onSelectAdvisor?.('')
                  clearError('firm')
                  if (firmId) onFirmChange?.(firmId)
                }}
                placeholder="Select a firm…"
                disabled={isLoading}
                hasError={!!errors.firm}
              />
              {showAddFirm && (
                <div className="upload-form__add-row">
                  <input
                    className="upload-form__input"
                    placeholder="New firm name"
                    value={newFirmName}
                    onChange={(e) => { setNewFirmName(e.target.value); setFirmAddError(null) }}
                    disabled={isCreatingFirm}
                  />
                  <button
                    type="button"
                    className="upload-form__add-btn"
                    onClick={handleCreateFirm}
                    disabled={isCreatingFirm}
                  >
                    {isCreatingFirm ? 'Adding…' : 'Add'}
                  </button>
                </div>
              )}
              {firmAddError && <span className="upload-form__error">{firmAddError}</span>}
              {errors.firm && <span className="upload-form__error">{errors.firm}</span>}
            </div>

            <div className="upload-form__field">
              <div className="upload-form__field-header">
                <label htmlFor="advisor-select" className="upload-form__label">Advisor</label>
                <button
                  type="button"
                  className="upload-form__inline-add"
                  onClick={toggleAddAdvisor}
                  disabled={isLoading || !selectedFirmId}
                  title={!selectedFirmId ? 'Select a firm first' : undefined}
                >
                  {showAddAdvisor ? 'Cancel' : '+ New'}
                </button>
              </div>
              <SearchableSelect
                id="advisor-select"
                options={firmAdvisors.map((a) => ({ value: a.id, label: a.name }))}
                value={selectedAdvisorId}
                onChange={(advisorId) => {
                  onSelectAdvisor?.(advisorId)
                  clearError('advisor')
                }}
                placeholder={
                  !selectedFirmId
                    ? 'Select a firm first'
                    : firmAdvisors.length === 0
                    ? 'No advisors at this firm'
                    : 'Select an advisor…'
                }
                disabled={isLoading || !selectedFirmId}
                hasError={!!errors.advisor}
              />
              {showAddAdvisor && (
                <div className="upload-form__add-row">
                  <input
                    className="upload-form__input"
                    placeholder="New advisor name"
                    value={newAdvisorName}
                    onChange={(e) => { setNewAdvisorName(e.target.value); setAdvisorAddError(null) }}
                    disabled={isCreatingAdvisor}
                  />
                  <button
                    type="button"
                    className="upload-form__add-btn"
                    onClick={handleCreateAdvisor}
                    disabled={isCreatingAdvisor}
                  >
                    {isCreatingAdvisor ? 'Adding…' : 'Add'}
                  </button>
                </div>
              )}
              {advisorAddError && <span className="upload-form__error">{advisorAddError}</span>}
              {errors.advisor && <span className="upload-form__error">{errors.advisor}</span>}
            </div>
          </>
        ) : (
          <>
            <div className="upload-form__field">
              <label htmlFor="advisor-name" className="upload-form__label">Advisor Name</label>
              <input
                id="advisor-name"
                type="text"
                className="upload-form__input upload-form__input--readonly"
                value={userName || ''}
                readOnly
              />
            </div>
            <div className="upload-form__field">
              <label htmlFor="firm-name" className="upload-form__label">Firm</label>
              <input
                id="firm-name"
                type="text"
                className="upload-form__input upload-form__input--readonly"
                value={userFirmName || ''}
                readOnly
              />
            </div>
          </>
        )}

        <div className="upload-form__field">
          <label htmlFor="prospectName" className="upload-form__label">Prospect Name</label>
          <input
            id="prospectName"
            name="prospectName"
            type="text"
            className={`upload-form__input${errors.prospectName ? ' upload-form__input--error' : ''}`}
            placeholder="e.g. Michael Torres"
            value={prospectName}
            onChange={(e) => { setProspectName(e.target.value); clearError('prospectName') }}
            disabled={isLoading}
          />
          {errors.prospectName && (
            <span className="upload-form__error">{errors.prospectName}</span>
          )}
        </div>

        <div className="upload-form__field">
          <label htmlFor="call-outcome" className="upload-form__label">Call Outcome (optional)</label>
          <SearchableSelect
            id="call-outcome"
            size="md"
            options={OUTCOME_SELECT_OPTIONS}
            value={callOutcome}
            onChange={setCallOutcome}
            placeholder="Not set"
            disabled={isLoading}
          />
        </div>
      </div>

      <div className="upload-form__field">
        <label className="upload-form__label">Call Recording</label>
        <div
          className={`upload-form__dropzone${isDragOver ? ' upload-form__dropzone--active' : ''}${errors.file ? ' upload-form__dropzone--error' : ''}${file ? ' upload-form__dropzone--has-file' : ''}`}
          onDragOver={(e) => { e.preventDefault(); setIsDragOver(true) }}
          onDragLeave={() => setIsDragOver(false)}
          onDrop={(e) => { e.preventDefault(); setIsDragOver(false); applyFile(e.dataTransfer.files?.[0]) }}
          onClick={() => !isLoading && fileInputRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              if (!isLoading) fileInputRef.current?.click()
            }
          }}
          aria-label="Upload recording file"
        >
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPTED_MIME_TYPES}
            onChange={(e) => applyFile(e.target.files?.[0])}
            className="upload-form__file-input"
            disabled={isLoading}
            tabIndex={-1}
          />
          {file ? (
            <div className="upload-form__file-info">
              <span className="upload-form__file-icon">&#127911;</span>
              <div>
                <p className="upload-form__file-name">{file.name}</p>
                <p className="upload-form__file-size">
                  {(file.size / (1024 * 1024)).toFixed(2)} MB
                </p>
              </div>
            </div>
          ) : (
            <div className="upload-form__dropzone-placeholder">
              <span className="upload-form__upload-icon">&#8679;</span>
              <p className="upload-form__dropzone-text">
                Drag and drop or <span className="upload-form__browse-link">browse</span>
              </p>
              <p className="upload-form__dropzone-hint">
                Accepted formats: MP3, MP4, M4A, WAV
              </p>
            </div>
          )}
        </div>
        {errors.file && <span className="upload-form__error">{errors.file}</span>}
      </div>

      <button type="submit" className="upload-form__submit" disabled={isLoading}>
        {isLoading ? 'Processing…' : 'Upload & Review'}
      </button>
    </form>
  )
}
