<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { deleteSolution, getSolution, listSolutions } from '../api/solutions'
import { fetchGaps } from '../api/sources'
import { toast } from '../composables/useToast'
import { parseAnswerBlocks, parseInline } from '../utils/answer'
import { llmModeMeta } from '../utils/llmMode'

const router = useRouter()

const STATUS_OPTIONS = [
  { value: '', label: '全部状态' },
  { value: 'ok', label: '生成成功' },
  { value: 'blocked', label: '已拒答' },
]

const items = ref([])
const total = ref(0)
const keyword = ref('')
const statusFilter = ref('')
const limit = ref(50)          // 每次多加载 50 条（后端单次上限 500）
const MAX_LIMIT = 500
const loading = ref(false)
const detail = ref(null)
const detailLoading = ref('')
const confirmingId = ref('')
const deleting = ref(false)
const gaps = ref(null)

// 生成时使用的模型（参数面板可调后，历史记录需可追溯）
const shortModel = (value) => {
  const text = String(value || '').split('/').pop()
  return text.length > 26 ? `${text.slice(0, 26)}…` : text
}

const detailBlocks = computed(() => (detail.value ? parseAnswerBlocks(detail.value.answer_text) : []))
const detailSources = computed(() => Object.entries(detail.value?.sources ?? {}))
async function load() {
  loading.value = true
  try {
    const payload = await listSolutions({
      limit: limit.value,
      keyword: keyword.value.trim(),
      status: statusFilter.value,
    })
    items.value = payload.items ?? []
    total.value = payload.total ?? items.value.length
  } catch (err) {
    toast.error(err.message)
  } finally {
    loading.value = false
  }
}

function loadMore() {
  limit.value = Math.min(limit.value + 50, MAX_LIMIT)
  load()
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  limit.value = 50
  load()
}

function viewBlockedOnly() {
  // 缺口摘要卡片 → 只看被拒答的题（缺口对应记录）
  statusFilter.value = 'blocked'
  limit.value = 50
  load()
}

async function toggleDetail(item) {
  if (detail.value?.solution_id === item.solution_id) {
    detail.value = null
    return
  }
  detailLoading.value = item.solution_id
  try {
    detail.value = await getSolution(item.solution_id)
  } catch (err) {
    toast.error(err.message)
  } finally {
    detailLoading.value = ''
  }
}

function regenerate(item) {
  // 跳到解析生成面板并预填题目（面板状态写入 URL，可分享）
  router.push({ query: { tab: 'solve', q: item.question_text } })
  toast.info('已把题目带入解析生成面板，点击「生成解析」即可重新生成')
}

function exportItem(item, fmt) {
  // 复用后端导出接口（与解析面板同一套生成文件逻辑）
  window.open(`/api/export/${item.solution_id}?fmt=${fmt}`, '_blank')
  toast.info(`正在导出 ${fmt === 'docx' ? 'Word' : 'Markdown'}`)
}

async function onDelete(item) {
  deleting.value = true
  try {
    const result = await deleteSolution(item.solution_id)
    toast.success(result.message ?? '已删除该解析结果')
    confirmingId.value = ''
    if (detail.value?.solution_id === item.solution_id) detail.value = null
    await load()
  } catch (err) {
    toast.error(err.message)
  } finally {
    deleting.value = false
  }
}

function statusText(item) {
  if (item.status !== 'blocked') return '生成成功'
  return item.blocked_type === 'incomplete' ? '题目信息不完整' : '无教材依据'
}

// 拒答记录的原因与处理建议（与后端 guard.build_error_response 的文案保持一致）
const BLOCKED_INFO = {
  incomplete: {
    title: '题目信息不完整',
    tip: '请补充缺失的条件（如数值、前提）后重试；也可在「解析生成」面板用完整题干重新生成。',
  },
  no_evidence: {
    title: '未在教材中找到相关依据',
    tip: '本题考点可能超出当前教材范围。可先在「资料上传」补充对应章节语料，再点击「重新生成」重试。',
  },
}
const blockedInfo = (item) => BLOCKED_INFO[item?.blocked_type] ?? {
  title: '已拒答',
  tip: '题目缺少教材依据或信息不全，未生成解析内容。',
}

// 生成模式标签：文案与顶栏徽标共用一份口径（mock 离线模板 / ollama 本地 / cloud·live 云端）
const modeLabel = (item) => {
  const meta = llmModeMeta(item.mode)
  return `${meta.icon} ${meta.label}`
}

async function loadGaps() {
  try {
    gaps.value = await fetchGaps()
  } catch {
    gaps.value = null   // 缺口摘要是增强信息：失败时静默，不打扰主流程
  }
}

onMounted(() => {
  load()
  loadGaps()
})
</script>

