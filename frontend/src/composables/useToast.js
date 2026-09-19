/**
 * 轻量吐司通知：不阻塞操作、自动消失，替代 window.alert。
 */
import { ref } from 'vue'

const ICONS = { info: 'ℹ️', success: '✅', error: '⚠️' }
const DEFAULT_TIMEOUT = { info: 4000, success: 3500, error: 7000 }

export const toasts = ref([])

let sequence = 0

export function dismissToast(id) {
  toasts.value = toasts.value.filter((item) => item.id !== id)
}

export function pushToast(kind, message, timeout) {
  const id = ++sequence
  const entry = { id, kind, message, icon: ICONS[kind] ?? ICONS.info }
  toasts.value = [...toasts.value, entry] // 不可变更新，避免共享引用
  const ttl = timeout ?? DEFAULT_TIMEOUT[kind] ?? 4000
  if (ttl > 0) setTimeout(() => dismissToast(id), ttl)
  return id
}

export const toast = {
  info: (message, timeout) => pushToast('info', message, timeout),
  success: (message, timeout) => pushToast('success', message, timeout),
  error: (message, timeout) => pushToast('error', message, timeout),
}
