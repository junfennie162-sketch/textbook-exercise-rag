<script setup>
import { computed, onMounted, ref } from 'vue'

import { listDocuments, uploadDocument } from '../api/upload'
import { toast } from '../composables/useToast'

const emit = defineEmits(['uploaded'])

const docType = ref('textbook')
const fileInput = ref(null)
const pendingFile = ref(null)
const dragging = ref(false)
const uploading = ref(false)
const loadingDocs = ref(false)
const docs = ref([])

const ACCEPT = '.pdf,.docx'
const MAX_MB = 20

const selectedName = computed(() => pendingFile.value?.name ?? '')
const totalChunks = computed(() => docs.value.reduce((sum, doc) => sum + (doc.chunks_count || 0), 0))

function isSupported(file) {
  return /\.(pdf|docx)$/i.test(file.name)
}

function acceptFile(file) {
  if (!file) return
  if (!isSupported(file)) {
    toast.error('仅支持 PDF 与 Word(.docx) 文件')
    return
  }
  if (file.size > MAX_MB * 1024 * 1024) {
    toast.error(`文件超过 ${MAX_MB}MB 限制`)
    return
  }
  pendingFile.value = file
}

function onPick(event) {
  acceptFile(event.target.files?.[0])
}

function onDrop(event) {
  dragging.value = false
  acceptFile(event.dataTransfer?.files?.[0])
}

function clearSelection() {
  pendingFile.value = null
  if (fileInput.value) fileInput.value.value = ''
}

async function refreshList() {
  loadingDocs.value = true
  try {
    docs.value = await listDocuments()
  } catch (err) {
    toast.error(`读取知识库失败：${err.message}`)
  } finally {
    loadingDocs.value = false
  }
}

async function onUpload() {
  if (!pendingFile.value) {
    toast.error('请先选择 PDF 或 Word 文件')
    return
  }
  uploading.value = true
  try {
    const result = await uploadDocument(docType.value, pendingFile.value)
    toast.success(
      `${result.message}：${result.document.original_name}（切出 ${result.document.chunks_count} 个知识块）`,
    )
    clearSelection()
    await refreshList()
    emit('uploaded')
  } catch (err) {
    if (err.status === 409) {
      // 内容重复属于业务提示：已入库的文件不必再传，直接给出原文档信息
      toast.info(err.message, 8000)
      clearSelection()
      await refreshList()
    } else {
      toast.error(`上传失败：${err.message}`)
    }
  } finally {
    uploading.value = false
  }
}

onMounted(refreshList)
</script>

<template>
  <div class="stack">
    <section class="card">
      <div class="card-head">
        <h2>上传资料</h2>
        <span class="muted">支持 PDF / Word，单个文件 ≤ {{ MAX_MB }}MB</span>
      </div>
      <div class="card-body stack">
        <div class="row">
          <span class="muted">资料类型</span>
          <div class="segmented" role="group" aria-label="资料类型">
            <button
              type="button"
              :class="{ 'is-active': docType === 'textbook' }"
              :aria-pressed="docType === 'textbook'"
              @click="docType = 'textbook'"
            >
              教材章节
            </button>
            <button
              type="button"
              :class="{ 'is-active': docType === 'exercise' }"
              :aria-pressed="docType === 'exercise'"
              @click="docType = 'exercise'"
            >
              习题册
            </button>
          </div>
          <span class="muted">
            {{ docType === 'textbook' ? '教材内容用于检索依据' : '习题册仅登记原题，不参与依据召回' }}
          </span>
        </div>

        <div
          class="dropzone"
          :class="{ 'is-over': dragging }"
          role="button"
          tabindex="0"
          @click="fileInput?.click()"
          @keydown.enter.prevent="fileInput?.click()"
          @keydown.space.prevent="fileInput?.click()"
          @dragover.prevent="dragging = true"
          @dragleave.prevent="dragging = false"
          @drop.prevent="onDrop"
        >
          <span class="dropzone-title">
            {{ selectedName || '拖拽文件到此处，或点击选择' }}
          </span>
          <span>{{ selectedName ? '已就绪，点击「上传并入库」开始解析切块' : '文档将按页/段落切块，并保留章节与页码来源' }}</span>
        </div>

        <input
          ref="fileInput"
          class="sr-only"
          type="file"
          :accept="ACCEPT"
          aria-label="选择教材或习题册文件"
          @change="onPick"
        />

        <div class="row">
          <button class="btn btn-primary" type="button" :disabled="uploading || !pendingFile" @click="onUpload">
            <span v-if="uploading" class="spinner" aria-hidden="true"></span>
            {{ uploading ? '上传解析中…' : '上传并入库' }}
          </button>
          <button class="btn" type="button" :disabled="!pendingFile || uploading" @click="clearSelection">
            清空选择
          </button>
          <button class="btn btn-ghost" type="button" :disabled="loadingDocs" @click="refreshList">
            {{ loadingDocs ? '读取中…' : '刷新知识库状态' }}
          </button>
        </div>
      </div>
    </section>

    <section class="card">
      <div class="card-head">
        <h2>知识库概览</h2>
        <span class="muted">共 {{ docs.length }} 份文档 · {{ totalChunks }} 个知识块</span>
      </div>
      <div class="card-body">
        <div v-if="loadingDocs" class="stack-sm">
          <span class="skeleton" style="height: 42px"></span>
          <span class="skeleton" style="height: 42px"></span>
        </div>
        <ul v-else-if="docs.length" class="doc-items">
          <li v-for="doc in docs" :key="doc.doc_id" class="source-item">
            <span class="badge" :class="doc.doc_type === 'textbook' ? 'is-accent' : ''">
              {{ doc.doc_type === 'textbook' ? '教材' : '习题册' }}
            </span>
            <span class="strong">{{ doc.original_name }}</span>
            <span class="spacer"></span>
            <span class="muted num">{{ doc.units_count }} 单元 · {{ doc.chunks_count }} 块</span>
          </li>
        </ul>
        <p v-else class="empty">知识库还是空的，先上传教材章节与习题册吧。</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.doc-items { list-style: none; padding: 0; display: flex; flex-direction: column; gap: 2px; }
</style>
