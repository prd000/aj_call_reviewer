import { getSession, signOut, refreshSession, SessionUnavailableError } from '../lib/supabaseAuth'

export { SessionUnavailableError }

const BASE_URL = `${import.meta.env.VITE_API_URL ?? ''}/api`

const REQUEST_TIMEOUT_MS = 15_000
const UPLOAD_TIMEOUT_MS = 60_000
const CHAT_TIMEOUT_MS = 30_000
const CHAT_AGENT_TIMEOUT_MS = 90_000
const PDF_TIMEOUT_MS = 30_000

export class NoSessionError extends Error {
  constructor() {
    super('No active session')
    this.name = 'NoSessionError'
  }
}

async function authHeaders(accessToken) {
  if (accessToken) return { Authorization: `Bearer ${accessToken}` }
  const { data: { session } } = await getSession()
  if (!session) throw new NoSessionError()
  return { Authorization: `Bearer ${session.access_token}` }
}

// Wraps fetch with an AbortSignal timeout so hanging requests don't freeze UI state.
function apiFetch(url, options = {}, timeoutMs = REQUEST_TIMEOUT_MS) {
  return fetch(url, { ...options, signal: AbortSignal.timeout(timeoutMs) })
}

async function handleResponse(response) {
  if (response.status === 204) return undefined
  if (response.status === 401) {
    // Before forcing a logout, attempt one token refresh. This handles the race
    // condition where the JWT expired right as this request was in-flight and
    // supabase-js hadn't rotated it yet.
    let refreshed = false
    try {
      const { data } = await refreshSession()
      if (data?.session) {
        console.warn('[api] 401 — session refreshed; the failed operation may be retried')
        refreshed = true
      }
    } catch {
      // SessionUnavailableError or no refresh token — refresh failed, log out below
    }
    if (refreshed) {
      // The user is still authenticated. Surface a retryable error to the caller
      // instead of wiping the session.
      throw new Error('Request failed. Please try again.')
    }
    console.warn('[api] 401 from backend — signing out and redirecting to /login')
    signOut()
    window.location.href = '/login'
    throw new Error('Session expired. Please log in again.')
  }
  if (!response.ok) {
    let errorMessage = `Request failed with status ${response.status}`
    try {
      const errorData = await response.json()
      errorMessage = errorData.detail || errorData.message || errorMessage
    } catch {
      // Response body is not JSON — use the default message
    }
    // 5xx is a server-side transient failure — log but do NOT touch auth state.
    // Caller decides how to surface it (retry silently, show banner, etc.).
    if (response.status >= 500) {
      console.warn(`[api] ${response.status} from backend (transient):`, errorMessage)
    }
    const err = new Error(errorMessage)
    err.status = response.status
    throw err
  }
  return response.json()
}

// ── Reviews ───────────────────────────────────────────────────────────────────

export async function uploadCall(formData) {
  const headers = await authHeaders()
  const response = await apiFetch(`${BASE_URL}/upload`, {
    method: 'POST',
    headers,
    body: formData,
  }, UPLOAD_TIMEOUT_MS)
  return handleResponse(response)
}

export async function getReview(id) {
  const headers = await authHeaders()
  const response = await apiFetch(`${BASE_URL}/reviews/${id}`, { headers })
  return handleResponse(response)
}

export async function listReviews() {
  const headers = await authHeaders()
  const response = await apiFetch(`${BASE_URL}/reviews`, { headers })
  return handleResponse(response)
}

export async function deleteReview(id) {
  const headers = await authHeaders()
  const response = await apiFetch(`${BASE_URL}/reviews/${id}`, {
    method: 'DELETE',
    headers,
  })
  return handleResponse(response)
}

// Re-enqueue a FAILED review for reprocessing. Returns the full updated review
// (status reset to 'pending'). The backend resumes from the transcript checkpoint
// when present (skips Rev.ai), otherwise re-transcribes from the kept recording.
export async function retryReview(id) {
  const headers = await authHeaders()
  const response = await apiFetch(`${BASE_URL}/reviews/${id}/retry`, {
    method: 'POST',
    headers,
  })
  return handleResponse(response)
}

