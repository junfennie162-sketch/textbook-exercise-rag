/**
 * SSE 流式解析客户端（POST + ReadableStream，逐帧解析 data: JSON 事件）。
 *
 * 健壮性约定：
 * - 单帧 JSON 解析失败只跳过该帧，不影响整条流（代理改写、心跳帧、半帧都不至于让整次生成失败）；
 * - 循环结束后对残留缓冲区再解析一次（末帧未以空行结尾时不会丢 done 事件，避免拿不到 solution_id 无法导出）；
 * - 收尾调用 decoder.decode() 处理被拆断的多字节字符；
 * - 非 2xx 时读取响应体中的 detail，给出可读错误；
 * - 异常/中止时释放读取锁并取消流。
 */
export async function streamSolve(questionText, { onEvent, signal } = {}) {
  const response = await fetch('/api/solve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question_text: questionText }),
    signal,
  })

  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => ({}))
    throw new Error(payload.detail || `后端响应异常：${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const dispatch = (frame) => {
    const line = frame.trim()
    if (!line.startsWith('data:')) return
    try {
      onEvent(JSON.parse(line.slice(5).trim()))
    } catch {
      // 坏帧跳过：单帧问题不应作废已渲染的内容
    }
  }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let sep = buffer.indexOf('\n\n')
      while (sep >= 0) {
        dispatch(buffer.slice(0, sep))
        buffer = buffer.slice(sep + 2)
        sep = buffer.indexOf('\n\n')
      }
    }
    buffer += decoder.decode()
    if (buffer.trim()) dispatch(buffer)
  } finally {
    reader.cancel().catch(() => {})
    reader.releaseLock?.()
  }
}
