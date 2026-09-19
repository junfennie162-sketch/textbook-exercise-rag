import assert from 'node:assert/strict'
import test from 'node:test'

import { extractCitationKeys, parseAnswerBlocks, parseInline } from '../src/utils/answer.js'

test('parseAnswerBlocks 识别标题、列表与段落', () => {
  const text = [
    '## 解题思路',
    '利用对数的定义求解 [来源1]。',
    '',
    '## 解题步骤',
    '1. 明确底数与真数',
    '2. 计算指数',
    '- 验证结果',
  ].join('\n')

  const blocks = parseAnswerBlocks(text)
  assert.deepEqual(
    blocks.map((block) => block.type),
    ['h', 'p', 'h', 'li', 'li', 'li'],
  )
  assert.equal(blocks[0].text, '解题思路')
  assert.equal(blocks[1].text, '利用对数的定义求解 [来源1]。')
  assert.equal(blocks[3].marker, '1.')
  assert.equal(blocks[3].text, '明确底数与真数')
  assert.equal(blocks[5].marker, '•')
  assert.equal(blocks[5].text, '验证结果')
})

test('parseAnswerBlocks 合并多行段落并容忍空输入', () => {
  assert.deepEqual(parseAnswerBlocks(''), [])
  assert.deepEqual(parseAnswerBlocks(null), [])
  assert.deepEqual(parseAnswerBlocks('第一行\n第二行'), [{ type: 'p', text: '第一行 第二行' }])
})

test('parseAnswerBlocks 支持未结束的流式片段', () => {
  // 流式生成时最后一块可能不完整，不能抛错
  const blocks = parseAnswerBlocks('## 参考答案\n58')
  assert.deepEqual(blocks, [
    { type: 'h', text: '参考答案' },
    { type: 'p', text: '58' },
  ])
})

test('parseInline 切出引用与加粗片段', () => {
  const segments = parseInline('由**对数定义** [来源1] 可知，参见 [来源12]。')
  assert.deepEqual(segments, [
    { kind: 'text', text: '由' },
    { kind: 'bold', text: '对数定义' },
    { kind: 'text', text: ' ' },
    { kind: 'citation', text: '[来源1]' },
    { kind: 'text', text: ' 可知，参见 ' },
    { kind: 'citation', text: '[来源12]' },
    { kind: 'text', text: '。' },
  ])
})

test('parseInline 不把非引用方括号或单个星号当标记', () => {
  assert.deepEqual(parseInline('区间 [0, 1] 与 [来源]'), [
    { kind: 'text', text: '区间 [0, 1] 与 [来源]' },
  ])
  assert.deepEqual(parseInline('3 * 4 = 12'), [{ kind: 'text', text: '3 * 4 = 12' }])
})

test('extractCitationKeys 汇总去重', () => {
  const keys = extractCitationKeys('[来源1] 与 [来源2] 再次引用 [来源1]')
  assert.deepEqual([...keys].sort(), ['来源1', '来源2'])
  assert.equal(extractCitationKeys('没有引用').size, 0)
})
