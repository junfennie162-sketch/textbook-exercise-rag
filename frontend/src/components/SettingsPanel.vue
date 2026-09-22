<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { fetchLlmStatus, pullOllamaModel } from '../api/llm'
import { fetchSettings, resetSettings, saveSettings } from '../api/settings'
import { toast } from '../composables/useToast'
import { llmModeMeta } from '../utils/llmMode'

const emit = defineEmits(['changed'])

const spec = ref([])
const values = ref({})
const overridden = ref([])
const meta = ref({})
const file = ref('')
const loading = ref(false)
const saving = ref(false)
const probing = ref(false)
const modelOptions = ref([])
const keyInput = ref('')      // 新 Key 输入框：留空/不回传掩码 = 不修改

// 本地模型拉取（Ollama 原生 /api/pull 的进度流）
const pullModel = ref('')
const pulling = ref(false)
const pullProgress = ref(null)
const pullStatus = ref('')
const pullError = ref('')
let pullController = null

const groups = computed(() => {
  const order = []
  const buckets = new Map()
  for (const item of spec.value) {
    if (!buckets.has(item.group)) {
      buckets.set(item.group, [])
      order.push(item.group)
    }
    buckets.get(item.group).push(item)
  }
  return order.map((name) => ({ name, items: buckets.get(name) }))
})

const modeMeta = computed(() => llmModeMeta(meta.value.mode || 'cloud'))

async function load() {
  loading.value = true
  try {
    const payload = await fetchSettings()
    spec.value = payload.spec ?? []
    values.value = { ...(payload.values ?? {}) }
    overridden.value = payload.overridden ?? []
    meta.value = payload
    file.value = payload.file ?? ''
    keyInput.value = ''
    if (!pullModel.value) {
      pullModel.value = payload.values?.ollama_model || 'qwen2.5:3b'
    }
  } catch (err) {
    toast.error(`读取设置失败：${err.message}`)
  } finally {
    loading.value = false
  }
}

async function onPull() {
  const model = pullModel.value.trim()
  if (!model) {
    toast.error('请先填写模型名，例如 qwen2.5:3b')
    return
  }
  pulling.value = true
  pullProgress.value = null
  pullStatus.value = '连接 Ollama…'
  pullError.value = ''
  pullController = new AbortController()
  try {
    await pullOllamaModel(model, {
      signal: pullController.signal,
      onEvent(event) {
        if (event.type === 'progress') {
          pullStatus.value = event.status || '下载中…'
          if (typeof event.percent === 'number') pullProgress.value = event.percent
        } else if (event.type === 'done') {
          pullProgress.value = 100
          pullStatus.value = '拉取完成'
          modelOptions.value = []      // 下次「测试连接」重新拉取模型列表
          toast.success(`模型「${model}」已就绪，可切换到 ollama 通道使用`)
        } else if (event.type === 'error') {
          pullStatus.value = ''
          pullError.value = `${event.message ?? '拉取失败'}${event.hint ? '｜' + event.hint : ''}`
        }
      },
    })
  } catch (err) {
    pullError.value = `拉取请求失败：${err.message}`
  } finally {
    pulling.value = false
    pullController = null
  }
}

async function onSave() {
  saving.value = true
  try {
    const update = { ...values.value }
    delete update.llm_api_key                 // Key 单独处理：不回传掩码
    if (keyInput.value.trim()) update.llm_api_key = keyInput.value.trim()
    const result = await saveSettings(update)
    if (result.rejected?.length) {
      toast.error(`已忽略无效字段：${result.rejected.join('、')}`)
    }
    toast.success('已保存并热生效（无需重启后端）')
    emit('changed')
    await load()
  } catch (err) {
    toast.error(`保存失败：${err.message}`)
  } finally {
    saving.value = false
  }
}

async function onReset() {
  saving.value = true
  try {
    await resetSettings()
    toast.info('已恢复默认配置（回到 .env / 默认值）')
    emit('changed')
    await load()
  } catch (err) {
    toast.error(`恢复默认失败：${err.message}`)
  } finally {
    saving.value = false
  }
}

async function onProbe() {
  probing.value = true
  try {
    const status = await fetchLlmStatus()
    modelOptions.value = status.models ?? []
    if (!status.ok) {
      toast.error(`${status.error ?? '连接失败'}｜${status.hint ?? ''}`)
    } else if (status.mode !== 'mock' && status.model_present === false) {
      toast.error(`模型连接异常：${status.message}`)
    } else {
      toast.success(status.mode === 'mock'
        ? '离线模板模式正常：不访问任何外部服务'
        : `连接正常（${status.model}）`)
    }
  } catch (err) {
    toast.error(`探测请求失败：${err.message}`)
  } finally {
    probing.value = false
  }
}

onMounted(load)
onBeforeUnmount(() => pullController?.abort())
</script>

