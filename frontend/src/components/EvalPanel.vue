<script setup>
import { computed, onMounted, ref } from 'vue'

const report = ref(null)
const loading = ref(false)
const error = ref('')
const view = ref('by_difficulty')

const BREAKDOWN_LABEL = { by_difficulty: '按难度', by_type: '按题型' }
const GROUP_HEAD = { by_difficulty: '难度', by_type: '题型' }

function pct(value) {
  return value === null || value === undefined ? '—' : `${(value * 100).toFixed(1)}%`
}

function widthOf(value) {
  return `${Math.max(0, Math.min(100, Math.round((value ?? 0) * 100)))}%`
}

function verdict(value) {
  return value === null || value === undefined ? '—' : value ? '✅' : '❌'
}

const kpis = computed(() => {
  const summary = report.value?.summary ?? {}
  return [
    { key: 'completeness', label: '解析完整率', value: summary.avg_completeness, hint: '有依据题的期望关键词覆盖率' },
    { key: 'citation', label: '引用命中率', value: summary.citation_hit_rate, hint: '有依据题返回引用 / 无依据题拒答' },
    { key: 'refusal', label: '无依据拒答率', value: summary.no_reference_refusal_rate, hint: '无教材依据时明确拒答' },
    {
      key: 'answer',
      label: '答案正确率',
      value: summary.answer_accuracy,
      hint: summary.answer_judged ? `${summary.answer_judged} 题可判定（抽取式比对）` : '暂无可判定题目',
    },
    {
      key: 'steps',
      label: '步骤验算通过率',
      value: summary.step_pass_rate,
      hint: `${summary.steps_passed ?? 0} / ${summary.steps_checked ?? 0} 步可验算`,
    },
    { key: 'pass', label: '通过率', value: summary.pass_rate, hint: '完整率与引用命中共同达标' },
  ]
})

const breakdown = computed(() => report.value?.breakdown?.[view.value] ?? {})

async function loadReport() {
  loading.value = true
  error.value = ''
  try {
    const response = await fetch('/api/eval/latest')
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const payload = await response.json()
    report.value = payload.available ? payload : null
    if (!payload.available) error.value = '还没有评测报告，请先运行 scripts/run_eval.py 或 scripts/regrade_solutions.py'
  } catch (err) {
    error.value = `读取评测报告失败：${err.message}`
  } finally {
    loading.value = false
  }
}

onMounted(loadReport)
</script>

<template>
  <div class="stack">
    <section class="card">
      <div class="card-head">
        <h2>评测概览</h2>
        <div class="row">
          <span v-if="report" class="muted">
            {{ report.summary.total }} 道样例题 · {{ report.summary.timestamp }}
          </span>
          <button class="btn btn-ghost" type="button" :disabled="loading" @click="loadReport">
            {{ loading ? '读取中…' : '刷新报告' }}
          </button>
        </div>
      </div>

      <div class="card-body stack">
        <div v-if="report?.mode === 'mock'" class="alert is-warn" role="status">
          <span aria-hidden="true">🧪</span>
          <div>
            <strong>本报告为离线模板模式（未调用大模型）</strong>
            <p class="muted">
              {{ report.mode_note || '解析由检索到的教材片段拼装而成，指标衡量的是离线模板子系统。' }}
            </p>
          </div>
        </div>

        <div v-if="loading" class="grid-auto">
          <span v-for="n in 6" :key="n" class="skeleton" style="height: 96px"></span>
        </div>

        <div v-else-if="report" class="grid-auto">
          <article v-for="kpi in kpis" :key="kpi.key" class="stat">
            <span class="stat-label">{{ kpi.label }}</span>
            <span class="stat-value num">{{ pct(kpi.value) }}</span>
            <span class="stat-hint">{{ kpi.hint }}</span>
            <span class="meter" aria-hidden="true">
              <span class="meter-fill" :style="{ width: widthOf(kpi.value) }"></span>
            </span>
          </article>
        </div>

        <p v-else class="empty">{{ error || '点击「刷新报告」加载评测结果。' }}</p>

        <p v-if="report" class="muted">
          报告文件：{{ report.file }}
          <template v-if="report.source?.type === 'regrade'">
            · 离线复评（未调用大模型，匹配 {{ report.source.matched }} / {{ report.source.solutions_total }} 份解析）
          </template>
        </p>
      </div>
    </section>

    <section v-if="report?.breakdown" class="card">
      <div class="card-head">
        <h2>分维度统计</h2>
        <div class="segmented" role="group" aria-label="分维度视角">
          <button
            v-for="(label, key) in BREAKDOWN_LABEL"
            :key="key"
            type="button"
            :class="{ 'is-active': view === key }"
            :aria-pressed="view === key"
            @click="view = key"
          >
            {{ label }}
          </button>
        </div>
      </div>
      <div class="card-body">
        <table v-if="Object.keys(breakdown).length" class="tbl">
          <thead>
            <tr>
              <th>{{ GROUP_HEAD[view] }}</th>
              <th class="num">题数</th>
              <th class="num">完整率</th>
              <th class="num">引用命中</th>
              <th class="num">答案正确率</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(metrics, name) in breakdown" :key="name">
              <td class="strong">{{ name }}</td>
              <td class="num">{{ metrics.count }}</td>
              <td class="num">{{ pct(metrics.avg_completeness) }}</td>
              <td class="num">{{ pct(metrics.citation_hit_rate) }}</td>
              <td class="num">{{ pct(metrics.answer_accuracy) }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="empty">报告未包含分维度统计（旧版报告请重新运行评测脚本）。</p>
      </div>
    </section>

    <section v-if="report?.details?.length" class="card">
      <div class="card-head">
        <h2>逐题明细</h2>
        <span class="muted">答案正确率仅统计有依据题；步骤验算只判纯数值等式</span>
      </div>
      <div class="card-body" style="padding: 0">
        <div class="table-scroll">
          <table class="tbl">
            <thead>
              <tr>
                <th>题目</th>
                <th>题型</th>
                <th>难度</th>
                <th class="num">完整率</th>
                <th>引用命中</th>
                <th>答案</th>
                <th class="num">步骤验算</th>
                <th>依据</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="detail in report.details" :key="detail.id">
                <td class="strong">{{ detail.id }}</td>
                <td>{{ detail.type }}</td>
                <td>{{ detail.difficulty }}</td>
                <td class="num">{{ detail.completeness }}</td>
                <td>{{ detail.citation_hit ? '✅' : '❌' }}</td>
                <td>{{ verdict(detail.answer_correct) }}</td>
                <td class="num">{{ detail.steps_passed ?? 0 }}/{{ detail.steps_checked ?? 0 }}</td>
                <td>{{ detail.status === 'blocked' ? '无依据（应拒答）' : '有依据' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.table-scroll { max-height: 480px; overflow: auto; border-radius: 0 0 var(--r-lg) var(--r-lg); }
</style>
