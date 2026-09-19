<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'

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

const rawText = ref('')
const running = ref(false)
const batchId = ref('')
const status = ref(null)
const exporting = ref(false)

let timer = null

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

async function onStart() {
  if (!questions.value.length) {
    toast.error('请先输入题目（每行一道）')
    return
  }
  running.value = true
  status.value = null
  try {
    const created = await createBatch(questions.value)
    batchId.value = created.batch_id
    toast.info(`批量任务已创建：共 ${questions.value.length} 题`)
    poll()
  } catch (err) {
    toast.error(`创建任务失败：${err.message}`)
    running.value = false
  }
}

async function poll() {
  try {
    const result = await getBatchStatus(batchId.value)
    status.value = result
    const stillRunning = (result.tasks ?? []).some((task) =>
      ['pending', 'running'].includes(task.status),
    )
    if (stillRunning) {
      timer = setTimeout(poll, 1500)
      return
    }
    running.value = false
    const detail = result.progress?.detail ?? {}
    toast.success(
      `批量任务结束：完成 ${detail.success ?? 0} · 失败 ${detail.failed ?? 0} · 中断 ${detail.cancelled ?? 0}`,
    )
  } catch (err) {
    toast.error(`查询任务状态失败：${err.message}`)
    running.value = false
  }
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
    anchor.click()
    URL.revokeObjectURL(url)
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
}

onBeforeUnmount(() => clearTimeout(timer))
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

        <p class="muted">批量任务为内存状态机，服务重启即清空；单题生成约需数秒，取决于模型响应速度。</p>
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
