const BASE = import.meta.env.VITE_API_BASE || ''

async function parseResponse(resp) {
  const text = await resp.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = text }
  if (!resp.ok) {
    const detail = data && typeof data === 'object' ? (data.detail || JSON.stringify(data)) : data
    throw new Error(detail || `HTTP ${resp.status}`)
  }
  return data
}

export async function uploadDocuments(files) {
  const form = new FormData()
  for (const file of files) form.append('files', file)
  return parseResponse(await fetch(`${BASE}/api/documents/upload`, { method: 'POST', body: form }))
}

export async function listDocuments() {
  return parseResponse(await fetch(`${BASE}/api/documents`))
}

export async function retryDocument(id) {
  return parseResponse(await fetch(`${BASE}/api/documents/${id}/retry`, { method: 'POST' }))
}

export function openDocumentEvents() {
  return new EventSource(`${BASE}/api/documents/events`)
}

export async function createSession() {
  return parseResponse(await fetch(`${BASE}/api/chat/sessions`, { method: 'POST' }))
}

export async function listSessions() {
  return parseResponse(await fetch(`${BASE}/api/chat/sessions`))
}

export async function listMessages(sessionId) {
  return parseResponse(await fetch(`${BASE}/api/chat/sessions/${sessionId}/messages`))
}

export async function askQuestion(sessionId, question, imageFile) {
  const form = new FormData()
  form.append('session_id', String(sessionId))
  form.append('question', question || '')
  if (imageFile) form.append('image', imageFile)
  return parseResponse(await fetch(`${BASE}/api/chat/ask`, { method: 'POST', body: form }))
}