// Pass `null` to clear the outcome. Returns the full updated review.
export async function updateReviewOutcome(id, callOutcome) {
  const headers = { ...(await authHeaders()), 'Content-Type': 'application/json' }
  const response = await apiFetch(`${BASE_URL}/reviews/${id}/outcome`, {
    method: 'PATCH',
    headers,
    body: JSON.stringify({ call_outcome: callOutcome }),
  })
  return handleResponse(response)
}

// Pass a criterion_id to generate focus text for that criterion (BDS only).
// Returns the full updated review.
export async function updateReviewMajorFocus(id, criterionId) {
  const headers = { ...(await authHeaders()), 'Content-Type': 'application/json' }
  const response = await apiFetch(
    `${BASE_URL}/reviews/${id}/major-focus`,
    { method: 'PATCH', headers, body: JSON.stringify({ criterion_id: criterionId }) },
    CHAT_TIMEOUT_MS,
  )
  return handleResponse(response)
}

export async function downloadReviewPdf(id) {
  const headers = await authHeaders()
  const response = await apiFetch(`${BASE_URL}/reviews/${id}/pdf`, { headers }, PDF_TIMEOUT_MS)
  if (!response.ok) {
    let errorMessage = `Request failed with status ${response.status}`
    try {
      const errorData = await response.json()
      errorMessage = errorData.detail || errorData.message || errorMessage
    } catch {
      // non-JSON error body
    }
    const err = new Error(errorMessage)
    err.status = response.status
    throw err
  }
  return response.blob()
}

// Pass an array of tag IDs to replace the review's tags. Returns the full updated review.
export async function updateReviewTags(id, tagIds) {
  const headers = { ...(await authHeaders()), 'Content-Type': 'application/json' }
  const response = await apiFetch(`${BASE_URL}/reviews/${id}/tags`, {
    method: 'PATCH',
    headers,
    body: JSON.stringify({ tag_ids: tagIds }),
  })
  return handleResponse(response)
}

// Pass null or empty string to clear notes. Returns the full updated review.
export async function updateReviewNotes(id, notes) {
  const headers = { ...(await authHeaders()), 'Content-Type': 'application/json' }
  const response = await apiFetch(`${BASE_URL}/reviews/${id}/notes`, {
    method: 'PATCH',
    headers,
    body: JSON.stringify({ notes: notes || null }),
  })
  return handleResponse(response)
}

export async function getTags() {
  const headers = await authHeaders()
  const response = await apiFetch(`${BASE_URL}/tags`, { headers })
  return handleResponse(response)
}

export async function createTag(name) {
  const headers = { ...(await authHeaders()), 'Content-Type': 'application/json' }
  const response = await apiFetch(`${BASE_URL}/tags`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ name }),
  })
  return handleResponse(response)
}

export async function chatAboutReview(id, messages) {
  const headers = { ...(await authHeaders()), 'Content-Type': 'application/json' }
  const response = await apiFetch(
    `${BASE_URL}/reviews/${id}/chat`,
    { method: 'POST', headers, body: JSON.stringify({ messages }) },
    CHAT_TIMEOUT_MS,
  )
  return handleResponse(response)
}

export async function chatOverHistory(reviewIds, messages) {
  const headers = { ...(await authHeaders()), 'Content-Type': 'application/json' }
  const response = await apiFetch(
    `${BASE_URL}/reviews/history-chat`,
    { method: 'POST', headers, body: JSON.stringify({ review_ids: reviewIds, messages }) },
    CHAT_AGENT_TIMEOUT_MS,
  )
  return handleResponse(response)
}

// ── Templates ─────────────────────────────────────────────────────────────────

export async function listTemplates() {
  const headers = await authHeaders()
  const response = await apiFetch(`${BASE_URL}/templates`, { headers })
  return handleResponse(response)
}

export async function getTemplate(id) {
  const headers = await authHeaders()
  const response = await apiFetch(`${BASE_URL}/templates/${id}`, { headers })
  return handleResponse(response)
}

export async function createTemplate(body) {
  const headers = { ...(await authHeaders()), 'Content-Type': 'application/json' }
  const response = await apiFetch(`${BASE_URL}/templates`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })
  return handleResponse(response)
}

