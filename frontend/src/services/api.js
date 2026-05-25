import { supabase } from '../lib/supabase'

const BASE_URL = `${import.meta.env.VITE_API_URL ?? ''}/api`

async function authHeaders() {
  const { data: { session } } = await supabase.auth.getSession()
  return session ? { Authorization: `Bearer ${session.access_token}` } : {}
}

async function handleResponse(response) {
  if (response.status === 204) return undefined
  if (response.status === 401) {
    await supabase.auth.signOut()
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
    throw new Error(errorMessage)
  }
  return response.json()
}

// ── Reviews ───────────────────────────────────────────────────────────────────

export async function uploadCall(formData) {
  const headers = await authHeaders()
  const response = await fetch(`${BASE_URL}/upload`, {
    method: 'POST',
    headers,
    body: formData,
  })
  return handleResponse(response)
}

export async function getReview(id) {
  const headers = await authHeaders()
  const response = await fetch(`${BASE_URL}/reviews/${id}`, { headers })
  return handleResponse(response)
}

export async function listReviews() {
  const headers = await authHeaders()
  const response = await fetch(`${BASE_URL}/reviews`, { headers })
  return handleResponse(response)
}

export async function deleteReview(id) {
  const headers = await authHeaders()
  const response = await fetch(`${BASE_URL}/reviews/${id}`, {
    method: 'DELETE',
    headers,
  })
  return handleResponse(response)
}

// ── Templates ─────────────────────────────────────────────────────────────────

export async function listTemplates() {
  const headers = await authHeaders()
  const response = await fetch(`${BASE_URL}/templates`, { headers })
  return handleResponse(response)
}

export async function getTemplate(id) {
  const headers = await authHeaders()
  const response = await fetch(`${BASE_URL}/templates/${id}`, { headers })
  return handleResponse(response)
}

export async function createTemplate(body) {
  const headers = { ...(await authHeaders()), 'Content-Type': 'application/json' }
  const response = await fetch(`${BASE_URL}/templates`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })
  return handleResponse(response)
}

export async function updateTemplate(id, body) {
  const headers = { ...(await authHeaders()), 'Content-Type': 'application/json' }
  const response = await fetch(`${BASE_URL}/templates/${id}`, {
    method: 'PUT',
    headers,
    body: JSON.stringify(body),
  })
  return handleResponse(response)
}

export async function deleteTemplate(id) {
  const headers = await authHeaders()
  const response = await fetch(`${BASE_URL}/templates/${id}`, {
    method: 'DELETE',
    headers,
  })
  return handleResponse(response)
}

// ── User / Auth ───────────────────────────────────────────────────────────────

export async function getCurrentUserProfile() {
  const headers = await authHeaders()
  const response = await fetch(`${BASE_URL}/users/me`, { headers })
  return handleResponse(response)
}

// ── Firms ─────────────────────────────────────────────────────────────────────

export async function listFirms() {
  const headers = await authHeaders()
  const response = await fetch(`${BASE_URL}/firms`, { headers })
  return handleResponse(response)
}

export async function createFirm(data) {
  const headers = { ...(await authHeaders()), 'Content-Type': 'application/json' }
  const response = await fetch(`${BASE_URL}/firms`, {
    method: 'POST',
    headers,
    body: JSON.stringify(data),
  })
  return handleResponse(response)
}

export async function getFirmDetail(id) {
  const headers = await authHeaders()
  const response = await fetch(`${BASE_URL}/firms/${id}`, { headers })
  return handleResponse(response)
}

export async function updateFirm(id, data) {
  const headers = { ...(await authHeaders()), 'Content-Type': 'application/json' }
  const response = await fetch(`${BASE_URL}/firms/${id}`, {
    method: 'PUT',
    headers,
    body: JSON.stringify(data),
  })
  return handleResponse(response)
}

export async function deleteFirm(id) {
  const headers = await authHeaders()
  const response = await fetch(`${BASE_URL}/firms/${id}`, {
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
  const response = await fetch(`${BASE_URL}/users/bds-reps`, { headers })
  return handleResponse(response)
}

export async function createUser(data) {
  const headers = { ...(await authHeaders()), 'Content-Type': 'application/json' }
  const response = await fetch(`${BASE_URL}/users`, {
    method: 'POST',
    headers,
    body: JSON.stringify(data),
  })
  return handleResponse(response)
}

export async function updateUser(id, data) {
  const headers = { ...(await authHeaders()), 'Content-Type': 'application/json' }
  const response = await fetch(`${BASE_URL}/users/${id}`, {
    method: 'PUT',
    headers,
    body: JSON.stringify(data),
  })
  return handleResponse(response)
}

export async function setUserActive(id, active) {
  const headers = { ...(await authHeaders()), 'Content-Type': 'application/json' }
  const response = await fetch(`${BASE_URL}/users/${id}/active`, {
    method: 'PATCH',
    headers,
    body: JSON.stringify({ active }),
  })
  return handleResponse(response)
}

export async function deleteUser(id) {
  const headers = await authHeaders()
  const response = await fetch(`${BASE_URL}/users/${id}`, {
    method: 'DELETE',
    headers,
  })
  return handleResponse(response)
}
