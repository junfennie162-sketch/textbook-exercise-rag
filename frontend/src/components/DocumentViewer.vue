<script setup>
import { computed, onMounted, ref, watch } from 'vue'

import { deleteDocument, getPage, listPages } from '../api/documents'
import { listDocuments } from '../api/upload'
import { toast } from '../composables/useToast'

const props = defineProps({ version: { type: Number, default: 0 } })

const docs = ref([])
const selectedDocId = ref('')
const pages = ref([])
const sections = ref([])
const selectedPage = ref(null)
const docFilter = ref('')
const pageFilter = ref('')
const sectionFilter = ref('')
const loadingDocs = ref(false)
const loadingPage = ref(false)
const confirmingId = ref('')
const deleting = ref(false)

const filteredDocs = computed(() => {
  const keyword = docFilter.value.trim().toLowerCase()
  if (!keyword) return docs.value
  return docs.value.filter((doc) => doc.original_name.toLowerCase().includes(keyword))
})

const visiblePages = computed(() => {
  const keyword = pageFilter.value.trim()
  return pages.value.filter((page) => {
    if (sectionFilter.value && page.section !== sectionFilter.value) return false
    if (keyword && !String(page.preview ?? '').includes(keyword)) return false
    return true
  })
})

// 不加小节筛选时按小节插入分组标题（相邻同小节只显示一次）
const visibleRows = computed(() => {
  let previous = null
  return visiblePages.value.map((page) => {
    const showHeader = page.section !== previous
    previous = page.section
    return { ...page, showHeader }
  })
})

const currentDoc = computed(() => docs.value.find((doc) => doc.doc_id === selectedDocId.value) ?? null)

async function loadDocs() {
  loadingDocs.value = true
  try {
    docs.value = await listDocuments()
    if (!docs.value.length) {
      selectedDocId.value = ''
      pages.value = []
      selectedPage.value = null
      return
    }
    const stillExists = docs.value.some((doc) => doc.doc_id === selectedDocId.value)
    if (!stillExists) await selectDoc(docs.value[0].doc_id)
  } catch (err) {
    toast.error(`读取文档列表失败：${err.message}`)
  } finally {
    loadingDocs.value = false
  }
}

async function selectDoc(docId) {
  selectedDocId.value = docId
  pages.value = []
  sections.value = []
  selectedPage.value = null
  pageFilter.value = ''
  sectionFilter.value = ''
  try {
    const result = await listPages(docId)
    pages.value = result.pages ?? []
    sections.value = result.sections ?? []
    if (pages.value.length) await selectPage(pages.value[0].page)
  } catch (err) {
    toast.error(`读取页段目录失败：${err.message}`)
  }
}

async function selectPage(pageNo) {
  loadingPage.value = true
  try {
    selectedPage.value = await getPage(selectedDocId.value, pageNo)
  } catch (err) {
    toast.error(`读取原文失败：${err.message}`)
  } finally {
    loadingPage.value = false
  }
}

async function copyContent() {
  if (!selectedPage.value) return
  try {
    await navigator.clipboard.writeText(selectedPage.value.content ?? '')
    toast.success('已复制当前页段原文')
  } catch {
    toast.error('复制失败：浏览器未授权剪贴板')
  }
}

async function onDelete(doc) {
  deleting.value = true
  try {
    const result = await deleteDocument(doc.doc_id)
    toast.success(result.message ?? '文档已删除')
    confirmingId.value = ''
    const wasSelected = selectedDocId.value === doc.doc_id
    if (wasSelected) {
      selectedDocId.value = ''
      pages.value = []
      selectedPage.value = null
    }
    await loadDocs()
  } catch (err) {
    toast.error(`删除失败：${err.message}`)
  } finally {
    deleting.value = false
  }
}

watch(() => props.version, loadDocs)
onMounted(loadDocs)
</script>

