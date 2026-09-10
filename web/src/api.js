export const API_BASE = 'http://127.0.0.1:8000'
export const MOCK_RESULT_URL = `${API_BASE}/api/result/mock`

// Which scene to load. Defaults to the mock fixture so the app always opens on
// something that works; ?scene=gulf20230620 switches to the real pipeline
// result without a rebuild.
export function sceneIdFromUrl(fallback = 'mock') {
  try {
    return new URLSearchParams(window.location.search).get('scene') || fallback
  } catch {
    return fallback
  }
}

export function resultUrl(sceneId) {
  return `${API_BASE}/api/result/${encodeURIComponent(sceneId)}`
}

// sceneId must be the SCENE FOLDER, not result.scene.id. They differ: a real
// run reports scene.id "sar_sea" (from the image filename) while its assets are
// served from /static/gulf20230620/. Passing the folder we requested is the
// only reliable answer; the old fallback is kept so nothing that already calls
// this with two arguments breaks.
export function sceneAssetUrl(result, filename, sceneId) {
  if (!filename) return null
  const folder = sceneId || (result.meta?.source === 'mock' ? 'mock' : result.scene.id)
  return `${API_BASE}/static/${encodeURIComponent(folder)}/${encodeURIComponent(filename)}`
}

export function scenesUrl() {
  return `${API_BASE}/api/scenes`
}

export function evidenceUrl(sceneId) {
  return `${API_BASE}/api/evidence/${encodeURIComponent(sceneId)}`
}
