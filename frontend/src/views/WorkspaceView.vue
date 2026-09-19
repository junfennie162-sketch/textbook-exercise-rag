<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { fetchHealth } from '../api/health'
import BatchPanel from '../components/BatchPanel.vue'
import DocumentViewer from '../components/DocumentViewer.vue'
import EvalPanel from '../components/EvalPanel.vue'
import HistoryPanel from '../components/HistoryPanel.vue'
import SolvePanel from '../components/SolvePanel.vue'
import UploadPanel from '../components/UploadPanel.vue'
import { useTheme } from '../composables/useTheme'

const tabs = [
  { id: 'upload', icon: '📚', label: '资料上传', hint: '上传教材与习题册，自动切块入库' },
  { id: 'viewer', icon: '📖', label: '资料查看', hint: '查看原文与页段，核对知识库内容' },
  { id: 'solve', icon: '✨', label: '解析生成', hint: '流式生成带引用标注的解析' },
  { id: 'history', icon: '🗃️', label: '历史记录', hint: '查看、筛选、删除与重新生成历史解析' },
  { id: 'batch', icon: '🗂️', label: '批量任务', hint: '多题批量生成与合并导出' },
  { id: 'eval', icon: '📊', label: '评测报告', hint: '完整率 / 引用命中 / 答案正确率 / 步骤验算' },
]

const { mode, modes, label: themeLabel, setMode } = useTheme()
const route = useRoute()
const router = useRouter()

const tabIds = tabs.map((tab) => tab.id)
// 面板状态写入 URL（/workspace?tab=eval），便于分享链接与直达
const initialTab = String(route.query.tab ?? '')
const activeTab = ref(tabIds.includes(initialTab) ? initialTab : 'upload')
const docListVersion = ref(0)
const connected = ref(null) // null=检测中
const mockMode = ref(false)

const current = computed(() => tabs.find((tab) => tab.id === activeTab.value) ?? tabs[0])
const statusText = computed(() => {
  if (connected.value === null) return '正在检查后端…'
  return connected.value ? '后端已连接' : '等待后端连接'
})

async function checkHealth() {
  try {
    const result = await fetchHealth()
    connected.value = result.status === 'UP'
    mockMode.value = result.llm_mock === true
  } catch {
    connected.value = false
  }
}

function onUploaded() {
  docListVersion.value += 1
  activeTab.value = 'viewer'
}

watch(activeTab, (id) => {
  const query = { ...route.query }
  if (id === 'upload') delete query.tab
  else query.tab = id
  router.replace({ query })
})

onMounted(checkHealth)
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <RouterLink to="/" class="brand" style="text-decoration: none; color: inherit">
        <span class="brand-mark" aria-hidden="true">✦</span>
        <span class="brand-text">
          <span class="brand-name">教材习题解析生成器</span>
          <span class="brand-sub">RAG WORKBENCH</span>
        </span>
      </RouterLink>

      <nav class="nav" aria-label="功能导航">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          class="nav-item"
          :class="{ 'is-active': activeTab === tab.id }"
          type="button"
          :aria-current="activeTab === tab.id ? 'page' : undefined"
          @click="activeTab = tab.id"
        >
          <span class="nav-icon" aria-hidden="true">{{ tab.icon }}</span>
          <span class="nav-label">{{ tab.label }}</span>
        </button>
      </nav>

      <div class="spacer"></div>

      <div class="stack-sm">
        <span class="muted">外观</span>
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
        <span class="muted">当前：{{ themeLabel }}</span>
      </div>
    </aside>

    <div class="content">
      <header class="topbar">
        <div>
          <h1>{{ current.label }}</h1>
          <p class="topbar-sub">{{ current.hint }}</p>
        </div>
        <div class="spacer"></div>
        <span
          v-if="mockMode"
          class="badge is-warn"
          title="未调用大模型：解析由检索到的教材片段拼装而成"
        >
          🧪 离线模板模式
        </span>
        <button class="pill" type="button" :title="statusText" @click="checkHealth">
          <span
            class="dot"
            :class="connected === null ? '' : connected ? 'is-good' : 'is-bad'"
            aria-hidden="true"
          ></span>
          {{ statusText }}
        </button>
      </header>

      <section class="page">
        <UploadPanel v-if="activeTab === 'upload'" @uploaded="onUploaded" />
        <DocumentViewer v-else-if="activeTab === 'viewer'" :version="docListVersion" />
        <SolvePanel v-else-if="activeTab === 'solve'" />
        <HistoryPanel v-else-if="activeTab === 'history'" />
        <BatchPanel v-else-if="activeTab === 'batch'" />
        <EvalPanel v-else />
      </section>
    </div>
  </div>
</template>
