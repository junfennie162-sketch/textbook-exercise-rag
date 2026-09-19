import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import test from 'node:test'

const requiredFiles = [
  'index.html',
  'src/main.js',
  'src/App.vue',
  'src/router/index.js',
  'src/style.css',
  'src/api/health.js',
  'src/api/solve.js',
  'src/api/upload.js',
  'src/api/documents.js',
  'src/api/batch.js',
  'src/api/solutions.js',
  'src/composables/useTheme.js',
  'src/composables/useToast.js',
  'src/utils/answer.js',
  'src/views/ProjectHome.vue',
  'src/views/WorkspaceView.vue',
  'src/components/UploadPanel.vue',
  'src/components/DocumentViewer.vue',
  'src/components/SolvePanel.vue',
  'src/components/HistoryPanel.vue',
  'src/components/BatchPanel.vue',
  'src/components/EvalPanel.vue',
  'src/components/ToastHost.vue',
  'src/components/CitationPopover.vue',
]

test('包含可启动前端所需的最小入口文件', () => {
  for (const file of requiredFiles) {
    assert.equal(existsSync(new URL(`../${file}`, import.meta.url)), true, `缺少 ${file}`)
  }
})

test('样式表定义了浅色与深色两套设计令牌', () => {
  const css = readFileSync(new URL('../src/style.css', import.meta.url), 'utf8')
  for (const token of ['--surface', '--ink', '--accent', '--good', '--warning', '--critical', '--line']) {
    assert.ok(css.includes(`${token}:`), `样式表缺少令牌 ${token}`)
  }
  assert.ok(css.includes('[data-theme="dark"]'), '缺少手动深色主题作用域')
  assert.ok(css.includes('prefers-color-scheme: dark'), '缺少跟随系统的深色主题')
  assert.ok(css.includes('prefers-reduced-motion'), '缺少减弱动效适配')
})
