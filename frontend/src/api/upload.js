/** 上传习题册/教材，并列出已入库文档。 */
export async function uploadDocument(docType, file) {
  const form = new FormData()
  form.append('file', file)
  const response = await fetch(`/api/upload/${docType}`, { method: 'POST', body: form })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    const error = new Error(payload.detail || `上传失败：${response.status}`)
    error.status = response.status   // 供调用方区分「内容重复（409）」等业务情形
    throw error
  }
  return payload
}

export async function listDocuments() {
  const response = await fetch('/api/documents')
  if (!response.ok) {
    throw new Error(`获取文档列表失败：${response.status}`)
  }
  return response.json()
}
