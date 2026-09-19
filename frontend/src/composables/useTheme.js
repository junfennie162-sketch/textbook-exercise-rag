/**
 * 主题（auto / light / dark）：写入 <html data-theme>，随系统或手动覆盖，选择记忆在 localStorage。
 */
import { computed, ref } from 'vue'

const STORAGE_KEY = 'workbench-theme'
const MODES = ['auto', 'light', 'dark']
const LABELS = { auto: '跟随系统', light: '浅色', dark: '深色' }

function readStored() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    return MODES.includes(stored) ? stored : 'auto'
  } catch {
    return 'auto' // 隐私模式下 localStorage 可能不可用
  }
}

function apply(value) {
  const root = document.documentElement
  if (value === 'auto') {
    root.removeAttribute('data-theme')
  } else {
    root.setAttribute('data-theme', value)
  }
}

const mode = ref(readStored())
apply(mode.value)

export function useTheme() {
  function setMode(value) {
    if (!MODES.includes(value)) return
    mode.value = value
    apply(value)
    try {
      localStorage.setItem(STORAGE_KEY, value)
    } catch {
      /* 存储不可用时仅本次生效 */
    }
  }

  return {
    mode,
    modes: MODES,
    label: computed(() => LABELS[mode.value]),
    setMode,
  }
}
