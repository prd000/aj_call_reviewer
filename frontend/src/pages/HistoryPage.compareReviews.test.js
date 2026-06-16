import { beforeAll, describe, expect, it, vi } from 'vitest'

// Stub modules with side-effects before importing HistoryPage.
vi.mock('../context/AuthContext', () => ({ useAuth: () => ({}) }))
vi.mock('../services/api', () => ({
  chatOverHistory: vi.fn(),
  deleteReview: vi.fn(),
  listFirms: vi.fn(),
  listReviews: vi.fn(),
  retryReview: vi.fn(),
}))
vi.mock('../components/ChatPanel', () => ({ default: () => null }))
vi.mock('../components/ReviewList', () => ({ default: () => null }))
vi.mock('../components/SearchableSelect', () => ({ default: () => null }))
vi.mock('../hooks/useLoadingWatchdog', () => ({ useLoadingWatchdog: () => {} }))
vi.mock('../lib/reviewStatus', () => ({ IN_PROGRESS_STATUSES: ['pending', 'transcribing', 'reviewing'] }))
vi.mock('./HistoryPage.css', () => ({}))

import { compareReviews } from './HistoryPage.jsx'

function r(score, date) {
  return { overall_score: score, created_at: date }
}

describe('compareReviews', () => {
  describe('date_desc (default)', () => {
    it('puts newer first', () => {
      expect(compareReviews(r(null, '2026-01-01'), r(null, '2026-06-01'), 'date_desc')).toBeGreaterThan(0)
      expect(compareReviews(r(null, '2026-06-01'), r(null, '2026-01-01'), 'date_desc')).toBeLessThan(0)
    })

    it('equal dates → 0', () => {
      expect(compareReviews(r(null, '2026-01-01'), r(null, '2026-01-01'), 'date_desc')).toBe(0)
    })
  })

  describe('date_asc', () => {
    it('puts older first', () => {
      expect(compareReviews(r(null, '2026-01-01'), r(null, '2026-06-01'), 'date_asc')).toBeLessThan(0)
    })
  })

  describe('score_desc', () => {
    it('higher score first', () => {
      expect(compareReviews(r(5, '2026-01-01'), r(8, '2026-01-01'), 'score_desc')).toBeGreaterThan(0)
      expect(compareReviews(r(8, '2026-01-01'), r(5, '2026-01-01'), 'score_desc')).toBeLessThan(0)
    })

    it('null score sorts below any real score', () => {
      expect(compareReviews(r(null, '2026-01-01'), r(8, '2026-01-01'), 'score_desc')).toBeGreaterThan(0)
      expect(compareReviews(r(8, '2026-01-01'), r(null, '2026-01-01'), 'score_desc')).toBeLessThan(0)
    })

    it('two null scores are ordered newest-first', () => {
      // older a, newer b → compareReviews(a, b) > 0 means b goes first
      expect(compareReviews(r(null, '2026-01-01'), r(null, '2026-06-01'), 'score_desc')).toBeGreaterThan(0)
    })
  })

  describe('score_asc', () => {
    it('lower score first', () => {
      expect(compareReviews(r(3, '2026-01-01'), r(8, '2026-01-01'), 'score_asc')).toBeLessThan(0)
    })

    it('null score still sorts to the bottom (last)', () => {
      expect(compareReviews(r(null, '2026-01-01'), r(1, '2026-01-01'), 'score_asc')).toBeGreaterThan(0)
    })
  })

  describe('unknown sortBy falls back to date_desc', () => {
    it('behaves like date_desc for unknown value', () => {
      expect(compareReviews(r(null, '2026-01-01'), r(null, '2026-06-01'), 'unknown')).toBeGreaterThan(0)
    })
  })
})
