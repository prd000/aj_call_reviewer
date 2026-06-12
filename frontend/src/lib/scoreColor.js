export const SCORE_HIGH = 0.7
export const SCORE_MID = 0.4

export function scoreTier(ratio) {
  return ratio >= SCORE_HIGH ? 'high' : ratio >= SCORE_MID ? 'mid' : 'low'
}
