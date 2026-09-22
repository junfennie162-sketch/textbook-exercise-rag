<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { streamSolve } from '../api/solve'
import CitationPopover from './CitationPopover.vue'
import { toast } from '../composables/useToast'
import { parseAnswerBlocks, parseInline } from '../utils/answer'

const EXAMPLES = [
  '计算：log₂ 8 + log₃ 9。',
  '已知等差数列 1, 4, 7, 10, …，求它的第 20 项 a₂₀。',
  '已知等比数列 2, 6, 18, …，求它的前 5 项和 S₅。',
]

const route = useRoute()

const question = ref('')
const generating = ref(false)
const answerText = ref('')
const sources = ref({})
const blocked = ref(null)
const llmError = ref(null)
const solutionId = ref('')
const stepCheck = ref(null)
// 终态：done=已保存 / stopped=用户停止 / error=失败 / incomplete=流被截断；null=进行中
const outcome = ref(null)
const popover = ref(null)
const answerBox = ref(null)

let controller = null
let unmounting = false

const sourceList = computed(() =>
  Object.entries(sources.value).map(([key, detail]) => ({ key, ...detail })),
)
const lowCount = computed(() => sourceList.value.filter((item) => item.low_relevance).length)
const answerBlocks = computed(() => parseAnswerBlocks(answerText.value))

function openCitation(label, event) {
  const detail = sources.value[label.slice(1, -1)]
  if (!detail) return
  const rect = event.currentTarget.getBoundingClientRect()
  popover.value = { label, detail, anchor: { x: rect.left, y: rect.bottom } }
}

function useExample(text) {
  question.value = text
}

async function onSolve() {
  const text = question.value.trim()
  if (!text || generating.value) return
  generating.value = true
  answerText.value = ''
  sources.value = {}
  blocked.value = null
  llmError.value = null
  solutionId.value = ''
  stepCheck.value = null
  outcome.value = null
  popover.value = null
  controller = new AbortController()

  try {
    await streamSolve(text, {
      signal: controller.signal,
      onEvent(event) {
        if (event.type === 'chunk') answerText.value += event.content
        else if (event.type === 'sources') sources.value = event.sources ?? {}
        else if (event.type === 'blocked') blocked.value = event
        else if (event.type === 'error') {
          llmError.value = event
          outcome.value = 'error'
        } else if (event.type === 'done') {
          if (event.status === 'ok') {
            outcome.value = 'done'
            solutionId.value = event.solution_id || ''
            stepCheck.value = event.step_check || null
          } else if (event.status === 'error') {
            outcome.value = 'error'
          }
          // done(blocked) 的展示交给 blocked 区块
        }
      },
    })
    if (outcome.value === 'done') {
      toast.success('解析生成完成')
    } else if (!blocked.value && outcome.value === null && answerText.value) {
      // 流被中途截断（连接断开/服务重启）：明确告知未保存，不再谎报成功
      outcome.value = 'incomplete'
      toast.error('生成中断：解析未保存，请重试')
    }
  } catch (err) {
    if (err.name === 'AbortError') {
      if (!unmounting) {
        outcome.value = 'stopped'
        toast.info('已停止本次生成')
      }
    } else {
      outcome.value = 'error'
      toast.error(`生成失败：${err.message}`)
    }
  } finally {
    generating.value = false
    controller = null
  }
}

function onStop() {
  controller?.abort()
}

async function copyAnswer() {
  try {
    await navigator.clipboard.writeText(answerText.value)
    toast.success('已复制解析全文')
  } catch {
    toast.error('复制失败：浏览器未授权剪贴板')
  }
}

function download(fmt) {
  if (!solutionId.value) {
    toast.error('解析尚未保存，无法导出')
    return
  }
  window.open(`/api/export/${solutionId.value}?fmt=${fmt}`, '_blank')
  toast.info(`正在导出 ${fmt === 'docx' ? 'Word' : 'Markdown'}`)
}

