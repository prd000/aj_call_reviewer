import { useState } from 'react'
import ApiKeysTab from '../components/ApiKeysTab'
import BdsRepsTab from '../components/BdsRepsTab'
import FirmsTab from '../components/FirmsTab'
import './ManagementPage.css'

export default function ManagementPage() {
  const [activeTab, setActiveTab] = useState('firms')

  return (
    <div className="management-page">
      <div className="page-container">
        <div className="management-page__header">
          <h1 className="management-page__title">Management</h1>
        </div>

        <div className="management-page__tabs">
          <button
            className={`management-page__tab${activeTab === 'firms' ? ' management-page__tab--active' : ''}`}
            onClick={() => setActiveTab('firms')}
          >
            Firms
          </button>
          <button
            className={`management-page__tab${activeTab === 'bds-reps' ? ' management-page__tab--active' : ''}`}
            onClick={() => setActiveTab('bds-reps')}
          >
            BDS Reps
          </button>
          <button
            className={`management-page__tab${activeTab === 'api-keys' ? ' management-page__tab--active' : ''}`}
            onClick={() => setActiveTab('api-keys')}
          >
            API Keys
          </button>
        </div>

        <div className="management-page__content">
          {activeTab === 'firms' && <FirmsTab />}
          {activeTab === 'bds-reps' && <BdsRepsTab />}
          {activeTab === 'api-keys' && <ApiKeysTab />}
        </div>
      </div>
    </div>
  )
}
