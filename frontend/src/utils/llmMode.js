/**
 * 生成模式展示元数据（顶栏徽标 / 历史记录标签 / 评测报告徽标共用一套口径）。
 *
 * 模式来源：后端 /api/health 的 llm_mode 与各条解析记录的 mode 字段；
 * 历史数据里的 "live" 是早期云端值，统一映射为云端。
 */
export const LLM_MODE_META = {
  mock: {
    icon: '🧪',
    label: '离线模板',
    title: '离线模板模式：由检索到的教材片段拼装而成，未调用大模型',
    warn: true,
  },
  ollama: {
    icon: '🦙',
    label: '本地模型',
    title: '本地 Ollama 模型生成：零费用、断网可用',
    warn: false,
  },
  cloud: {
    icon: '☁️',
    label: '云端模型',
    title: '云端大模型生成（OpenAI 兼容端点）',
    warn: false,
  },
  live: {   // 历史记录旧值：既有的云端生成记录
    icon: '☁️',
    label: '云端模型',
    title: '云端大模型生成（历史记录旧值 live）',
    warn: false,
  },
}

export function llmModeMeta(mode, fallback = 'cloud') {
  return LLM_MODE_META[mode] ?? LLM_MODE_META[fallback]
}