<template>
  <div class="stack">
    <section v-if="loading" class="card">
      <div class="card-body stack-sm">
        <span class="skeleton" style="height: 18px"></span>
        <span class="skeleton" style="height: 18px; width: 76%"></span>
        <span class="skeleton" style="height: 18px; width: 58%"></span>
      </div>
    </section>

    <template v-else>
      <section v-for="group in groups" :key="group.name" class="card">
        <div class="card-head">
          <h2>{{ group.name }}</h2>
          <span v-if="group.name === '模型通道'" class="row" style="gap: 8px">
            <span class="badge">{{ modeMeta.icon }} {{ modeMeta.label }}<template v-if="meta.model"> · {{ meta.model }}</template></span>
            <button class="btn btn-sm" type="button" :disabled="probing" @click="onProbe">
              <span v-if="probing" class="spinner" aria-hidden="true"></span>
              {{ probing ? '检测中…' : '测试连接' }}
            </button>
          </span>
        </div>
        <div class="card-body stack">
          <div v-for="item in group.items" :key="item.key" class="setting-row">
            <div class="setting-head">
              <span class="strong">{{ item.label }}</span>
              <span v-if="overridden.includes(item.key)" class="badge is-accent">已覆盖</span>
            </div>

            <div class="setting-control">
              <div v-if="item.type === 'select'" class="segmented" role="group" :aria-label="item.label">
                <button
                  v-for="option in item.options"
                  :key="option"
                  type="button"
                  :class="{ 'is-active': values[item.key] === option }"
                  @click="values[item.key] = option"
                >
                  {{ option === 'cloud' ? '☁️ 云端 API' : '🦙 本地 Ollama' }}
                </button>
              </div>

              <template v-else-if="item.type === 'number'">
                <input
                  v-model.number="values[item.key]"
                  type="range"
                  :min="item.min"
                  :max="item.max"
                  :step="item.step"
                  :aria-label="item.label"
                />
                <span class="num setting-value">{{ values[item.key] }}</span>
              </template>

              <label v-else-if="item.type === 'bool'" class="row" style="gap: 8px">
                <input v-model="values[item.key]" type="checkbox" />
                <span class="muted">{{ values[item.key] ? '已启用' : '已关闭' }}</span>
              </label>

              <input
                v-else-if="item.type === 'password'"
                v-model="keyInput"
                type="password"
                autocomplete="off"
                :placeholder="values[item.key] || '未配置（留空则保持现有 Key）'"
                :aria-label="item.label"
              />

              <textarea
                v-else-if="item.type === 'textarea'"
                v-model="values[item.key]"
                rows="3"
                :maxlength="item.max_length"
                :placeholder="item.hint"
                :aria-label="item.label"
              ></textarea>

              <input
                v-else
                v-model="values[item.key]"
                type="text"
                :list="item.key.includes('model') && modelOptions.length ? 'llm-models' : undefined"
                :aria-label="item.label"
              />
            </div>
            <p class="muted setting-hint">{{ item.hint }}</p>
          </div>
        </div>
      </section>

      <datalist id="llm-models">
        <option v-for="id in modelOptions" :key="id" :value="id"></option>
      </datalist>

      <section class="card">
        <div class="card-head">
          <h2>本地模型拉取（Ollama）</h2>
          <span class="muted">调用本机 Ollama 下载模型，实时显示进度</span>
        </div>
        <div class="card-body stack-sm">
          <div class="row" style="gap: 8px">
            <input
              v-model="pullModel"
              type="text"
              placeholder="模型名，例如 qwen2.5:3b"
              aria-label="待拉取的模型名"
              style="flex: 0 1 300px"
            />
            <button class="btn" type="button" :disabled="pulling" @click="onPull">
              <span v-if="pulling" class="spinner" aria-hidden="true"></span>
              {{ pulling ? '拉取中…' : '拉取模型' }}
            </button>
            <button class="btn btn-ghost" type="button" :disabled="pulling"
                    @click="pullModel = values.ollama_model || 'qwen2.5:3b'">
              填入当前 Ollama 模型名
            </button>
          </div>

          <div v-if="pullStatus || pullProgress !== null" class="stack-sm">
            <div class="meter" role="progressbar" :aria-valuenow="pullProgress ?? 0"
                 aria-valuemin="0" aria-valuemax="100" aria-label="模型拉取进度">
              <div class="meter-fill" :style="{ width: `${pullProgress ?? 0}%` }"></div>
            </div>
            <p class="muted" style="margin: 0">
              {{ pullStatus }}<template v-if="pullProgress !== null">（{{ pullProgress }}%）</template>
            </p>
          </div>
          <p v-if="pullError" class="muted" style="margin: 0">{{ pullError }}</p>
          <p class="muted" style="margin: 0">
            需要本机 Ollama 已启动（默认 http://localhost:11434）；拉取完成后把上方「模型通道」切到 ollama
            并填写模型名即可使用。大模型体积可达数 GB，请留意磁盘与网络。
          </p>
        </div>
      </section>

      <section class="card">
        <div class="card-body stack-sm">
          <div class="row" style="gap: 8px">
            <button class="btn btn-primary" type="button" :disabled="saving" @click="onSave">
              <span v-if="saving" class="spinner" aria-hidden="true"></span>
              {{ saving ? '保存中…' : '保存并热生效' }}
            </button>
            <button class="btn btn-ghost" type="button" :disabled="saving" @click="onReset">恢复默认</button>
          </div>
          <p class="muted">
            保存后<strong>立即生效、无需重启后端</strong>；覆盖值存于 {{ file || 'backend/data/runtime_settings.json' }}。
            该文件可能包含 API Key，请勿随源码包外发（打包脚本已自动排除）。
          </p>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.setting-row { display: flex; flex-direction: column; gap: 6px; }
.setting-head { display: flex; align-items: center; gap: 8px; font-size: 13.5px; }
.setting-control { display: flex; align-items: center; gap: 10px; }
.setting-control input[type='range'] { flex: 0 0 min(320px, 60%); }
.setting-control input[type='text'],
.setting-control input[type='password'],
.setting-control textarea { flex: 1 1 320px; max-width: 560px; }
.setting-value { min-width: 52px; text-align: right; font-weight: 600; }
.setting-hint { font-size: 12.5px; line-height: 1.6; margin: 0; }
</style>
