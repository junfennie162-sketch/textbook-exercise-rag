<script setup>
import { computed, onMounted, ref } from 'vue'

import { fetchHealth } from '../api/health'
import { listDocuments } from '../api/upload'
import { useTheme } from '../composables/useTheme'

const { mode, modes, setMode } = useTheme()

const connected = ref(null)
const mockMode = ref(false)
const docs = ref([])

const chunks = computed(() => docs.value.reduce((sum, doc) => sum + (doc.chunks_count || 0), 0))
const textbooks = computed(() => docs.value.filter((doc) => doc.doc_type === 'textbook').length)
const exercises = computed(() => docs.value.filter((doc) => doc.doc_type === 'exercise').length)

const capabilities = [
  { icon: '📤', title: '资料入库', text: 'PDF / Word 上传，按页段解析并切块，保留章节与页码来源。' },
  { icon: '🔍', title: '混合检索', text: '向量稠密召回 + BM25 稀疏召回 → RRF 融合 → 轻量重排。' },
  { icon: '✨', title: '流式解析', text: '思路 / 步骤 / 易错点 / 答案四段结构，SSE 逐段呈现。' },
  { icon: '🔗', title: '引用追溯', text: '[来源N] 标注 + 相关度预警，可点开核对原文与页码。' },
  { icon: '🧮', title: '质量校验', text: '参考答案抽取与数值步骤验算，只提示不误判。' },
  { icon: '📊', title: '量化评测', text: '完整率、引用命中率、答案正确率、步骤验算率与分维度统计。' },
]

onMounted(async () => {
  try {
    const health = await fetchHealth()
    connected.value = health.status === 'UP'
    mockMode.value = health.llm_mock === true
  } catch {
    connected.value = false
  }
  try {
    docs.value = await listDocuments()
  } catch {
    docs.value = []
  }
})
</script>

<template>
  <main class="home">
    <div class="home-inner">
      <header class="row-between">
        <span class="pill">
          <span class="brand-mark" aria-hidden="true">✦</span>
          RAG 教材习题解析生成器
        </span>
        <div class="segmented" role="group" aria-label="主题切换">
          <button
            v-for="item in modes"
            :key="item"
            type="button"
            :class="{ 'is-active': mode === item }"
            :aria-pressed="mode === item"
            @click="setMode(item)"
          >
            {{ item === 'auto' ? '自动' : item === 'light' ? '浅色' : '深色' }}
          </button>
        </div>
      </header>

      <section class="hero">
        <p class="eyebrow">RETRIEVAL · AUGMENTED · GENERATION</p>
        <h1>把习题和教材章节放在一起，<br />生成有据可查的解析</h1>
        <p class="intro">
          上传习题册与教材 → 切块入库 → 检索依据 → 流式生成解析并标注引用 → 导出交付。
          题目信息不全或没有教材依据时明确提示，不凭空编造步骤。
        </p>
        <div class="row">
          <RouterLink class="btn btn-primary" to="/workspace">进入解析工作台 →</RouterLink>
          <span class="pill">
            <span
              class="dot"
              :class="connected === null ? '' : connected ? 'is-good' : 'is-bad'"
              aria-hidden="true"
            ></span>
            {{ connected === null ? '正在检查后端…' : connected ? '后端已连接' : '等待后端连接' }}
          </span>
          <span
            v-if="mockMode"
            class="badge is-warn"
            title="未调用大模型：解析由检索到的教材片段拼装而成"
          >
            🧪 离线模板模式
          </span>
        </div>
      </section>

      <section class="grid-auto">
        <article class="stat">
          <span class="stat-label">知识库文档</span>
          <span class="stat-value num">{{ docs.length }}</span>
          <span class="stat-hint">教材 {{ textbooks }} · 习题册 {{ exercises }}</span>
        </article>
        <article class="stat">
          <span class="stat-label">知识块总数</span>
          <span class="stat-value num">{{ chunks }}</span>
          <span class="stat-hint">切块粒度 600 字 / 重叠 80 字</span>
        </article>
        <article class="stat">
          <span class="stat-label">检索路线</span>
          <span class="stat-value">混合</span>
          <span class="stat-hint">向量 + BM25 → RRF → 轻量重排</span>
        </article>
      </section>

      <section class="cap-grid">
        <article v-for="item in capabilities" :key="item.title" class="card">
          <div class="card-body stack-sm">
            <span aria-hidden="true" style="font-size: 22px">{{ item.icon }}</span>
            <h3>{{ item.title }}</h3>
            <p class="muted">{{ item.text }}</p>
          </div>
        </article>
      </section>

      <p class="muted">
        提示：先在「资料上传」导入教材与习题册，再到「解析生成」粘贴题目；批量与评测在对应面板中查看。
      </p>
    </div>
  </main>
</template>

<style scoped>
.home {
  min-height: 100vh;
  padding: var(--sp-6) var(--sp-5);
  background:
    radial-gradient(1200px 400px at 20% -10%, var(--accent-soft), transparent 70%),
    var(--page);
}
.home-inner {
  display: flex;
  flex-direction: column;
  gap: var(--sp-6);
  width: 100%;
  max-width: 1080px;
  margin: 0 auto;
}
.hero { display: flex; flex-direction: column; gap: var(--sp-4); padding: var(--sp-6) 0; }
.eyebrow {
  color: var(--accent);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.16em;
}
.hero h1 {
  font-size: clamp(28px, 4.4vw, 44px);
  letter-spacing: -0.03em;
  line-height: 1.15;
}
.intro { max-width: 680px; color: var(--ink-2); font-size: 15.5px; line-height: 1.85; }
.cap-grid { display: grid; gap: var(--sp-4); grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }
@media (min-width: 980px) {
  .cap-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
</style>
