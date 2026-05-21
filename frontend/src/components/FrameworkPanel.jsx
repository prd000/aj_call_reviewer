import './FrameworkPanel.css'

export default function FrameworkPanel({ framework }) {
  if (!framework || !framework.criteria || framework.criteria.length === 0) {
    return null
  }

  const { template_name, criteria } = framework
  const displayName = template_name || 'Unsaved Template'

  return (
    <section className="framework-panel">
      <div className="framework-panel__header">
        <h2 className="framework-panel__heading">Review Framework</h2>
        <span className="framework-panel__template-badge">{displayName}</span>
      </div>

      <div className="framework-panel__criteria-list">
        {criteria.map((criterion, index) => (
          <div key={criterion.id || index} className="framework-panel__criterion">
            <h3 className="framework-panel__criterion-title">
              {criterion.title || criterion.description}
            </h3>
            {criterion.success_condition && (
              <div className="framework-panel__success-block">
                <span className="framework-panel__success-label">Success Condition</span>
                <p className="framework-panel__success-condition">{criterion.success_condition}</p>
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}
