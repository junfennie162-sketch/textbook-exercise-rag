export async function fetchHealth() {
  const response = await fetch('/api/health')

  if (!response.ok) {
    throw new Error(`后端响应异常：${response.status}`)
  }

  return response.json()
}
