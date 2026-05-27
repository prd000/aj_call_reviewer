import { useEffect, useRef, useState } from 'react'
import './SearchableSelect.css'

/**
 * SearchableSelect — custom dropdown with an inline search/filter input.
 *
 * Props:
 *   id          – applied to the trigger button (for <label htmlFor> association)
 *   options     – [{ value: string, label: string }]
 *   value       – currently selected value ('' = nothing selected)
 *   onChange    – (value: string) => void
 *   placeholder – text shown when nothing is selected
 *   disabled    – bool
 *   hasError    – bool — applies red border
 *   size        – 'sm' (36 px, for compact filter bars) | 'md' (44 px, default)
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
}) {
  const [isOpen, setIsOpen] = useState(false)
  const [search, setSearch] = useState('')
  const containerRef = useRef(null)
  const searchRef = useRef(null)

  const selectedOption = options.find((o) => o.value === value)

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
    onChange(opt.value)
    close()
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
        <span className={selectedOption ? 'ss__value' : 'ss__placeholder'}>
          {selectedOption ? selectedOption.label : placeholder}
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
        <div className="ss__dropdown" role="listbox">
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
              filtered.map((o) => (
                <li
                  key={o.value}
                  className={[
                    'ss__option',
                    o.value === value ? 'ss__option--selected' : '',
                    o.value === '' ? 'ss__option--all' : '',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                  role="option"
                  aria-selected={o.value === value}
                  onMouseDown={() => handleSelect(o)}
                >
                  {o.label}
                </li>
              ))
            )}
          </ul>
        </div>
      )}
    </div>
  )
}
