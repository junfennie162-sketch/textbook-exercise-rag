/** 解析结果历史：列表（可按关键词/状态筛选）、详情、删除。 */
export async function listSolutions({ limit = 50, keyword = '', status = '' } = {}) {
  const params = new URLSearchParams({ limit: String(limit) })
  if (keyword) params.set('keyword', keyword)
  if (status) params.set('status', status)
  const response = await fetch(`/api/solutions?${params.toString()}`)
  if (!response.ok) {
    throw new Error(`获取历史记录失败：${response.status}`)
  }
  return response.json()
}

export async function getSolution(solutionId) {
  const response = await fetch(`/api/solutions/${solutionId}`)
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(payload.detail || `获取解析详情失败：${response.status}`)
  }
  return payload
}

export async function deleteSolution(solutionId) {
  const response = await fetch(`/api/solutions/${solutionId}`, { method: 'DELETE' })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(payload.detail || `删除失败：${response.status}`)
  }
  return payload
}
