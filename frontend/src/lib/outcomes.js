// Call-outcome labels — single source of truth on the frontend.
//
// These strings MUST stay byte-identical to backend `CALL_OUTCOMES`
// (backend/modules/ingestion.py), including the inconsistent casing. The
// backend is the validator of record; the frontend only ever sends these
// canonical strings.

export const OUTCOME_OPTIONS = [
  { value: 'Lost after first call', label: 'Lost after first call' },
  { value: 'No follow-up booked', label: 'No follow-up booked' },
  { value: 'Follow-up Booked', label: 'Follow-up Booked' },
  { value: 'Lost after follow-up', label: 'Lost after follow-up' },
  { value: 'Closed', label: 'Closed' },
]

// Sentinel for the history filter's "no outcome set" option (untagged calls).
// Kept distinct from '' (= "All") and from any real outcome string.
export const NO_OUTCOME = '__none__'

export const OUTCOME_FILTER_OPTIONS = [
  { value: '', label: 'All' },
  ...OUTCOME_OPTIONS,
  { value: NO_OUTCOME, label: 'No outcome set' },
]

// Maps an outcome to a color key used for the history-row pill. Single source
// of truth for the color mapping (per DESIGN.md, colors are applied as text,
// not card fills).
export function outcomeColorClass(outcome) {
  switch (outcome) {
    case 'Closed':
      return 'green'
    case 'Lost after first call':
    case 'Lost after follow-up':
      return 'red'
    case 'Follow-up Booked':
      return 'blue'
    case 'No follow-up booked':
      return 'yellow'
    default:
      return ''
  }
}