<template>
  <div class="stack">
    <section class="card">
      <div class="card-head">
        <h2>历史解析结果</h2>
        <span class="muted">
          共 {{ total }} 条<template v-if="items.length < total">（已显示 {{ items.length }} 条）</template>
        </span>
      </div>
      <div class="card-body stack">
        <div class="row">
          <label class="field" style="flex: 1 1 260px">
            <input
              v-model="keyword"
              type="text"
              placeholder="按题干或解析内容筛选"
              aria-label="按题干或解析内容筛选"
              @keyup.enter="load"
            />
          </label>
          <label class="field" style="flex: 0 0 160px">
            <select v-model="statusFilter" aria-label="按状态筛选" @change="load">
              <option v-for="option in STATUS_OPTIONS" :key="option.value" :value="option.value">
                {{ option.label }}
              </option>
            </select>
          </label>
          <button class="btn btn-primary" type="button" :disabled="loading" @click="load">
            <span v-if="loading" class="spinner" aria-hidden="true"></span>
            {{ loading ? '查询中…' : '查询' }}
          </button>
          <button class="btn btn-ghost" type="button" @click="resetFilters">重置</button>
        </div>
        <p class="muted">
          说明：历史记录来自数据库（solutions 表）。「重新生成」会把题目带入解析生成面板；
          删除会同时清理该解析的引用来源。
        </p>

        <div v-if="gaps && gaps.total" class="gap-card">
          <div class="row-between">
            <span class="strong">🕳️ 教材缺口摘要</span>
            <span class="muted">
              共 {{ gaps.total }} 道题被拒答（无依据 {{ gaps.no_evidence }} · 信息不全 {{ gaps.incomplete }}）
            </span>
          </div>
          <p class="muted" style="margin: 4px 0">{{ gaps.hint }}</p>
          <div v-if="gaps.top_terms.length" class="row" style="gap: 6px; flex-wrap: wrap">
            <span class="muted">高频考点词：</span>
            <span v-for="term in gaps.top_terms" :key="term.term" class="badge">
              {{ term.term }} × {{ term.count }}
            </span>
          </div>
          <div class="row" style="margin-top: 6px">
            <button class="btn btn-sm" type="button" @click="viewBlockedOnly">只看这些被拒答的题</button>
          </div>
        </div>

        <div v-if="loading" class="stack-sm">
          <span class="skeleton" style="height: 46px"></span>
          <span class="skeleton" style="height: 46px"></span>
          <span class="skeleton" style="height: 46px"></span>
        </div>

        <template v-else-if="items.length">
          <ul class="history-list">
          <li v-for="item in items" :key="item.solution_id" class="history-item">
            <div class="row-between">
              <div class="stack-sm" style="flex: 1 1 320px; min-width: 0">
                <span class="question-text">{{ item.question_text }}</span>
                <span class="row" style="gap: 8px">
                  <span class="badge" :class="item.status === 'blocked' ? 'is-warn' : 'is-good'">
                    {{ item.status === 'blocked' ? '⚠️' : '✅' }} {{ statusText(item) }}
                  </span>
                  <span class="badge">{{ modeLabel(item) }}</span>
                  <span v-if="item.model" class="muted" :title="item.model">🤖 {{ shortModel(item.model) }}</span>
                  <span v-if="item.status !== 'blocked'" class="muted">引用 {{ item.sources_count }} 条</span>
                  <span class="muted num">{{ item.created_at }}</span>
                </span>
              </div>
              <div class="row" style="gap: 6px">
                <button class="btn btn-sm" type="button" @click="toggleDetail(item)">
                  {{ detail?.solution_id === item.solution_id ? '收起' : '查看详情' }}
                </button>
                <template v-if="item.status === 'ok'">
                  <button class="btn btn-sm" type="button" title="导出 Word" @click="exportItem(item, 'docx')">
                    Word
                  </button>
                  <button class="btn btn-sm" type="button" title="导出 Markdown" @click="exportItem(item, 'md')">
                    MD
                  </button>
                </template>
                <button
                  class="btn btn-sm"
                  type="button"
                  :title="item.status === 'blocked' ? '语料或参数更新后可重试本题' : '带入解析面板重新生成'"
                  @click="regenerate(item)"
                >
                  重新生成
                </button>
                <template v-if="confirmingId === item.solution_id">
                  <button class="btn btn-danger btn-sm" type="button" :disabled="deleting" @click="onDelete(item)">
                    {{ deleting ? '删除中…' : '确认删除' }}
                  </button>
                  <button class="btn btn-ghost btn-sm" type="button" @click="confirmingId = ''">取消</button>
                </template>
                <button
                  v-else
                  class="btn btn-ghost btn-sm"
                  type="button"
                  :aria-label="`删除 ${item.solution_id}`"
                  @click="confirmingId = item.solution_id"
                >
                  删除
                </button>
              </div>
            </div>

            <div v-if="detailLoading === item.solution_id" class="stack-sm" style="margin-top: 12px">
              <span class="skeleton" style="height: 16px"></span>
              <span class="skeleton" style="height: 16px; width: 80%"></span>
            </div>

            <div v-else-if="detail?.solution_id === item.solution_id" class="detail">
              <template v-if="detail.status === 'blocked'">
                <div class="stack-sm">
                  <span class="badge is-warn">⚠️ {{ blockedInfo(detail).title }}</span>
                  <p class="muted" style="margin: 0">{{ blockedInfo(detail).tip }}</p>
                  <p class="muted" style="margin: 0">
                    该题未生成解析内容（依据不足或题目信息不全），因此没有引用来源与步骤验算；
                    拒答属于边界处理的预期行为，不是系统故障。
                  </p>
                </div>
              </template>

              <template v-else>
              <div class="stack-sm">
                <template v-for="(block, index) in detailBlocks" :key="index">
                  <h3 v-if="block.type === 'h'" class="detail-heading">{{ block.text }}</h3>
                  <p v-else-if="block.type === 'p'" class="detail-line">
                    <template v-for="(seg, j) in parseInline(block.text)" :key="j">
                      <strong v-if="seg.kind === 'bold'">{{ seg.text }}</strong>
                      <template v-else>{{ seg.text }}</template>
                    </template>
                  </p>
                  <p v-else class="detail-line">
                    <span class="muted" aria-hidden="true">{{ block.marker }}</span>
                    <template v-for="(seg, j) in parseInline(block.text)" :key="j">
                      <strong v-if="seg.kind === 'bold'">{{ seg.text }}</strong>
                      <template v-else>{{ seg.text }}</template>
                    </template>
                  </p>
                </template>
              </div>

              <p v-if="detail.step_check && detail.step_check.checked" class="row" style="margin-top: 10px">
                <span class="badge" :class="detail.step_check.ok ? 'is-good' : 'is-warn'">
                  {{ detail.step_check.ok ? '✅' : '⚠️' }} 步骤验算：可验算
                  {{ detail.step_check.checked }} 步，通过 {{ detail.step_check.passed }} 步
                </span>
              </p>

              <div v-if="detailSources.length" class="stack-sm" style="margin-top: 12px">
                <h4>引用来源</h4>
                <ul class="source-list">
                  <li
                    v-for="[key, source] in detailSources"
                    :key="key"
                    class="source-item"
                    :class="{ 'is-warn': source.low_relevance }"
                  >
                    <span class="strong">{{ key }}</span>
                    <span>{{ source.source_file }}</span>
                    <span class="muted">{{ source.chapter }} · {{ source.section }} · 第{{ source.page_number }}页</span>
                    <span class="spacer"></span>
                    <span class="badge" :class="source.low_relevance ? 'is-warn' : 'is-good'">
                      {{ source.low_relevance ? '⚠️ 建议复核' : '✅ 相关度良好' }}
                    </span>
                    <span class="muted num">{{ (source.relevance ?? 0).toFixed(2) }}</span>
                  </li>
                </ul>
              </div>
              </template>

              <p class="muted" style="margin-top: 8px">
                解析 ID：{{ detail.solution_id }}<template v-if="detail.model"> · 生成模型：{{ detail.model }}</template>
              </p>
            </div>
          </li>
        </ul>

          <div v-if="items.length < total" class="row" style="justify-content: center; gap: 10px; margin-top: 10px">
            <button class="btn" type="button" :disabled="loading || limit >= MAX_LIMIT" @click="loadMore">
              <span v-if="loading" class="spinner" aria-hidden="true"></span>
              {{ loading ? '加载中…' : '加载更多' }}
            </button>
            <span class="muted">
              已显示 {{ items.length }} / 共 {{ total }} 条
              <template v-if="limit >= MAX_LIMIT">（已达单次上限，可用关键词或状态筛选定位）</template>
            </span>
          </div>
        </template>

        <p v-else class="empty">
          没有符合条件的解析记录。先在「解析生成」面板生成一条，或调整筛选条件。
        </p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.gap-card {
  padding: var(--sp-3) var(--sp-4);
  border: 1px dashed var(--line);
  border-radius: var(--r-md);
  background: var(--surface-sunken);
}
.history-list { list-style: none; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.history-item {
  padding: var(--sp-3);
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface);
}
.history-item:hover { background: var(--surface-2); }
.question-text {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-weight: 600;
  font-size: 13.5px;
  color: var(--ink);
}
.detail {
  margin-top: var(--sp-3);
  padding: var(--sp-3) var(--sp-4);
  border-radius: var(--r-sm);
  background: var(--surface-sunken);
}
.detail-heading { font-size: 13.5px; color: var(--accent-ink); margin-top: var(--sp-2); }
.detail-line { font-size: 13px; line-height: 1.8; margin: 2px 0; display: flex; gap: 6px; }
.source-list { list-style: none; padding: 0; display: flex; flex-direction: column; gap: 2px; }
</style>
