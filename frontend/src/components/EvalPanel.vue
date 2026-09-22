<script setup>
import { computed, onMounted, ref, watch } from 'vue'

import { fetchAblationReport, fetchEvalReport } from '../api/eval'
import { llmModeMeta } from '../utils/llmMode'

const report = ref(null)
const loading = ref(false)
const error = ref('')
const view = ref('by_difficulty')

// 面板视图：评测报告（生成质量指标） / 检索实验对比（消融实验，检索层代理指标）
const viewMode = ref('report')
const ablation = ref(null)
const ablationLoading = ref(false)
const ablationError = ref('')

const BREAKDOWN_LABEL = { by_difficulty: '按难度', by_type: '按题型' }
const GROUP_HEAD = { by_difficulty: '难度', by_type: '题型' }

// 报告生成模式徽标（与顶栏/历史共用口径）：mock 显著警示，避免把模板指标误当模型效果
const reportMode = computed(() => (report.value?.mode ? llmModeMeta(report.value.mode) : null))

// ---- 检索实验对比（消融）----
const ablationRows = computed(() => {
  const rows = ablation.value?.rows ?? []
  return [...rows].sort((a, b) =>
    (b['kw_coverage@k'] ?? 0) - (a['kw_coverage@k'] ?? 0)
      || (b['hit@1'] ?? 0) - (a['hit@1'] ?? 0),
  )
})
const bestRow = computed(() => ablationRows.value[0] ?? null)
const isBest = (row) => bestRow.value
  && row.chunk_size === bestRow.value.chunk_size
  && row.mode === bestRow.value.mode
  && row.rerank === bestRow.value.rerank
  && row.top_k === bestRow.value.top_k

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
    {
      key: 'delta',
      label: '去题干回声完整率',
      value: summary.avg_delta_completeness,
      hint: '去掉题干中已出现的关键词后的覆盖率，更贴近真实知识点覆盖',
    },
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
    const payload = await fetchEvalReport()
    report.value = payload.available ? payload : null
    if (!payload.available) error.value = '还没有评测报告，请先运行 scripts/run_eval.py 或 scripts/regrade_solutions.py'
  } catch (err) {
    error.value = `读取评测报告失败：${err.message}`
  } finally {
    loading.value = false
  }
}

async function loadAblation() {
  ablationLoading.value = true
  ablationError.value = ''
  try {
    const payload = await fetchAblationReport()
    ablation.value = payload.available ? payload : null
    if (!payload.available) {
      ablationError.value = '还没有消融实验报告，请先运行 scripts/run_ablation.py'
    }
  } catch (err) {
    ablationError.value = `读取消融报告失败：${err.message}`
  } finally {
    ablationLoading.value = false
  }
}

// 切到实验视图时按需加载（只读报告，不触发任何实验）
watch(viewMode, (mode) => {
  if (mode === 'experiment' && !ablation.value && !ablationLoading.value) loadAblation()
})

onMounted(loadReport)
</script>

