export const API_BASE = 'http://127.0.0.1:8000'
export const MOCK_RESULT_URL = `${API_BASE}/api/result/mock`

export function sceneAssetUrl(result, filename) {
  if (!filename) return null
  const folder = result.meta?.source === 'mock' ? 'mock' : result.scene.id
  return `${API_BASE}/static/${encodeURIComponent(folder)}/${encodeURIComponent(filename)}`
}

export function evidenceUrl(sceneId) {
  return `${API_BASE}/api/evidence/${encodeURIComponent(sceneId)}`
}