export async function updateTemplate(id, body) {
  const headers = { ...(await authHeaders()), 'Content-Type': 'application/json' }
  const response = await apiFetch(`${BASE_URL}/templates/${id}`, {
    method: 'PUT',
    headers,
    body: JSON.stringify(body),
  })
  return handleResponse(response)
}

export async function deleteTemplate(id) {
  const headers = await authHeaders()
  const response = await apiFetch(`${BASE_URL}/templates/${id}`, {
    method: 'DELETE',
    headers,
  })
  return handleResponse(response)
}

// ── User / Auth ───────────────────────────────────────────────────────────────

export async function getCurrentUserProfile(accessToken) {
  const headers = await authHeaders(accessToken)
  const response = await apiFetch(`${BASE_URL}/users/me`, { headers })
  return handleResponse(response)
}

export async function markPasswordSet() {
  const headers = { ...(await authHeaders()), 'Content-Type': 'application/json' }
  const response = await apiFetch(`${BASE_URL}/users/me/password-set`, {
    method: 'POST',
    headers,
  })
  return handleResponse(response)
}

// ── Firms ─────────────────────────────────────────────────────────────────────

export async function listFirms() {
  const headers = await authHeaders()
  const response = await apiFetch(`${BASE_URL}/firms`, { headers })
  return handleResponse(response)
}

export async function createFirm(data) {
  const headers = { ...(await authHeaders()), 'Content-Type': 'application/json' }
  const response = await apiFetch(`${BASE_URL}/firms`, {
    method: 'POST',
    headers,
    body: JSON.stringify(data),
  })
  return handleResponse(response)
}

export async function getFirmDetail(id) {
  const headers = await authHeaders()
  const response = await apiFetch(`${BASE_URL}/firms/${id}`, { headers })
  return handleResponse(response)
}

export async function updateFirm(id, data) {
  const headers = { ...(await authHeaders()), 'Content-Type': 'application/json' }
  const response = await apiFetch(`${BASE_URL}/firms/${id}`, {
    method: 'PUT',
    headers,
    body: JSON.stringify(data),
  })
  return handleResponse(response)
}

export async function deleteFirm(id) {
  const headers = await authHeaders()
  const response = await apiFetch(`${BASE_URL}/firms/${id}`, {
    method: 'DELETE',
    headers,
  })
  return handleResponse(response)
}

export async function getFirmAdvisors(firmId) {
  const detail = await getFirmDetail(firmId)
  return (detail?.users || []).filter((u) => u.role === 'financial_advisor')
}

// ── Management users ──────────────────────────────────────────────────────────

export async function listBdsReps() {
  const headers = await authHeaders()
  const response = await apiFetch(`${BASE_URL}/users/bds-reps`, { headers })
  return handleResponse(response)
}

export async function createUser(data) {
  const headers = { ...(await authHeaders()), 'Content-Type': 'application/json' }
  const response = await apiFetch(`${BASE_URL}/users`, {
    method: 'POST',
    headers,
    body: JSON.stringify(data),
  })
  return handleResponse(response)
}

export async function updateUser(id, data) {
  const headers = { ...(await authHeaders()), 'Content-Type': 'application/json' }
  const response = await apiFetch(`${BASE_URL}/users/${id}`, {
    method: 'PUT',
    headers,
    body: JSON.stringify(data),
  })
  return handleResponse(response)
}

export async function setUserActive(id, active) {
  const headers = { ...(await authHeaders()), 'Content-Type': 'application/json' }
  const response = await apiFetch(`${BASE_URL}/users/${id}/active`, {
    method: 'PATCH',
    headers,
    body: JSON.stringify({ active }),
  })
  return handleResponse(response)
}

export async function promoteAdvisor(userId, email) {
  const headers = { ...(await authHeaders()), 'Content-Type': 'application/json' }
  const response = await apiFetch(`${BASE_URL}/users/${userId}/promote`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ email }),
  })
  return handleResponse(response)
}

export async function deleteUser(id) {
  const headers = await authHeaders()
  const response = await apiFetch(`${BASE_URL}/users/${id}`, {
    method: 'DELETE',
    headers,
  })
  return handleResponse(response)
}
