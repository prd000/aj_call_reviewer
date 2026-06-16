import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

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

import { listTemplates, getTemplate } from '../services/api'
import TemplateManager from './TemplateManager.jsx'

const TEMPLATES = [
  { id: 'tpl-1', name: 'Alpha' },
  { id: 'tpl-2', name: 'Beta' },
]

const FULL_TPL1 = { id: 'tpl-1', name: 'Alpha', criteria: [] }
const FULL_TPL2 = { id: 'tpl-2', name: 'Beta', criteria: [] }

beforeEach(() => {
  vi.clearAllMocks()
  listTemplates.mockResolvedValue(TEMPLATES)
  getTemplate.mockImplementation((id) =>
    Promise.resolve(id === 'tpl-1' ? FULL_TPL1 : FULL_TPL2)
  )
})

describe('TemplateManager default template', () => {
  it('selects the default template on load when defaultTemplateId matches', async () => {
    render(
      <TemplateManager
        onCriteriaChange={() => {}}
        defaultTemplateId="tpl-2"
        onSetDefault={() => {}}
      />
    )
    await waitFor(() => expect(getTemplate).toHaveBeenCalledWith('tpl-2'))
    const select = screen.getByRole('combobox')
    expect(select.value).toBe('tpl-2')
  })

  it('falls back to the first template when defaultTemplateId does not match', async () => {
    render(
      <TemplateManager
        onCriteriaChange={() => {}}
        defaultTemplateId="tpl-deleted"
        onSetDefault={() => {}}
      />
    )
    await waitFor(() => expect(getTemplate).toHaveBeenCalledWith('tpl-1'))
    const select = screen.getByRole('combobox')
    expect(select.value).toBe('tpl-1')
  })

  it('appends (default) to the matching option label', async () => {
    render(
      <TemplateManager
        onCriteriaChange={() => {}}
        defaultTemplateId="tpl-1"
        onSetDefault={() => {}}
      />
    )
    await waitFor(() => screen.getByRole('combobox'))
    const option = screen.getByRole('option', { name: /Alpha.*\(default\)/ })
    expect(option).toBeTruthy()
  })

  it('shows Set as default button when a real template is selected', async () => {
    render(
      <TemplateManager
        onCriteriaChange={() => {}}
        defaultTemplateId={null}
        onSetDefault={() => {}}
      />
    )
    await waitFor(() => screen.getByRole('combobox'))
    expect(screen.getByTitle(/set as default template/i)).toBeTruthy()
  })

  it('calls onSetDefault with the selected template id when clicked', async () => {
    const onSetDefault = vi.fn().mockResolvedValue(undefined)
    render(
      <TemplateManager
        onCriteriaChange={() => {}}
        defaultTemplateId={null}
        onSetDefault={onSetDefault}
      />
    )
    await waitFor(() => screen.getByRole('combobox'))
    fireEvent.click(screen.getByTitle(/set as default template/i))
    await waitFor(() => expect(onSetDefault).toHaveBeenCalledWith('tpl-1'))
  })

  it('shows the active state when selected template is the default', async () => {
    render(
      <TemplateManager
        onCriteriaChange={() => {}}
        defaultTemplateId="tpl-1"
        onSetDefault={() => {}}
      />
    )
    await waitFor(() => screen.getByRole('combobox'))
    expect(screen.getByTitle(/this is your default template/i)).toBeTruthy()
  })
})
