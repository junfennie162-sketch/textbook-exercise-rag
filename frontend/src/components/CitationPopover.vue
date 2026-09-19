<script setup>
import { computed, onBeforeUnmount, onMounted } from 'vue'

import { toast } from '../composables/useToast'

const props = defineProps({
  sourceKey: { type: String, required: true },
  detail: { type: Object, required: true },
  anchor: { type: Object, default: () => ({ x: 0, y: 0 }) },
})

const emit = defineEmits(['close'])

const relevance = computed(() => Number(props.detail.relevance ?? 0))
const percent = computed(() => `${Math.round(relevance.value * 100)}%`)

const boxStyle = computed(() => {
  const width = Math.min(420, window.innerWidth * 0.88)
  const left = Math.max(12, Math.min(props.anchor.x, window.innerWidth - width - 16))
  const top = Math.max(12, Math.min(props.anchor.y + 10, window.innerHeight - 240))
  return { position: 'fixed', left: `${left}px`, top: `${top}px` }
})

function onKeydown(event) {
  if (event.key === 'Escape') emit('close')
}

async function copySnippet() {
  try {
    await navigator.clipboard.writeText(props.detail.text_snippet ?? '')
    toast.success('已复制原文片段')
  } catch {
    toast.error('复制失败：浏览器未授权剪贴板')
  }
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div class="popover" :style="boxStyle" role="dialog" :aria-label="`${sourceKey} 引用详情`">
    <div class="popover-head">
      <div class="stack-sm">
        <strong>{{ sourceKey }} · 引用详情</strong>
        <span class="muted">
          《{{ detail.source_file }}》{{ detail.chapter }} · {{ detail.section }} 第{{ detail.page_number }}页
        </span>
      </div>
      <button class="btn btn-ghost btn-sm" type="button" aria-label="关闭" @click="emit('close')">✕</button>
    </div>

    <div class="row" style="margin-top: 12px">
      <span class="badge" :class="detail.low_relevance ? 'is-warn' : 'is-good'">
        {{ detail.low_relevance ? '⚠️ 相关度偏低' : '✅ 相关度良好' }}
      </span>
      <span class="num strong">{{ percent }}</span>
      <span class="meter" style="flex: 1 1 80px" aria-hidden="true">
        <span class="meter-fill" :style="{ width: percent }"></span>
      </span>
    </div>

    <p v-if="detail.low_relevance" class="muted" style="margin-top: 10px">
      该来源与题目相关性低于预警阈值，建议人工复核依据是否贴合。
    </p>

    <blockquote class="popover-quote">{{ detail.text_snippet }}</blockquote>

    <div class="row" style="margin-top: 14px">
      <button class="btn btn-sm" type="button" @click="copySnippet">复制原文片段</button>
      <span class="muted">Esc 关闭</span>
    </div>
  </div>
</template>
