export async function fetchSettings() {
  const response = await fetch('/api/settings')
  if (!response.ok) throw new Error(`后端响应异常：${response.status}`)
  return response.json()
}

export async function saveSettings(values) {
  const response = await fetch('/api/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ values }),
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    throw new Error(payload.detail || `后端响应异常：${response.status}`)
  }
  return response.json()
}

export async function resetSettings() {
  const response = await fetch('/api/settings/reset', { method: 'POST' })
  if (!response.ok) throw new Error(`后端响应异常：${response.status}`)
  return response.json()
}
