import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import UploadForm from '../components/UploadForm'
import TemplateManager from '../components/TemplateManager'
import { uploadCall, processReview } from '../services/api'
import './UploadPage.css'

export default function UploadPage() {
  const navigate = useNavigate()
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)
  const [activeCriteria, setActiveCriteria] = useState([])
  const [activeTemplateName, setActiveTemplateName] = useState('')
  const [activeTemplateId, setActiveTemplateId] = useState(null)

  const handleCriteriaChange = useCallback(function (criteria, templateName, templateId) {
    setActiveCriteria(criteria)
    setActiveTemplateName(templateName)
    setActiveTemplateId(templateId)
  }, [])

  async function handleSubmit(formData) {
    if (activeCriteria.length === 0) {
      setError('Please add at least one review criterion before uploading.')
      return
    }

    setIsLoading(true)
    setError(null)

    let reviewId
    try {
      const { id } = await uploadCall(formData)
      reviewId = id
    } catch (err) {
      setError(err.message || 'Failed to upload the recording. Please try again.')
      setIsLoading(false)
      return
    }

    // Navigate to processing page immediately so the user sees progress feedback
    navigate(`/processing/${reviewId}`)

    // Fire processing in the background — ProcessingPage will poll for completion
    try {
      await processReview(reviewId, {
        criteria: activeCriteria,
        template_name: activeTemplateName,
        template_id: activeTemplateId,
      })
    } catch {
      // ProcessingPage polls status and will show the error state
    }
  }

  return (
    <div className="upload-page">
      <div className="page-container">
        <div className="upload-page__header">
          <h1 className="upload-page__title">Upload a Call Recording</h1>
          <p className="upload-page__subtitle">
            Enter the advisor and prospect details, attach the recording, and we'll
            generate a full coaching review with scores and feedback.
          </p>
        </div>

        {error && (
          <div className="upload-page__error" role="alert">
            <span className="upload-page__error-icon" aria-hidden="true">&#9888;</span>
            {error}
          </div>
        )}

        <div className="upload-page__form-card">
          <UploadForm onSubmit={handleSubmit} isLoading={isLoading} />
        </div>

        <div className="upload-page__template-section">
          <TemplateManager onCriteriaChange={handleCriteriaChange} />
        </div>
      </div>
    </div>
  )
}