<template>
  <div class="stack">
    <section class="card">
      <div class="card-head">
        <h2>资料原文</h2>
        <div class="row">
          <span v-if="currentDoc" class="muted">
            {{ currentDoc.original_name }} · {{ pages.length }} 个页段
          </span>
          <button class="btn btn-ghost" type="button" :disabled="loadingDocs" @click="loadDocs">
            {{ loadingDocs ? '读取中…' : '刷新' }}
          </button>
        </div>
      </div>

      <div class="card-body viewer">
        <div class="pane">
          <label class="field">
            <input v-model="docFilter" type="text" placeholder="按文件名筛选" aria-label="按文件名筛选" />
          </label>
          <div v-if="loadingDocs" class="stack-sm">
            <span class="skeleton" style="height: 46px"></span>
            <span class="skeleton" style="height: 46px"></span>
          </div>
          <ul v-else-if="filteredDocs.length" class="list">
            <li
              v-for="doc in filteredDocs"
              :key="doc.doc_id"
              class="doc-row"
              :class="{ 'is-active': doc.doc_id === selectedDocId }"
            >
              <button
                class="doc-main"
                type="button"
                :aria-pressed="doc.doc_id === selectedDocId"
                @click="selectDoc(doc.doc_id)"
              >
                <span class="row" style="gap: 6px">
                  <span class="badge" :class="doc.doc_type === 'textbook' ? 'is-accent' : ''">
                    {{ doc.doc_type === 'textbook' ? '教材' : '习题册' }}
                  </span>
                  <span class="strong">{{ doc.original_name }}</span>
                </span>
                <span class="muted num">{{ doc.units_count }} 单元 · {{ doc.chunks_count }} 块</span>
              </button>
              <template v-if="confirmingId === doc.doc_id">
                <button class="btn btn-danger btn-sm" type="button" :disabled="deleting" @click="onDelete(doc)">
                  {{ deleting ? '删除中…' : '确认删除' }}
                </button>
                <button class="btn btn-ghost btn-sm" type="button" @click="confirmingId = ''">取消</button>
              </template>
              <button
                v-else
                class="btn btn-ghost btn-sm"
                type="button"
                :aria-label="`删除 ${doc.original_name}`"
                @click="confirmingId = doc.doc_id"
              >
                删除
              </button>
            </li>
          </ul>
          <p v-else class="empty">没有匹配的文档。</p>
        </div>

        <div class="pane">
          <label class="field">
            <input v-model="pageFilter" type="text" placeholder="在页段摘要中搜索" aria-label="在页段摘要中搜索" />
          </label>
          <label class="field">
            <select v-model="sectionFilter" aria-label="按小节筛选">
              <option value="">全部小节（共 {{ sections.length }} 个）</option>
              <option v-for="item in sections" :key="item.section" :value="item.section">
                {{ item.section }}（{{ item.count }} 段）
              </option>
            </select>
          </label>
          <ul v-if="visibleRows.length" class="list">
            <li v-for="row in visibleRows" :key="row.page">
              <p v-if="row.showHeader" class="section-head">{{ row.section }}</p>
              <button
                class="list-item"
                :class="{ 'is-active': selectedPage?.page === row.page }"
                type="button"
                :aria-pressed="selectedPage?.page === row.page"
                @click="selectPage(row.page)"
              >
                <span class="strong num">第 {{ row.page }} 页/段</span>
                <span class="muted clamp">{{ row.preview }}</span>
              </button>
            </li>
          </ul>
          <p v-else class="empty">
            {{ pages.length ? '没有匹配的页段。' : '选择左侧文档后查看页段目录。' }}
          </p>
        </div>

        <div class="pane">
          <div class="row-between">
            <span class="strong">
              {{ selectedPage ? `第 ${selectedPage.page} 页/段原文` : '原文内容' }}
            </span>
            <button class="btn btn-sm" type="button" :disabled="!selectedPage" @click="copyContent">
              复制原文
            </button>
          </div>
          <div v-if="loadingPage" class="stack-sm">
            <span class="skeleton" style="height: 16px"></span>
            <span class="skeleton" style="height: 16px; width: 85%"></span>
            <span class="skeleton" style="height: 16px; width: 70%"></span>
          </div>
          <pre v-else-if="selectedPage" class="content">{{ selectedPage.content }}</pre>
          <p v-else class="empty">点击中间目录查看对应原文。</p>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.viewer {
  display: grid;
  grid-template-columns: minmax(200px, 0.9fr) minmax(200px, 1fr) minmax(260px, 1.4fr);
  gap: var(--sp-4);
}
.pane { display: flex; flex-direction: column; gap: var(--sp-3); min-width: 0; }
.list { list-style: none; padding: 0; display: flex; flex-direction: column; gap: 3px; max-height: 460px; overflow-y: auto; }
.list-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
  width: 100%;
  padding: var(--sp-2) var(--sp-3);
  border: 1px solid transparent;
  border-radius: var(--r-sm);
  background: transparent;
  color: var(--ink-2);
  font: inherit;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}
.list-item:hover { background: var(--surface-2); }
.list-item.is-active { background: var(--accent-soft); border-color: var(--accent-wash); }
.section-head {
  position: sticky;
  top: 0;
  z-index: 1;
  margin: var(--sp-2) 0 2px;
  padding: 2px var(--sp-2);
  border-radius: 4px;
  background: var(--surface-2);
  color: var(--accent-ink);
  font-size: 11.5px;
  font-weight: 650;
}
.section-head:first-child { margin-top: 0; }
.doc-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding-right: 4px;
  border: 1px solid transparent;
  border-radius: var(--r-sm);
}
.doc-row:hover { background: var(--surface-2); }
.doc-row.is-active { background: var(--accent-soft); border-color: var(--accent-wash); }
.doc-main {
  display: flex;
  flex-direction: column;
  gap: 3px;
  flex: 1 1 auto;
  min-width: 0;
  padding: var(--sp-2) var(--sp-3);
  border: 0;
  background: transparent;
  color: var(--ink-2);
  font: inherit;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}
.clamp { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.content {
  margin: 0;
  padding: var(--sp-4);
  border-radius: var(--r-md);
  background: var(--surface-sunken);
  font-size: 13px;
  line-height: 1.8;
  white-space: pre-wrap;
  max-height: 460px;
  overflow-y: auto;
}
@media (max-width: 1100px) {
  .viewer { grid-template-columns: 1fr; }
  .list { max-height: 260px; }
}
</style>
