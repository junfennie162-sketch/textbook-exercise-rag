<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { fetchHealth } from '../api/health'
import { fetchLlmStatus } from '../api/llm'
import BatchPanel from '../components/BatchPanel.vue'
import DocumentViewer from '../components/DocumentViewer.vue'
import EvalPanel from '../components/EvalPanel.vue'
import HistoryPanel from '../components/HistoryPanel.vue'
import SettingsPanel from '../components/SettingsPanel.vue'
import SolvePanel from '../components/SolvePanel.vue'
import UploadPanel from '../components/UploadPanel.vue'
import { useTheme } from '../composables/useTheme'
import { toast } from '../composables/useToast'
import { llmModeMeta } from '../utils/llmMode'

const tabs = [
  { id: 'upload', icon: '📚', label: '资料上传', hint: '上传教材与习题册，自动切块入库' },
  { id: 'viewer', icon: '📖', label: '资料查看', hint: '查看原文与页段，核对知识库内容' },
  { id: 'solve', icon: '✨', label: '解析生成', hint: '流式生成带引用标注的解析' },
  { id: 'history', icon: '🗃️', label: '历史记录', hint: '查看、筛选、删除与重新生成历史解析' },
  { id: 'batch', icon: '🗂️', label: '批量任务', hint: '多题批量生成与合并导出' },
  { id: 'eval', icon: '📊', label: '评测报告', hint: '完整率 / 引用命中 / 答案正确率 / 步骤验算' },
  { id: 'settings', icon: '⚙️', label: '模型设置', hint: '切换模型通道、调整生成与检索参数，保存即热生效' },
]

const { mode, modes, label: themeLabel, setMode } = useTheme()
const route = useRoute()
const router = useRouter()

const tabIds = tabs.map((tab) => tab.id)
// 面板状态写入 URL（/workspace?tab=eval），便于分享链接与直达
const initialTab = String(route.query.tab ?? '')
const activeTab = ref(tabIds.includes(initialTab) ? initialTab : 'upload')
let syncingTab = false
const docListVersion = ref(0)
const connected = ref(null) // null=检测中
const llmMode = ref('')
const llmModel = ref('')
const probing = ref(false)

const current = computed(() => tabs.find((tab) => tab.id === activeTab.value) ?? tabs[0])
const statusText = computed(() => {
  if (connected.value === null) return '正在检查后端…'
  return connected.value ? '后端已连接' : '等待后端连接'
})

// 生成模式徽标（与后端 /api/health 的 llm_mode 对应；文案与历史/评测面板共用）
const llmBadge = computed(() => {
  if (!connected.value) return null
  const meta = llmModeMeta(llmMode.value || 'cloud')
  const modelText = llmMode.value === 'mock' ? '' : (llmModel.value || '')
  return { ...meta, title: `${meta.title}（点击可探测模型连通性）`,
           text: `${meta.label}${modelText ? ` · ${modelText}` : ''}` }
})

async function checkHealth() {
  try {
    const result = await fetchHealth()
    connected.value = result.status === 'UP'
    llmMode.value = result.llm_mode ?? ''
    llmModel.value = result.llm_model ?? ''
  } catch {
    connected.value = false
  }
}

async function probeLlm() {
  if (probing.value) return
  probing.value = true
  try {
    const status = await fetchLlmStatus()
    if (!status.ok) {
      toast.error(`${status.error ?? '连接失败'}｜${status.hint ?? ''}`)
    } else if (status.mode !== 'mock' && status.model_present === false) {
      toast.error(`模型连接异常：${status.message}`)
    } else {
      toast.success(status.mode === 'mock'
        ? '离线模板模式正常：不访问任何外部服务'
        : `模型连接正常（${status.model}）`)
    }
  } catch (exc) {
    toast.error(`探测请求失败：${exc.message}`)
  } finally {
    probing.value = false
  }
}

function onUploaded() {
  docListVersion.value += 1
  activeTab.value = 'viewer'
}

watch(activeTab, (id) => {
  if (syncingTab) return
  const query = { ...route.query }
  if (id === 'upload') delete query.tab
  else query.tab = id
  router.replace({ query })
})

// 反向同步：URL 变化（历史记录「重新生成」跳转、前进后退、直接改地址）要回写当前面板
watch(() => route.query.tab, (value) => {
  const id = String(value ?? 'upload')
  if (!tabIds.includes(id) || id === activeTab.value) return
  syncingTab = true
  activeTab.value = id
  nextTick(() => {
    syncingTab = false
  })
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
        <button class="pill" type="button" :title="statusText" @click="checkHealth">
          <span
            class="dot"
            :class="connected === null ? '' : connected ? 'is-good' : 'is-bad'"
            aria-hidden="true"
          ></span>
          {{ statusText }}
        </button>
        <button
          v-if="llmBadge"
          class="pill"
          type="button"
          :title="llmBadge.title"
          @click="probeLlm"
        >
          <span aria-hidden="true">{{ llmBadge.icon }}</span>
          {{ probing ? '模型探测中…' : llmBadge.text }}
        </button>
      </header>

      <section class="page">
        <UploadPanel v-if="activeTab === 'upload'" @uploaded="onUploaded" />
        <DocumentViewer v-else-if="activeTab === 'viewer'" :version="docListVersion" />
        <SolvePanel v-else-if="activeTab === 'solve'" />
        <HistoryPanel v-else-if="activeTab === 'history'" />
        <BatchPanel v-else-if="activeTab === 'batch'" />
        <EvalPanel v-else-if="activeTab === 'eval'" />
        <SettingsPanel v-else @changed="checkHealth" />
      </section>
    </div>
  </div>
</template>
