import { describe, expect, it, vi } from 'vitest'

// Stub modules with side-effects before importing TemplateManager.
vi.mock('../services/api', () => ({
  listTemplates: vi.fn(),
  getTemplate: vi.fn(),
  createTemplate: vi.fn(),
  updateTemplate: vi.fn(),
  deleteTemplate: vi.fn(),
}))
vi.mock('../hooks/useLoadingWatchdog', () => ({ useLoadingWatchdog: () => {} }))
vi.mock('./CriteriaCard', () => ({ default: () => null }))
vi.mock('./TemplateManager.css', () => ({}))

import { validateImportedTemplate } from './TemplateManager.jsx'

const VALID = {
  name: 'My Template',
  criteria: [
    {
      description: 'Opening strength',
      success_condition: 'Advisor sets agenda in first 30 seconds',
    },
  ],
}

describe('validateImportedTemplate — accept cases', () => {
  it('accepts a minimal valid template', () => {
    const result = validateImportedTemplate(VALID)
    expect(result.ok).toBe(true)
    expect(result.template.name).toBe('My Template')
    expect(result.template.criteria).toHaveLength(1)
  })

  it('accepts a criterion with an optional title', () => {
    const parsed = {
      name: 'T',
      criteria: [{ title: 'Opening', description: 'D', success_condition: 'S' }],
    }
    expect(validateImportedTemplate(parsed).ok).toBe(true)
  })

  it('accepts a criterion with a valid max_score', () => {
    const parsed = {
      name: 'T',
      criteria: [{ description: 'D', success_condition: 'S', max_score: 5 }],
    }
    const result = validateImportedTemplate(parsed)
    expect(result.ok).toBe(true)
    expect(result.template.criteria[0].max_score).toBe(5)
  })

  it('defaults max_score to 10 when omitted', () => {
    const result = validateImportedTemplate(VALID)
    expect(result.template.criteria[0].max_score).toBe(10)
  })

  it('regenerates criterion IDs (crypto.randomUUID)', () => {
    const parsed = {
      name: 'T',
      criteria: [{ id: 'original-id', description: 'D', success_condition: 'S' }],
    }
    const result = validateImportedTemplate(parsed)
    expect(result.ok).toBe(true)
    // IDs are regenerated — exported id is a new UUID, not the original.
    expect(result.template.criteria[0].id).not.toBe('original-id')
  })

  it('accepts multiple criteria', () => {
    const parsed = {
      name: 'Multi',
      criteria: [
        { description: 'A', success_condition: 'Sa' },
        { description: 'B', success_condition: 'Sb' },
      ],
    }
    const result = validateImportedTemplate(parsed)
    expect(result.ok).toBe(true)
    expect(result.template.criteria).toHaveLength(2)
  })
})

describe('validateImportedTemplate — reject cases', () => {
  it('rejects null', () => {
    expect(validateImportedTemplate(null).ok).toBe(false)
  })

  it('rejects an array', () => {
    expect(validateImportedTemplate([{ name: 'T', criteria: [] }]).ok).toBe(false)
  })

  it('rejects unknown top-level field', () => {
    const result = validateImportedTemplate({ name: 'T', criteria: [], extra: true })
    expect(result.ok).toBe(false)
    expect(result.error).toMatch(/unknown/i)
  })

  it('rejects empty name', () => {
    const result = validateImportedTemplate({ name: '', criteria: [{ description: 'D', success_condition: 'S' }] })
    expect(result.ok).toBe(false)
    expect(result.error).toMatch(/name/i)
  })

  it('rejects non-string name', () => {
    const result = validateImportedTemplate({ name: 42, criteria: [] })
    expect(result.ok).toBe(false)
  })

  it('rejects empty criteria array', () => {
    const result = validateImportedTemplate({ name: 'T', criteria: [] })
    expect(result.ok).toBe(false)
  })

  it('rejects criterion missing description', () => {
    const result = validateImportedTemplate({
      name: 'T',
      criteria: [{ success_condition: 'S' }],
    })
    expect(result.ok).toBe(false)
    expect(result.error).toMatch(/description/i)
  })

  it('rejects criterion missing success_condition', () => {
    const result = validateImportedTemplate({
      name: 'T',
      criteria: [{ description: 'D' }],
    })
    expect(result.ok).toBe(false)
    expect(result.error).toMatch(/success_condition/i)
  })

  it('rejects criterion with unknown field', () => {
    const result = validateImportedTemplate({
      name: 'T',
      criteria: [{ description: 'D', success_condition: 'S', color: 'red' }],
    })
    expect(result.ok).toBe(false)
    expect(result.error).toMatch(/unknown/i)
  })

  it('rejects criterion max_score of 0', () => {
    const result = validateImportedTemplate({
      name: 'T',
      criteria: [{ description: 'D', success_condition: 'S', max_score: 0 }],
    })
    expect(result.ok).toBe(false)
  })

  it('rejects criterion max_score that is a float', () => {
    const result = validateImportedTemplate({
      name: 'T',
      criteria: [{ description: 'D', success_condition: 'S', max_score: 1.5 }],
    })
    expect(result.ok).toBe(false)
  })

  it('rejects criterion where title is a number', () => {
    const result = validateImportedTemplate({
      name: 'T',
      criteria: [{ title: 42, description: 'D', success_condition: 'S' }],
    })
    expect(result.ok).toBe(false)
  })
})
