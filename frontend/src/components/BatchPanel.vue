<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { cancelBatch, createBatch, getBatchStatus } from '../api/batch'
import { toast } from '../composables/useToast'

const STATUS_LABEL = {
  pending: '排队中',
  running: '生成中',
  success: '完成',
  failed: '失败',
  cancelled: '已中断',
}

const STATUS_BADGE = {
  pending: '',
  running: 'is-accent',
  success: 'is-good',
  failed: 'is-critical',
  cancelled: 'is-warn',
}

const POLL_INTERVAL = 1500
const MAX_POLL_RETRIES = 3          // 连续失败几次后停止自动重试（避免无限弹错）
const STORAGE_KEY = 'batch-job-id'  // 记住 batch_id：切换面板/刷新后可重新接管进度

const rawText = ref('')
const running = ref(false)
const batchId = ref('')
const status = ref(null)
const exporting = ref(false)
const pollError = ref(false)

let timer = null
let disposed = false
let consecutiveErrors = 0

const questions = computed(() =>
  rawText.value
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean),
)

const progressPercent = computed(() => {
  const progress = status.value?.progress
  if (!progress?.total) return 0
  return Math.round((progress.done / progress.total) * 100)
})

const exportableIds = computed(() =>
  (status.value?.tasks ?? []).filter((task) => task.solution_id).map((task) => task.solution_id),
)

function rememberJob(id) {
  try {
    if (id) localStorage.setItem(STORAGE_KEY, id)
    else localStorage.removeItem(STORAGE_KEY)
  } catch {
    // 隐私模式等场景下 localStorage 不可用：仅影响"切换面板后接管"，不影响主流程
  }
}

function schedulePoll(delay = POLL_INTERVAL) {
  clearTimeout(timer)
  timer = setTimeout(poll, delay)
}

async function onStart() {
  if (!questions.value.length) {
    toast.error('请先输入题目（每行一道）')
    return
  }
  running.value = true
  pollError.value = false
  consecutiveErrors = 0
  status.value = null
  try {
    const created = await createBatch(questions.value)
    batchId.value = created.batch_id
    rememberJob(created.batch_id)
    toast.info(`批量任务已创建：共 ${questions.value.length} 题`)
    schedulePoll()
  } catch (err) {
    toast.error(`创建任务失败：${err.message}`)
    running.value = false
  }
}

function finishToast(result) {
  const detail = result.progress?.detail ?? {}
  const success = detail.success ?? 0
  const failed = detail.failed ?? 0
  const cancelled = detail.cancelled ?? 0
  const text = `批量任务结束：完成 ${success} · 失败 ${failed} · 中断 ${cancelled}`
  if (result.status === 'failed' || (success === 0 && failed > 0)) {
    toast.error(`${text}（全部失败，请检查模型通道后重试）`)
  } else if (failed > 0 || cancelled > 0) {
    toast.info(text)
  } else {
    toast.success(text)
  }
}

async function poll({ silent = false } = {}) {
  try {
    const result = await getBatchStatus(batchId.value)
    if (disposed) return
    consecutiveErrors = 0
    pollError.value = false
    status.value = result
    const stillRunning = (result.tasks ?? []).some((task) =>
      ['pending', 'running'].includes(task.status),
    )
    if (stillRunning) {
      running.value = true
      schedulePoll()
      return
    }
    running.value = false
    rememberJob('')
    if (!silent) finishToast(result)
  } catch (err) {
    if (disposed) return
    consecutiveErrors += 1
    if (consecutiveErrors <= MAX_POLL_RETRIES) {
      // 瞬时失败（网络抖动/后端重启中）：退避重试，任务在服务端照常运行
      schedulePoll(POLL_INTERVAL * consecutiveErrors)
      return
    }
    pollError.value = true
    running.value = false
    toast.error(`查询任务状态失败：${err.message}。任务可能仍在后台运行，可点击「重新连接进度」`)
  }
}

async function reconnect() {
  pollError.value = false
  consecutiveErrors = 0
  running.value = true
  await poll()
}

async function onCancel() {
  if (!batchId.value) return
  try {
    await cancelBatch(batchId.value)
    toast.info('已请求中断，等待当前题目收尾')
  } catch (err) {
    toast.error(`中断失败：${err.message}`)
  }
}

