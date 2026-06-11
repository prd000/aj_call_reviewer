import { useState } from 'react'
import SearchableSelect from './SearchableSelect'
import { createTag } from '../services/api'
import './TagEditor.css'

export default function TagEditor({ tagIds, allTags, onTagsChange, onTagCreated, disabled }) {
  const [newTagName, setNewTagName] = useState('')
  const [isCreating, setIsCreating] = useState(false)
  const [createError, setCreateError] = useState(null)

  const attachedTags = allTags.filter((t) => tagIds.includes(t.id))
  const availableTags = allTags.filter((t) => !tagIds.includes(t.id))

  const selectOptions = [
    { value: '', label: 'Add existing tag…' },
    ...availableTags.map((t) => ({ value: t.id, label: t.name })),
  ]

  function handleSelect(tagId) {
    if (!tagId) return
    onTagsChange([...tagIds, tagId])
  }

  function handleRemove(tagId) {
    onTagsChange(tagIds.filter((id) => id !== tagId))
  }

  async function handleCreate() {
    const name = newTagName.trim()
    if (!name) return
    setCreateError(null)
    setIsCreating(true)
    try {
      const tag = await createTag(name)
      onTagCreated(tag)
      if (!tagIds.includes(tag.id)) {
        onTagsChange([...tagIds, tag.id])
      }
      setNewTagName('')
    } catch (err) {
      setCreateError(err.message || 'Failed to create tag.')
    } finally {
      setIsCreating(false)
    }
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleCreate()
    }
  }

  return (
    <div className="tag-editor">
      <div className="tag-editor__label">Tags</div>

      {attachedTags.length > 0 && (
        <div className="tag-editor__chips">
          {attachedTags.map((tag) => (
            <span key={tag.id} className="tag-editor__chip">
              {tag.name}
              <button
                type="button"
                className="tag-editor__chip-remove"
                onClick={() => handleRemove(tag.id)}
                disabled={disabled}
                aria-label={`Remove tag ${tag.name}`}
              >
                &#x2715;
              </button>
            </span>
          ))}
        </div>
      )}

      <div className="tag-editor__controls">
        {availableTags.length > 0 && (
          <SearchableSelect
            id="tag-select"
            size="sm"
            options={selectOptions}
            value=""
            onChange={handleSelect}
            placeholder="Add existing tag…"
            disabled={disabled || isCreating}
          />
        )}

        <div className="tag-editor__create">
          <input
            type="text"
            className="tag-editor__input"
            placeholder="New tag name…"
            value={newTagName}
            onChange={(e) => setNewTagName(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={disabled || isCreating}
            maxLength={80}
          />
          <button
            type="button"
            className="tag-editor__add-btn"
            onClick={handleCreate}
            disabled={disabled || isCreating || !newTagName.trim()}
          >
            {isCreating ? '…' : 'Add'}
          </button>
        </div>
      </div>

      {createError && <p className="tag-editor__error">{createError}</p>}
    </div>
  )
}
