/**
 * SSE 流式解析客户端（POST + ReadableStream，逐帧解析 data: JSON 事件）。
 */
export async function streamSolve(questionText, { onEvent, signal } = {}) {
  const response = await fetch('/api/solve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question_text: questionText }),
    signal,
  })

  if (!response.ok || !response.body) {
    throw new Error(`后端响应异常：${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let sep = buffer.indexOf('\n\n')
    while (sep >= 0) {
      const frame = buffer.slice(0, sep).trim()
      buffer = buffer.slice(sep + 2)
      if (frame.startsWith('data:')) {
        onEvent(JSON.parse(frame.slice(5).trim()))
      }
      sep = buffer.indexOf('\n\n')
    }
  }
}
