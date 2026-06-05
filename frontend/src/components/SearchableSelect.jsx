import { useEffect, useRef, useState } from 'react'
import './SearchableSelect.css'

/**
 * SearchableSelect — custom dropdown with an inline search/filter input.
 *
 * Props:
 *   id          – applied to the trigger button (for <label htmlFor> association)
 *   options     – [{ value: string, label: string }]
 *   value       – single mode: the selected value ('' = nothing selected).
 *                 multiple mode: an array of selected values ([] = nothing selected).
 *   onChange    – single mode: (value: string) => void.
 *                 multiple mode: (values: string[]) => void.
 *   placeholder – text shown when nothing is selected
 *   disabled    – bool
 *   hasError    – bool — applies red border
 *   size        – 'sm' (36 px, for compact filter bars) | 'md' (44 px, default)
 *   multiple    – bool — opt-in multi-select. When true, `value` is an array and
 *                 selecting an option toggles it without closing the dropdown.
 *                 An option with value '' acts as a "clear all" row. Defaults to
 *                 false so all existing single-select callers are unaffected.
 */
export default function SearchableSelect({
  id,
  options = [],
  value = '',
  onChange,
  placeholder = 'Select…',
  disabled = false,
  hasError = false,
  size = 'md',
  multiple = false,
}) {
  const [isOpen, setIsOpen] = useState(false)
  const [search, setSearch] = useState('')
  const containerRef = useRef(null)
  const searchRef = useRef(null)

  // In multiple mode `value` is an array; normalize defensively.
  const selectedValues = multiple ? (Array.isArray(value) ? value : []) : []

  const selectedOption = !multiple
    ? options.find((o) => o.value === value)
    : undefined

  // Whether a given option reads as selected (drives the checkmark + style).
  // The '' row ("All"/clear) is "selected" only when nothing else is.
  function isSelected(opt) {
    if (!multiple) return opt.value === value
    if (opt.value === '') return selectedValues.length === 0
    return selectedValues.includes(opt.value)
  }

  // Trigger label: placeholder when empty, the single label when one is chosen,
  // otherwise an "N selected" count.
  let triggerLabel = placeholder
  let hasSelection = false
  if (multiple) {
    const chosenLabels = options
      .filter((o) => o.value !== '' && selectedValues.includes(o.value))
      .map((o) => o.label)
    hasSelection = chosenLabels.length > 0
    if (chosenLabels.length === 1) triggerLabel = chosenLabels[0]
    else if (chosenLabels.length > 1) triggerLabel = `${chosenLabels.length} selected`
  } else {
    hasSelection = Boolean(selectedOption)
    if (selectedOption) triggerLabel = selectedOption.label
  }

  const filtered = options.filter((o) =>
    o.label.toLowerCase().includes(search.toLowerCase())
  )

  function open() {
    if (disabled) return
    setSearch('')
    setIsOpen(true)
  }

  function close() {
    setIsOpen(false)
    setSearch('')
  }

  function handleSelect(opt) {
    if (!multiple) {
      onChange(opt.value)
      close()
      return
    }
    // Multi-select: the '' row clears everything; any other row toggles.
    // The dropdown stays open so several options can be picked in one pass.
    if (opt.value === '') {
      onChange([])
    } else if (selectedValues.includes(opt.value)) {
      onChange(selectedValues.filter((v) => v !== opt.value))
    } else {
      onChange([...selectedValues, opt.value])
    }
  }

  // Close on outside click
  useEffect(() => {
    function handleOutside(e) {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        close()
      }
    }
    if (isOpen) document.addEventListener('mousedown', handleOutside)
    return () => document.removeEventListener('mousedown', handleOutside)
  }, [isOpen])

  // Auto-focus the search field when the dropdown opens
  useEffect(() => {
    if (isOpen) searchRef.current?.focus()
  }, [isOpen])

  const rootClass = [
    'ss',
    `ss--${size}`,
    isOpen ? 'ss--open' : '',
    hasError ? 'ss--error' : '',
    disabled ? 'ss--disabled' : '',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div ref={containerRef} className={rootClass}>
      {/* Trigger */}
      <button
        type="button"
        id={id}
        className="ss__trigger"
        onClick={() => (isOpen ? close() : open())}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
      >
        <span className={hasSelection ? 'ss__value' : 'ss__placeholder'}>
          {triggerLabel}
        </span>
        <span
          className={`ss__arrow${isOpen ? ' ss__arrow--up' : ''}`}
          aria-hidden="true"
        >
          ▾
        </span>
      </button>

      {/* Dropdown */}
      {isOpen && (
        <div className="ss__dropdown" role="listbox" aria-multiselectable={multiple}>
          <div className="ss__search-wrap">
            <input
              ref={searchRef}
              type="text"
              className="ss__search"
              placeholder="Search…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onMouseDown={(e) => e.stopPropagation()}
            />
          </div>
          <ul className="ss__list">
            {filtered.length === 0 ? (
              <li
                className="ss__option ss__option--empty"
                role="option"
                aria-selected={false}
              >
                No results
              </li>
            ) : (
              filtered.map((o) => {
                const selected = isSelected(o)
                return (
                  <li
                    key={o.value}
                    className={[
                      'ss__option',
                      multiple ? 'ss__option--multi' : '',
                      selected ? 'ss__option--selected' : '',
                      o.value === '' ? 'ss__option--all' : '',
                    ]
                      .filter(Boolean)
                      .join(' ')}
                    role="option"
                    aria-selected={selected}
                    onMouseDown={() => handleSelect(o)}
                  >
                    {multiple && (
                      <span className="ss__check" aria-hidden="true">
                        {selected && o.value !== '' ? '✓' : ''}
                      </span>
                    )}
                    <span className="ss__option-label">{o.label}</span>
                  </li>
                )
              })
            )}
          </ul>
        </div>
      )}
    </div>
  )
}
