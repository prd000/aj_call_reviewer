import { useState, useRef } from 'react'
import './UploadForm.css'

const ACCEPTED_EXTENSIONS = ['.mp3', '.mp4', '.m4a', '.wav']
const ACCEPTED_MIME_TYPES = 'audio/mpeg,audio/mp4,audio/m4a,audio/wav,audio/x-wav,video/mp4'

function validateFileExtension(filename) {
  if (!filename) return false
  const ext = filename.slice(filename.lastIndexOf('.')).toLowerCase()
  return ACCEPTED_EXTENSIONS.includes(ext)
}

export default function UploadForm({ onSubmit, isLoading }) {
  const [fields, setFields] = useState({
    advisorName: '',
    firm: '',
    prospectName: '',
    bdsRep: '',
  })
  const [file, setFile] = useState(null)
  const [errors, setErrors] = useState({})
  const [isDragOver, setIsDragOver] = useState(false)
  const fileInputRef = useRef(null)

  function handleFieldChange(e) {
    const { name, value } = e.target
    setFields((prev) => ({ ...prev, [name]: value }))
    if (errors[name]) {
      setErrors((prev) => ({ ...prev, [name]: '' }))
    }
  }

  function handleFileChange(e) {
    const selected = e.target.files?.[0] || null
    applyFile(selected)
  }

  function applyFile(selected) {
    if (selected) {
      if (!validateFileExtension(selected.name)) {
        setErrors((prev) => ({
          ...prev,
          file: `Unsupported file type. Accepted formats: ${ACCEPTED_EXTENSIONS.join(', ')}`,
        }))
        setFile(null)
        return
      }
      setFile(selected)
      setErrors((prev) => ({ ...prev, file: '' }))
    }
  }

  function handleDragOver(e) {
    e.preventDefault()
    setIsDragOver(true)
  }

  function handleDragLeave() {
    setIsDragOver(false)
  }

  function handleDrop(e) {
    e.preventDefault()
    setIsDragOver(false)
    const dropped = e.dataTransfer.files?.[0] || null
    applyFile(dropped)
  }

  function validate() {
    const newErrors = {}
    if (!fields.advisorName.trim()) newErrors.advisorName = 'Advisor name is required.'
    if (!fields.firm.trim()) newErrors.firm = 'Firm name is required.'
    if (!fields.prospectName.trim()) newErrors.prospectName = 'Prospect name is required.'
    if (!file) newErrors.file = 'Please select a recording file.'
    return newErrors
  }

  function handleSubmit(e) {
    e.preventDefault()
    const validationErrors = validate()
    if (Object.keys(validationErrors).length > 0) {
      setErrors(validationErrors)
      return
    }

    const formData = new FormData()
    formData.append('advisor_name', fields.advisorName.trim())
    formData.append('firm', fields.firm.trim())
    formData.append('prospect_name', fields.prospectName.trim())
    formData.append('bds_rep', fields.bdsRep.trim())
    formData.append('file', file)

    onSubmit(formData)
  }

  return (
    <form className="upload-form" onSubmit={handleSubmit} noValidate>
      <div className="upload-form__fields">
        <div className="upload-form__field">
          <label htmlFor="advisorName" className="upload-form__label">
            Advisor Name
          </label>
          <input
            id="advisorName"
            name="advisorName"
            type="text"
            className={`upload-form__input${errors.advisorName ? ' upload-form__input--error' : ''}`}
            placeholder="e.g. Sarah Johnson"
            value={fields.advisorName}
            onChange={handleFieldChange}
            disabled={isLoading}
          />
          {errors.advisorName && (
            <span className="upload-form__error">{errors.advisorName}</span>
          )}
        </div>

        <div className="upload-form__field">
          <label htmlFor="firm" className="upload-form__label">
            Firm Name
          </label>
          <input
            id="firm"
            name="firm"
            type="text"
            className={`upload-form__input${errors.firm ? ' upload-form__input--error' : ''}`}
            placeholder="e.g. Meridian Wealth Advisors"
            value={fields.firm}
            onChange={handleFieldChange}
            disabled={isLoading}
          />
          {errors.firm && (
            <span className="upload-form__error">{errors.firm}</span>
          )}
        </div>

        <div className="upload-form__field">
          <label htmlFor="prospectName" className="upload-form__label">
            Prospect Name
          </label>
          <input
            id="prospectName"
            name="prospectName"
            type="text"
            className={`upload-form__input${errors.prospectName ? ' upload-form__input--error' : ''}`}
            placeholder="e.g. Michael Torres"
            value={fields.prospectName}
            onChange={handleFieldChange}
            disabled={isLoading}
          />
          {errors.prospectName && (
            <span className="upload-form__error">{errors.prospectName}</span>
          )}
        </div>

        <div className="upload-form__field">
          <label htmlFor="bdsRep" className="upload-form__label">
            BDS Rep <span className="upload-form__label-optional">(optional)</span>
          </label>
          <input
            id="bdsRep"
            name="bdsRep"
            type="text"
            className="upload-form__input"
            placeholder="e.g. Jamie Lee"
            value={fields.bdsRep}
            onChange={handleFieldChange}
            disabled={isLoading}
          />
        </div>
      </div>

      <div className="upload-form__field">
        <label className="upload-form__label">Call Recording</label>
        <div
          className={`upload-form__dropzone${isDragOver ? ' upload-form__dropzone--active' : ''}${errors.file ? ' upload-form__dropzone--error' : ''}${file ? ' upload-form__dropzone--has-file' : ''}`}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
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
            onChange={handleFileChange}
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
        {errors.file && (
          <span className="upload-form__error">{errors.file}</span>
        )}
      </div>

      <button
        type="submit"
        className="upload-form__submit"
        disabled={isLoading}
      >
        {isLoading ? 'Processing...' : 'Upload & Review'}
      </button>
    </form>
  )
}
