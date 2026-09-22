export async function fetchSource(chunkId) {
  const response = await fetch(`/api/sources/${encodeURIComponent(chunkId)}`)
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    throw new Error(payload.detail || `后端响应异常：${response.status}`)
  }
  return response.json()
}


export async function fetchGaps() {
  const response = await fetch('/api/gaps')
  if (!response.ok) throw new Error(`后端响应异常：${response.status}`)
  return response.json()
}