async function exportSelected(fmt) {
  if (!exportableIds.value.length) {
    toast.error('还没有可导出的解析结果')
    return
  }
  exporting.value = true
  try {
    const response = await fetch(`/api/export/file?fmt=${fmt}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(exportableIds.value),
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `solutions_export.${fmt}`
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    // 立即 revoke 会让部分浏览器取消下载，延迟释放更稳
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    toast.success(`已导出 ${exportableIds.value.length} 份解析`)
  } catch (err) {
    toast.error(`导出失败：${err.message}`)
  } finally {
    exporting.value = false
  }
}

function resetForm() {
  status.value = null
  batchId.value = ''
  pollError.value = false
  rememberJob('')
}

onMounted(async () => {
  // 面板重挂载（切换标签页/刷新）后接管仍在运行的任务，避免"任务在跑但界面已失联"
  let saved = ''
  try {
    saved = localStorage.getItem(STORAGE_KEY) ?? ''
  } catch {
    saved = ''
  }
  if (!saved) return
  batchId.value = saved
  running.value = true
  await poll({ silent: true })   // 若任务已结束：静默展示结果，不重复弹完成提示
})

onBeforeUnmount(() => {
  disposed = true
  clearTimeout(timer)
})
</script>

<template>
  <div class="stack">
    <section class="card">
      <div class="card-head">
        <h2>批量题目</h2>
        <span class="muted">已输入 {{ questions.length }} 题（每行一道）</span>
      </div>
      <div class="card-body stack">
        <textarea
          v-model="rawText"
          rows="6"
          placeholder="每行一道题目，例如：&#10;计算 log₂ 8 + log₃ 9&#10;已知等差数列 1,4,7,… 求第 20 项"
          aria-label="批量题目输入"
        ></textarea>

        <div class="row">
          <button class="btn btn-primary" type="button" :disabled="running || !questions.length" @click="onStart">
            <span v-if="running" class="spinner" aria-hidden="true"></span>
            {{ running ? '任务执行中…' : '开始批量生成' }}
          </button>
          <button v-if="running" class="btn btn-danger" type="button" @click="onCancel">中断任务</button>
          <button v-if="pollError" class="btn" type="button" @click="reconnect">重新连接进度</button>
          <template v-if="status && !running">
            <button class="btn" type="button" :disabled="exporting" @click="exportSelected('docx')">
              导出 Word
            </button>
            <button class="btn" type="button" :disabled="exporting" @click="exportSelected('md')">
              导出 Markdown
            </button>
            <button class="btn btn-ghost" type="button" @click="resetForm">清空结果</button>
          </template>
        </div>

        <p class="muted">
          批量任务为内存状态机，服务重启即清空；单题生成约需数秒，取决于模型响应速度。
          切换到其他面板后会保留任务编号并自动恢复进度跟踪。
        </p>
      </div>
    </section>

    <section v-if="status" class="card">
      <div class="card-head">
        <h2>执行进度</h2>
        <span class="muted num">
          {{ status.progress.done }} / {{ status.progress.total }}（{{ progressPercent }}%）
        </span>
      </div>
      <div class="card-body stack">
        <div class="meter meter-lg" role="progressbar" :aria-valuenow="progressPercent" aria-valuemin="0" aria-valuemax="100">
          <div class="meter-fill" :style="{ width: `${progressPercent}%` }"></div>
        </div>

        <div class="row">
          <span class="badge is-good">✅ 完成 {{ status.progress.detail.success || 0 }}</span>
          <span class="badge is-critical">⚠️ 失败 {{ status.progress.detail.failed || 0 }}</span>
          <span class="badge is-warn">⏹️ 中断 {{ status.progress.detail.cancelled || 0 }}</span>
          <span v-if="status.progress.detail.pending" class="badge">
            排队 {{ status.progress.detail.pending }}
          </span>
        </div>

        <ul class="task-list">
          <li v-for="task in status.tasks" :key="task.question_id" class="task-item">
            <span class="badge" :class="STATUS_BADGE[task.status]">{{ STATUS_LABEL[task.status] }}</span>
            <span class="task-text">{{ task.question }}</span>
            <span class="spacer"></span>
            <span v-if="task.blocked_type === 'incomplete'" class="muted">题目信息不完整</span>
            <span v-else-if="task.blocked_type === 'no_evidence'" class="muted">无教材依据</span>
            <span v-else-if="task.error" class="muted">{{ task.error }}</span>
            <span v-else-if="task.solution_id" class="muted num">已保存 {{ task.solution_id }}</span>
          </li>
        </ul>
      </div>
    </section>
  </div>
</template>

<style scoped>
.task-list { list-style: none; padding: 0; display: flex; flex-direction: column; gap: 2px; }
.task-item {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-2) var(--sp-3);
  border-radius: var(--r-sm);
  font-size: 13px;
}
.task-item:hover { background: var(--surface-2); }
.task-text {
  max-width: 52ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
