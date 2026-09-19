/** 资料原文查看：页/段摘要列表 + 单页完整内容 + 删除文档。 */
export async function listPages(docId) {
  const response = await fetch(`/api/documents/${docId}/pages`)
  if (!response.ok) {
    throw new Error(`获取页面列表失败：${response.status}`)
  }
  return response.json()
}

export async function getPage(docId, pageNo) {
  const response = await fetch(`/api/documents/${docId}/pages/${pageNo}`)
  if (!response.ok) {
    throw new Error(`获取页面内容失败：${response.status}`)
  }
  return response.json()
}

/** 从知识库删除文档：同时清理向量块、词法索引与上传文件。 */
export async function deleteDocument(docId) {
  const response = await fetch(`/api/documents/${docId}`, { method: 'DELETE' })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(payload.detail || `删除失败：${response.status}`)
  }
  return payload
}