watch(answerText, async () => {
  if (!generating.value) return
  await nextTick()
  const box = answerBox.value
  if (box) box.scrollTop = box.scrollHeight
})

// 支持从历史记录「重新生成」带入题目：/workspace?tab=solve&q=题目
watch(
  () => route.query.q,
  (value) => {
    if (typeof value === 'string' && value.trim()) question.value = value.trim()
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  unmounting = true   // 切换面板导致的主动中止：不弹「已停止」提示打扰用户
  controller?.abort()
})
</script>

<template>
  <div class="stack">
    <section class="card">
      <div class="card-head">
        <h2>题目输入</h2>
        <span class="muted">{{ question.length }} 字</span>
      </div>
      <div class="card-body stack">
        <textarea
          v-model="question"
          rows="4"
          placeholder="粘贴或输入题目，例如：计算 log₂ 8 + log₃ 9。"
          aria-label="题目内容"
        ></textarea>

        <div class="row">
          <span class="muted">示例：</span>
          <button
            v-for="(example, index) in EXAMPLES"
            :key="index"
            class="btn btn-sm"
            type="button"
            @click="useExample(example)"
          >
            示例 {{ index + 1 }}
          </button>
        </div>

        <div class="row">
          <button
            class="btn btn-primary"
            type="button"
            :disabled="generating || !question.trim()"
            @click="onSolve"
          >
            <span v-if="generating" class="spinner" aria-hidden="true"></span>
            {{ generating ? '解析生成中…' : '生成解析' }}
          </button>
          <button v-if="generating" class="btn btn-danger" type="button" @click="onStop">停止生成</button>
          <template v-if="answerText && !generating">
            <button class="btn" type="button" @click="copyAnswer">复制解析</button>
            <template v-if="solutionId">
              <button class="btn" type="button" @click="download('docx')">导出 Word</button>
              <button class="btn" type="button" @click="download('md')">导出 Markdown</button>
            </template>
          </template>
        </div>
      </div>
    </section>

    <section v-if="blocked" class="alert is-warn">
      <span aria-hidden="true">⚠️</span>
      <div>
        <strong>{{ blocked.title }}</strong>
        <p class="muted">{{ blocked.detail }}</p>
        <p class="muted">{{ blocked.tip }}</p>
      </div>
    </section>

    <section v-if="llmError" class="alert is-warn">
      <span aria-hidden="true">🔌</span>
      <div>
        <strong>模型调用失败</strong>
        <p class="muted">{{ llmError.message }}</p>
        <p class="muted">{{ llmError.hint }}</p>
      </div>
    </section>

    <section v-if="generating && !answerText" class="card">
      <div class="card-body stack-sm">
        <span class="muted">正在检索教材依据并生成解析…</span>
        <span class="skeleton" style="height: 16px"></span>
        <span class="skeleton" style="height: 16px; width: 88%"></span>
        <span class="skeleton" style="height: 16px; width: 72%"></span>
      </div>
    </section>

    <section v-if="answerText" class="card">
      <div class="card-head">
        <h2>解析结果</h2>
        <div class="row">
          <span v-if="generating" class="badge is-accent"><span class="spinner" aria-hidden="true"></span>流式生成中</span>
          <span v-else-if="outcome === 'done'" class="badge is-good">✅ 生成完成（已保存）</span>
          <span v-else-if="outcome === 'error'" class="badge is-critical">⚠️ 生成失败（未保存）</span>
          <span v-else-if="outcome === 'stopped'" class="badge is-warn">⏹️ 已停止（未保存）</span>
          <span v-else-if="answerText" class="badge is-warn">⚠️ 未完成（未保存）</span>
        </div>
      </div>
      <div class="card-body">
        <div ref="answerBox" class="answer-stream">
          <template v-for="(block, index) in answerBlocks" :key="index">
            <h3 v-if="block.type === 'h'" class="ans-h">{{ block.text }}</h3>
            <p v-else-if="block.type === 'p'" class="ans-p">
              <template v-for="(seg, j) in parseInline(block.text)" :key="j">
                <button
                  v-if="seg.kind === 'citation'"
                  class="citation"
                  type="button"
                  @click="openCitation(seg.text, $event)"
                >{{ seg.text }}</button>
                <strong v-else-if="seg.kind === 'bold'">{{ seg.text }}</strong>
                <template v-else>{{ seg.text }}</template>
              </template>
            </p>
            <p v-else class="ans-li">
              <span class="ans-marker" aria-hidden="true">{{ block.marker }}</span>
              <span>
                <template v-for="(seg, j) in parseInline(block.text)" :key="j">
                  <button
                    v-if="seg.kind === 'citation'"
                    class="citation"
                    type="button"
                    @click="openCitation(seg.text, $event)"
                  >{{ seg.text }}</button>
                  <strong v-else-if="seg.kind === 'bold'">{{ seg.text }}</strong>
                  <template v-else>{{ seg.text }}</template>
                </template>
              </span>
            </p>
          </template>
        </div>

        <p v-if="stepCheck && stepCheck.checked" class="row" style="margin-top: 14px">
          <span class="badge" :class="stepCheck.ok ? 'is-good' : 'is-warn'">
            {{ stepCheck.ok ? '✅' : '⚠️' }} 步骤验算：可验算 {{ stepCheck.checked }} 步，通过 {{ stepCheck.passed }} 步
          </span>
          <span v-for="bad in stepCheck.failed" :key="bad" class="muted">可疑：{{ bad }}</span>
        </p>
      </div>
    </section>

    <section v-if="sourceList.length" class="card">
      <div class="card-head">
        <h2>引用来源</h2>
        <span class="muted">
          共 {{ sourceList.length }} 条<template v-if="lowCount">，其中 {{ lowCount }} 条相关度偏低</template>
        </span>
      </div>
      <div class="card-body">
        <ul class="source-list">
          <li
            v-for="item in sourceList"
            :key="item.key"
            class="source-item"
            :class="{ 'is-warn': item.low_relevance }"
          >
            <button class="citation" type="button" @click="openCitation(`[${item.key}]`, $event)">
              {{ item.key }}
            </button>
            <span class="strong">{{ item.source_file }}</span>
            <span class="muted">{{ item.chapter }} · {{ item.section }} · 第{{ item.page_number }}页</span>
            <span class="spacer"></span>
            <span class="badge" :class="item.low_relevance ? 'is-warn' : 'is-good'">
              {{ item.low_relevance ? '⚠️ 建议复核' : '✅ 相关度良好' }}
            </span>
            <span class="meter score-meter" :title="`相关度 ${item.relevance}`">
              <span class="meter-fill" :style="{ width: `${Math.round((item.relevance ?? 0) * 100)}%` }"></span>
            </span>
            <span class="muted num score">{{ (item.relevance ?? 0).toFixed(2) }}</span>
          </li>
        </ul>
      </div>
    </section>

    <CitationPopover
      v-if="popover"
      :source-key="popover.label"
      :detail="popover.detail"
      :anchor="popover.anchor"
      @close="popover = null"
    />
  </div>
</template>

<style scoped>
.answer-stream { max-height: 520px; overflow-y: auto; padding-right: var(--sp-2); }
.ans-h {
  margin: var(--sp-4) 0 var(--sp-2);
  font-size: 14px;
  font-weight: 700;
  color: var(--accent-ink);
}
.ans-h:first-child { margin-top: 0; }
.ans-p { margin: var(--sp-2) 0; line-height: 1.85; }
.ans-li { display: flex; gap: var(--sp-2); margin: var(--sp-1) 0; line-height: 1.8; }
.ans-marker { color: var(--ink-muted); font-weight: 600; }
.source-list { list-style: none; padding: 0; display: flex; flex-direction: column; gap: 2px; }
.score-meter { width: 72px; flex: 0 0 auto; }
.score { width: 34px; text-align: right; }
</style>