<template>
  <div class="stack">
    <section class="card">
      <div class="card-head">
        <h2>评测视图</h2>
        <div class="segmented" role="group" aria-label="评测视图切换">
          <button
            type="button"
            :class="{ 'is-active': viewMode === 'report' }"
            :aria-pressed="viewMode === 'report'"
            @click="viewMode = 'report'"
          >
            生成质量评测
          </button>
          <button
            type="button"
            :class="{ 'is-active': viewMode === 'experiment' }"
            :aria-pressed="viewMode === 'experiment'"
            @click="viewMode = 'experiment'"
          >
            检索实验对比
          </button>
        </div>
      </div>
      <div class="card-body">
        <p class="muted" style="margin: 0">
          生成质量评测 = 60 题端到端指标（完整率 / 引用命中 / 答案 / 步骤验算）；
          检索实验对比 = 切块粒度 × 检索模式 × 重排 × Top-k 的离线消融（检索层代理指标，不调用大模型、零成本）。
        </p>
      </div>
    </section>

    <template v-if="viewMode === 'report'">
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

        <p v-if="report && reportMode" class="row" style="gap: 8px">
          <span class="badge" :class="reportMode.warn ? 'is-warn' : ''">
            {{ reportMode.icon }} 本报告由{{ reportMode.label }}生成
          </span>
          <span v-if="reportMode.warn" class="muted">
            模板解析由检索片段拼装、未调用大模型，指标仅验证流程与评测口径
          </span>
        </p>

        <p v-if="report && report.summary.errors" class="row" style="gap: 8px">
          <span class="badge is-critical">
            ⚠️ {{ report.summary.errors }} 题请求失败（已剔除出指标分母，建议重跑）
          </span>
        </p>

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
    </template>

    <template v-else>
      <section v-if="ablationLoading" class="card">
        <div class="card-body stack-sm">
          <span class="skeleton" style="height: 18px"></span>
          <span class="skeleton" style="height: 18px; width: 72%"></span>
        </div>
      </section>

      <section v-else-if="!ablation" class="card">
        <div class="card-body">
          <p class="empty">{{ ablationError || '暂无消融实验报告。' }}</p>
        </div>
      </section>

      <template v-else>
        <section class="card">
          <div class="card-head">
            <h2>实验概览</h2>
            <div class="row">
              <span class="muted">{{ ablation.rows?.length ?? 0 }} 组组合<template v-if="ablation.timestamp"> · {{ ablation.timestamp }}</template></span>
              <button class="btn btn-ghost" type="button" :disabled="ablationLoading" @click="loadAblation">
                {{ ablationLoading ? '读取中…' : '刷新报告' }}
              </button>
            </div>
          </div>
          <div class="card-body stack-sm">
            <p class="muted" style="margin: 0">{{ ablation.summary }}</p>
            <p class="muted" style="margin: 0">{{ ablation.note }}</p>
            <div class="row" style="gap: 8px; flex-wrap: wrap">
              <span class="badge">门控阈值 {{ ablation.similarity_threshold }}</span>
              <span v-if="ablation.corpus_units" class="badge">语料 {{ ablation.corpus_units }} 个单元</span>
              <span v-if="ablation.dataset_size" class="badge">评测集 {{ ablation.dataset_size }} 题</span>
              <span v-if="ablation.grid" class="badge">切块 {{ (ablation.grid.chunk_sizes || []).join(' / ') }}</span>
              <span v-if="ablation.grid" class="badge">top_k {{ (ablation.grid.top_ks || []).join(' / ') }}</span>
            </div>
            <p v-if="ablation.grounding" class="row" style="gap: 8px; margin: 0">
              <span class="badge" :class="ablation.grounding.grounding_rate === 1 ? 'is-good' : 'is-warn'">
                ✅ 关键词接地检查 {{ ablation.grounding.grounded_items }}/{{ ablation.grounding.graded_items }}
                （{{ pct(ablation.grounding.grounding_rate) }}）
              </span>
              <span v-if="ablation.grounding.ungrounded?.length" class="muted">
                未接地：{{ ablation.grounding.ungrounded.join('；') }}
              </span>
            </p>
            <p class="muted" style="margin: 0">报告文件：{{ ablation.file }}</p>
          </div>
        </section>

        <section v-if="bestRow" class="card">
          <div class="card-head">
            <h2>最优配置</h2>
            <span class="muted">按关键词覆盖优先、hit@1 次之</span>
          </div>
          <div class="card-body stack-sm">
            <p class="row" style="gap: 8px; margin: 0">
              <span class="badge is-good">
                chunk={{ bestRow.chunk_size }} · {{ bestRow.mode }} · rerank {{ bestRow.rerank }} · top_k={{ bestRow.top_k }}
              </span>
            </p>
            <p class="muted" style="margin: 0">
              关键词覆盖 {{ pct(bestRow['kw_coverage@k']) }} · hit@1 {{ pct(bestRow['hit@1']) }} ·
              拒答正确率 {{ pct(bestRow.refusal_correct) }}
            </p>
            <p class="muted" style="margin: 0">
              提示：代理指标只用于快速筛选；最终结论以「生成质量评测」视图的端到端指标为准。
            </p>
          </div>
        </section>

        <section class="card">
          <div class="card-head">
            <h2>组合明细</h2>
            <span class="muted">共 {{ ablationRows.length }} 组，按关键词覆盖降序</span>
          </div>
          <div class="card-body" style="padding: 0">
            <div class="table-scroll">
              <table class="tbl">
                <thead>
                  <tr>
                    <th class="num">切块</th>
                    <th>模式</th>
                    <th>重排</th>
                    <th class="num">top_k</th>
                    <th class="num">关键词覆盖@k</th>
                    <th class="num">hit@1</th>
                    <th class="num">拒答正确率</th>
                    <th class="num">平均最高余弦</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="row in ablationRows"
                    :key="`${row.chunk_size}-${row.mode}-${row.rerank}-${row.top_k}`"
                    :class="{ 'row-best': isBest(row) }"
                  >
                    <td class="num">{{ row.chunk_size }}</td>
                    <td>{{ row.mode }}</td>
                    <td>{{ row.rerank }}</td>
                    <td class="num">{{ row.top_k }}</td>
                    <td class="num">{{ pct(row['kw_coverage@k']) }}</td>
                    <td class="num">{{ pct(row['hit@1']) }}</td>
                    <td class="num">{{ pct(row.refusal_correct) }}</td>
                    <td class="num">{{ (row.avg_max_cos ?? 0).toFixed(3) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </section>
      </template>
    </template>
  </div>
</template>

<style scoped>
.table-scroll { max-height: 480px; overflow: auto; border-radius: 0 0 var(--r-lg) var(--r-lg); }
.row-best { background: var(--surface-2); font-weight: 600; }
</style>
