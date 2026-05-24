const BASE_URL = '/api'

async function handleResponse(response) {
  if (response.status === 204) {
    return undefined
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

export async function uploadCall(formData) {
  const response = await fetch(`${BASE_URL}/upload`, {
    method: 'POST',
    body: formData,
  })
  return handleResponse(response)
}

export async function getReview(id) {
  const response = await fetch(`${BASE_URL}/reviews/${id}`)
  return handleResponse(response)
}

export async function listReviews() {
  const response = await fetch(`${BASE_URL}/reviews`)
  return handleResponse(response)
}

export async function listTemplates() {
  const response = await fetch(`${BASE_URL}/templates`)
  return handleResponse(response)
}

export async function getTemplate(id) {
  const response = await fetch(`${BASE_URL}/templates/${id}`)
  return handleResponse(response)
}

export async function createTemplate(body) {
  const response = await fetch(`${BASE_URL}/templates`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return handleResponse(response)
}

export async function updateTemplate(id, body) {
  const response = await fetch(`${BASE_URL}/templates/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return handleResponse(response)
}

export async function deleteTemplate(id) {
  const response = await fetch(`${BASE_URL}/templates/${id}`, {
    method: 'DELETE',
  })
  return handleResponse(response)
}

export async function deleteReview(id) {
  const response = await fetch(`${BASE_URL}/reviews/${id}`, {
    method: 'DELETE',
  })
  return handleResponse(response)
}
