export async function fetchLlmStatus() {
  const response = await fetch('/api/llm/status')

  if (!response.ok) {
    throw new Error(`后端响应异常：${response.status}`)
  }

  return response.json()
}


/**
 * 拉取本地 Ollama 模型（NDJSON 进度流）。
 * onEvent 收到 {type: 'progress'|'done'|'error', status, percent, message, ...}。
 */
export async function pullOllamaModel(model, { onEvent, signal } = {}) {
  const response = await fetch('/api/llm/pull', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model }),
    signal,
  })

  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    throw new Error(payload.detail || `后端响应异常：${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const dispatch = (chunk) => {
    const line = chunk.trim()
    if (!line) return
    try {
      onEvent(JSON.parse(line))
    } catch {
      // 坏行跳过：单行问题不作废整体进度
    }
  }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let sep = buffer.indexOf('\n')
      while (sep >= 0) {
        dispatch(buffer.slice(0, sep))
        buffer = buffer.slice(sep + 1)
        sep = buffer.indexOf('\n')
      }
    }
    buffer += decoder.decode()
    if (buffer.trim()) dispatch(buffer)
  } finally {
    reader.cancel().catch(() => {})
    reader.releaseLock?.()
  }
}
