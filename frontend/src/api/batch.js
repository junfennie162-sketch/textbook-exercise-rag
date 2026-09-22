/** 批量解析任务：创建 / 轮询进度 / 中断。 */
export async function createBatch(questions) {
  const response = await fetch('/api/batch/parse', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ questions }),
  })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(payload.detail || `创建任务失败：${response.status}`)
  }
  return payload
}

export async function getBatchStatus(batchId) {
  const response = await fetch(`/api/batch/${batchId}`)
  if (!response.ok) {
    throw new Error(`查询进度失败：${response.status}`)
  }
  return response.json()
}

export async function cancelBatch(batchId) {
  const response = await fetch(`/api/batch/${batchId}/cancel`, { method: 'POST' })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(payload.detail || `中断任务失败：${response.status}`)
  }
  return payload
}
