import { describe, expect, it } from 'vitest'
import {
  NO_OUTCOME,
  OUTCOME_FILTER_OPTIONS,
  OUTCOME_OPTIONS,
  outcomeColorClass,
} from './outcomes.js'

describe('outcomeColorClass', () => {
  it('returns green for Closed', () => {
    expect(outcomeColorClass('Closed')).toBe('green')
  })

  it('returns red for lost outcomes', () => {
    expect(outcomeColorClass('Lost after first call')).toBe('red')
    expect(outcomeColorClass('Lost after follow-up')).toBe('red')
  })

  it('returns blue for Follow-up Booked', () => {
    expect(outcomeColorClass('Follow-up Booked')).toBe('blue')
  })

  it('returns yellow for No follow-up booked', () => {
    expect(outcomeColorClass('No follow-up booked')).toBe('yellow')
  })

  it('returns empty string for unknown value', () => {
    expect(outcomeColorClass('Something else')).toBe('')
  })

  it('returns empty string for null', () => {
    expect(outcomeColorClass(null)).toBe('')
  })

  it('returns empty string for undefined', () => {
    expect(outcomeColorClass(undefined)).toBe('')
  })
})

describe('NO_OUTCOME sentinel', () => {
  it('is a non-empty string', () => {
    expect(typeof NO_OUTCOME).toBe('string')
    expect(NO_OUTCOME.length).toBeGreaterThan(0)
  })

  it('is distinct from empty string (the "All" filter value)', () => {
    expect(NO_OUTCOME).not.toBe('')
  })

  it('is distinct from every real outcome value', () => {
    for (const opt of OUTCOME_OPTIONS) {
      expect(NO_OUTCOME).not.toBe(opt.value)
    }
  })

  it('appears in OUTCOME_FILTER_OPTIONS', () => {
    const values = OUTCOME_FILTER_OPTIONS.map((o) => o.value)
    expect(values).toContain(NO_OUTCOME)
  })
})

describe('OUTCOME_OPTIONS', () => {
  it('has at least one option', () => {
    expect(OUTCOME_OPTIONS.length).toBeGreaterThan(0)
  })

  it('every option has value and label', () => {
    for (const opt of OUTCOME_OPTIONS) {
      expect(typeof opt.value).toBe('string')
      expect(typeof opt.label).toBe('string')
    }
  })
})
