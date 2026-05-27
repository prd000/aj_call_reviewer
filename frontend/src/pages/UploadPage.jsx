import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import TemplateManager from '../components/TemplateManager'
import UploadForm from '../components/UploadForm'
import { useAuth } from '../context/AuthContext'
import {
  createFirm,
  createUser,
  getFirmAdvisors,
  listFirms,
  uploadCall,
} from '../services/api'
import './UploadPage.css'

export default function UploadPage() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const isBds = user?.role === 'bds_rep'

  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)
  const [activeCriteria, setActiveCriteria] = useState([])
  const [activeTemplateId, setActiveTemplateId] = useState(null)
  const [firms, setFirms] = useState([])
  const [firmAdvisors, setFirmAdvisors] = useState([])
  const [selectedFirmId, setSelectedFirmId] = useState('')
  const [selectedAdvisorId, setSelectedAdvisorId] = useState('')

  useEffect(() => {
    if (isBds) {
      listFirms().then(setFirms).catch(() => {})
    }
  }, [isBds])

  async function handleFirmChange(firmId) {
    setFirmAdvisors([])
    if (!firmId) return
    try {
      const advisors = await getFirmAdvisors(firmId)
      setFirmAdvisors(advisors)
    } catch {
      setFirmAdvisors([])
    }
  }

  async function handleCreateFirm(name) {
    const firm = await createFirm({ name })
    setFirms((prev) => [...prev, firm])
    setSelectedFirmId(firm.id)
    setSelectedAdvisorId('')
    await handleFirmChange(firm.id)
  }

  async function handleCreateAdvisor(name, firmId) {
    const advisor = await createUser({
      name,
      role: 'financial_advisor',
      firm_id: firmId,
      send_invite: false,
    })
    setFirmAdvisors((prev) => [...prev, advisor])
    setSelectedAdvisorId(advisor.id)
  }

  const handleCriteriaChange = useCallback(function (criteria, _name, templateId) {
    setActiveCriteria(criteria)
    setActiveTemplateId(templateId)
  }, [])

  async function handleSubmit(formData) {
    if (isBds && activeCriteria.length === 0) {
      setError('Please add at least one review criterion before uploading.')
      return
    }

    setIsLoading(true)
    setError(null)

    try {
      if (isBds) {
        formData.append('template_id', activeTemplateId)
      }
      await uploadCall(formData)
      navigate('/history')
    } catch (err) {
      setError(err.message || 'Failed to upload the recording. Please try again.')
      setIsLoading(false)
    }
  }

  return (
    <div className="upload-page">
      <div className="page-container">
        <div className="upload-page__header">
          <h1 className="upload-page__title">Upload a Call Recording</h1>
          <p className="upload-page__subtitle">
            {isBds
              ? 'Select the firm and advisor, attach the recording, and generate a coaching review.'
              : 'Enter the prospect details, attach the recording, and generate a coaching review.'}
          </p>
        </div>

        {error && (
          <div className="upload-page__error" role="alert">
            <span className="upload-page__error-icon" aria-hidden="true">&#9888;</span>
            {error}
          </div>
        )}

        <div className="upload-page__form-card">
          <UploadForm
            onSubmit={handleSubmit}
            isLoading={isLoading}
            userRole={user?.role}
            userName={user?.name}
            userFirmName={user?.firm_name}
            firms={firms}
            firmAdvisors={firmAdvisors}
            onFirmChange={handleFirmChange}
            selectedFirmId={selectedFirmId}
            selectedAdvisorId={selectedAdvisorId}
            onSelectFirm={setSelectedFirmId}
            onSelectAdvisor={setSelectedAdvisorId}
            onCreateFirm={handleCreateFirm}
            onCreateAdvisor={handleCreateAdvisor}
          />
        </div>

        {isBds && (
          <div className="upload-page__template-section">
            <TemplateManager onCriteriaChange={handleCriteriaChange} />
          </div>
        )}
      </div>
    </div>
  )
}
