<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { deleteSolution, getSolution, listSolutions } from '../api/solutions'
import { toast } from '../composables/useToast'
import { parseAnswerBlocks, parseInline } from '../utils/answer'

const router = useRouter()

const STATUS_OPTIONS = [
  { value: '', label: '全部状态' },
  { value: 'ok', label: '生成成功' },
  { value: 'blocked', label: '已拒答' },
]

const items = ref([])
const keyword = ref('')
const statusFilter = ref('')
const loading = ref(false)
const detail = ref(null)
const detailLoading = ref('')
const confirmingId = ref('')
const deleting = ref(false)

const modeLabel = computed(() => (mode) => (mode === 'mock' ? '离线模板' : '真实模型'))
const detailBlocks = computed(() => (detail.value ? parseAnswerBlocks(detail.value.answer_text) : []))
const detailSources = computed(() => Object.entries(detail.value?.sources ?? {}))

async function load() {
  loading.value = true
  try {
    const payload = await listSolutions({
      keyword: keyword.value.trim(),
      status: statusFilter.value,
    })
    items.value = payload.items ?? []
  } catch (err) {
    toast.error(err.message)
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
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

onMounted(load)
</script>

<template>
  <div class="stack">
    <section class="card">
      <div class="card-head">
        <h2>历史解析结果</h2>
        <span class="muted">共 {{ items.length }} 条（最多显示最近 50 条）</span>
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

        <div v-if="loading" class="stack-sm">
          <span class="skeleton" style="height: 46px"></span>
          <span class="skeleton" style="height: 46px"></span>
          <span class="skeleton" style="height: 46px"></span>
        </div>

        <ul v-else-if="items.length" class="history-list">
          <li v-for="item in items" :key="item.solution_id" class="history-item">
            <div class="row-between">
              <div class="stack-sm" style="flex: 1 1 320px; min-width: 0">
                <span class="question-text">{{ item.question_text }}</span>
                <span class="row" style="gap: 8px">
                  <span class="badge" :class="item.status === 'blocked' ? 'is-warn' : 'is-good'">
                    {{ item.status === 'blocked' ? '⚠️' : '✅' }} {{ statusText(item) }}
                  </span>
                  <span class="badge" :class="item.mode === 'mock' ? 'is-warn' : 'is-accent'">
                    {{ item.mode === 'mock' ? '🧪' : '🤖' }} {{ modeLabel(item.mode) }}
                  </span>
                  <span class="muted">引用 {{ item.sources_count }} 条</span>
                  <span class="muted num">{{ item.created_at }}</span>
                </span>
              </div>
              <div class="row" style="gap: 6px">
                <button class="btn btn-sm" type="button" @click="toggleDetail(item)">
                  {{ detail?.solution_id === item.solution_id ? '收起' : '查看详情' }}
                </button>
                <button
                  class="btn btn-sm"
                  type="button"
                  :disabled="item.status === 'blocked'"
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
                    v-for="[key, ref] in detailSources"
                    :key="key"
                    class="source-item"
                    :class="{ 'is-warn': ref.low_relevance }"
                  >
                    <span class="strong">{{ key }}</span>
                    <span>{{ ref.source_file }}</span>
                    <span class="muted">{{ ref.chapter }} · {{ ref.section }} · 第{{ ref.page_number }}页</span>
                    <span class="spacer"></span>
                    <span class="badge" :class="ref.low_relevance ? 'is-warn' : 'is-good'">
                      {{ ref.low_relevance ? '⚠️ 建议复核' : '✅ 相关度良好' }}
                    </span>
                    <span class="muted num">{{ (ref.relevance ?? 0).toFixed(2) }}</span>
                  </li>
                </ul>
              </div>
              <p class="muted" style="margin-top: 8px">
                解析 ID：{{ detail.solution_id }} · 生成模式：{{ modeLabel(detail.mode) }}
              </p>
            </div>
          </li>
        </ul>

        <p v-else class="empty">
          没有符合条件的解析记录。先在「解析生成」面板生成一条，或调整筛选条件。
        </p>
      </div>
    </section>
  </div>
</template>

<style scoped>
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
