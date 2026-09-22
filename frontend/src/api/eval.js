export async function fetchEvalReport() {
  const response = await fetch('/api/eval/latest')
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json()
}


export async function fetchAblationReport() {
  const response = await fetch('/api/eval/ablation')
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json()
}
