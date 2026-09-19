/**
 * 解析文本渲染工具：把流式返回的 Markdown 片段切成可渲染块，并识别 [来源N] 引用。
 *
 * 纯函数、无副作用，便于单元测试；组件只负责展示，不承担解析逻辑。
 */

const HEADING = /^#{1,4}\s*(.+)$/
const BULLET = /^[-*]\s+(.+)$/
const NUMBERED = /^(\d+)[.、)]\s+(.+)$/
const CITATION_EXACT = /^\[来源\d+\]$/
const BOLD_EXACT = /^\*\*[^*]+\*\*$/
// 行内元素：Markdown 加粗 **文字** 与引用标记 [来源N]
const INLINE_SPLIT = /(\*\*[^*]+\*\*|\[来源\d+\])/

/**
 * 把解析文本切成有序渲染块：标题 / 列表项 / 段落。
 * @param {string} text 流式累积的解析文本
 * @returns {Array<{type: 'h'|'li'|'p', text: string, marker?: string}>}
 */
export function parseAnswerBlocks(text) {
  const blocks = []
  let paragraph = []

  const flush = () => {
    if (paragraph.length) {
      blocks.push({ type: 'p', text: paragraph.join(' ') })
      paragraph = []
    }
  }

  for (const rawLine of String(text ?? '').split('\n')) {
    const line = rawLine.trim()
    if (!line) {
      flush()
      continue
    }

    const heading = HEADING.exec(line)
    if (heading) {
      flush()
      blocks.push({ type: 'h', text: heading[1] })
      continue
    }

    const bullet = BULLET.exec(line)
    if (bullet) {
      flush()
      blocks.push({ type: 'li', marker: '•', text: bullet[1] })
      continue
    }

    const numbered = NUMBERED.exec(line)
    if (numbered) {
      flush()
      blocks.push({ type: 'li', marker: `${numbered[1]}.`, text: numbered[2] })
      continue
    }

    paragraph.push(line)
  }

  flush()
  return blocks
}

/**
 * 把一段文本切成行内片段：普通文本 / **加粗** / [来源N] 引用，供模板分别渲染。
 * @param {string} text
 * @returns {Array<{kind: 'text'|'bold'|'citation', text: string}>}
 */
export function parseInline(text) {
  return String(text ?? '')
    .split(INLINE_SPLIT)
    .filter((part) => part !== '')
    .map((part) => {
      if (CITATION_EXACT.test(part)) return { kind: 'citation', text: part }
      if (BOLD_EXACT.test(part)) return { kind: 'bold', text: part.slice(2, -2) }
      return { kind: 'text', text: part }
    })
}

/**
 * 提取文本中出现的全部引用键（如 "来源1"），用于核对引用是否都在来源表内。
 * @param {string} text
 * @returns {Set<string>}
 */
export function extractCitationKeys(text) {
  const keys = new Set()
  for (const match of String(text ?? '').matchAll(/\[(来源\d+)\]/g)) {
    keys.add(match[1])
  }
  return keys
}
