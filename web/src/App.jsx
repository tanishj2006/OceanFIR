import { useEffect, useState } from 'react'
import MapView from './components/MapView'
import EvidencePanel from './components/EvidencePanel'
import VesselTable from './components/VesselTable'
import ScoreBreakdown from './components/ScoreBreakdown'
import ExonerationRecord from './components/ExonerationRecord'
import { evidenceUrl, resultUrl, sceneAssetUrl, sceneIdFromUrl, scenesUrl } from './api'
import { buildReportText, loadImage, primaryVessel, validateResult } from './sceneUtils'
import './components/AttributionDeck.css'

function topScorer(result) {
  const vessels = result?.vessels ?? []
  if (!vessels.length) return null
  return vessels.reduce((best, v) => ((v.score ?? -1) > (best.score ?? -1) ? v : best))
}

export default function App() {
  const [result, setResult] = useState(null)
  const [assetUrls, setAssetUrls] = useState(null)
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState('')
  const [selectedMmsi, setSelectedMmsi] = useState(null)
  const [highlight, setHighlight] = useState(null)
  const [notice, setNotice] = useState('')
  // Which scene is on screen. Starts from ?scene= so a link still opens a
  // specific one, but it is state now: switching no longer reloads the page,
  // which matters when you are flipping between scenes in front of an audience.
  const [sceneId, setSceneId] = useState(() => sceneIdFromUrl('mock'))
  const [scenes, setScenes] = useState([])

  useEffect(() => {
    let cancelled = false
    fetch(scenesUrl())
      .then((r) => (r.ok ? r.json() : []))
      .then((list) => { if (!cancelled && Array.isArray(list)) setScenes(list) })
      .catch(() => { /* the switcher just stays hidden */ })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    try {
      const url = new URL(window.location.href)
      url.searchParams.set('scene', sceneId)
      window.history.replaceState({}, '', url)
    } catch { /* deep link is a nicety, never a requirement */ }
  }, [sceneId])

  useEffect(() => {
    let cancelled = false
    async function fetchScene() {
      try {
        setStatus('loading')
        const response = await fetch(resultUrl(sceneId))
        if (!response.ok) throw new Error(`Scene request failed (${response.status}).`)
        const sceneResult = validateResult(await response.json())
        // pass sceneId: assets live under the scene FOLDER, which is not the
        // same string as result.scene.id on a real pipeline run
        const sceneUrl = sceneAssetUrl(sceneResult, sceneResult.scene.image, sceneId)
        const maskUrl = sceneAssetUrl(sceneResult, sceneResult.scene.mask, sceneId)
        await Promise.all([loadImage(sceneUrl), loadImage(maskUrl)])
        if (cancelled) return
        setAssetUrls({ sceneUrl, maskUrl })
        setResult(sceneResult)
        setHighlight(null)
        // On a no_attribution scene there is no accused or suspect vessel, so
        // primaryVessel() returns null and the score panel opens empty. Fall
        // back to the highest scorer: the point of the panel there is to show
        // WHY the best candidate still did not clear the bar.
        setSelectedMmsi(primaryVessel(sceneResult)?.mmsi ?? topScorer(sceneResult)?.mmsi ?? null)
        setStatus('ready')
      } catch (caught) {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : 'Unable to load the scene.')
          setStatus('error')
        }
      }
    }
    fetchScene()
    return () => { cancelled = true }
  }, [sceneId])

  useEffect(() => {
    if (!notice) return undefined
    const timer = setTimeout(() => setNotice(''), 3200)
    return () => clearTimeout(timer)
  }, [notice])

  async function generateReport() {
    if (!result) return
    const reportScene = result.meta?.source === 'mock' ? 'mock' : sceneId
    try {
      const response = await fetch(evidenceUrl(reportScene))
      if (response.ok) {
        const blob = await response.blob()
        const url = URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = url
        link.download = `oceanfir-${reportScene}.pdf`
        link.click()
        URL.revokeObjectURL(url)
        setNotice('Evidence brief downloaded.')
        return
      }
    } catch {
      /* Fall through to a client-side report so the dashboard still works offline. */
    }
    const blob = new Blob([buildReportText(result)], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `oceanfir-${reportScene}-report.txt`
    link.click()
    URL.revokeObjectURL(url)
    setNotice('Client-side report downloaded.')
  }

  async function shareIncident() {
    if (!result) return
    const text = buildReportText(result)
    try {
      if (navigator.share) {
        await navigator.share({ title: 'OceanFIR incident', text })
        setNotice('Incident shared.')
        return
      }
      await navigator.clipboard.writeText(text)
      setNotice('Incident summary copied to clipboard.')
    } catch {
      setNotice('Share cancelled.')
    }
  }

  const sceneIndex = scenes.findIndex((s) => s.id === sceneId)
  const currentScene = sceneIndex >= 0 ? scenes[sceneIndex] : null
  const canSwitch = scenes.length > 1 && sceneIndex >= 0
  const step = (delta) => {
    if (!canSwitch) return
    const next = (sceneIndex + delta + scenes.length) % scenes.length
    setSceneId(scenes[next].id)
  }

  const vessels = result?.vessels ?? []
  const selectedVessel = vessels.find((v) => v.mmsi === selectedMmsi) ?? null
  const summary = result?.summary ?? null
  const declined = summary?.verdict === 'no_attribution'

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          {/* The emblem, not the full square logo. The header slot is 44px tall
              and the supplied artwork has the wordmark baked in underneath the
              globe -- contained to 44px that text renders about 6px high and is
              unreadable. So the globe carries the mark and the name is real
              text, which stays crisp at any size and is selectable. The
              emblem doubles as the favicon. */}
          <img className="brand-mark" src="/oceanfir-mark.png" alt="" />
          <div>
            <p className="brand-word"><span>Ocean</span><b>FIR</b></p>
            <p className="brand-kicker">Sentinel-1 investigation workspace</p>
          </div>
        </div>
        <div className="header-actions">
          {canSwitch && (
            <div className="scene-switch" role="group" aria-label="Scene">
              <button type="button" onClick={() => step(-1)} aria-label="Previous scene">&#8249;</button>
              <div className="scene-switch-label">
                <span className="scene-name">{currentScene?.name || sceneId}</span>
                <span className="scene-count">{sceneIndex + 1} of {scenes.length}</span>
              </div>
              <button type="button" onClick={() => step(1)} aria-label="Next scene">&#8250;</button>
            </div>
          )}
          <div className="header-status" aria-live="polite">
            {status === 'ready' && <span className="status-ok">SAR image loaded</span>}
            {status === 'loading' && <span>Loading Sentinel-1 scene…</span>}
            {status === 'error' && <span className="status-bad">Scene unavailable</span>}
            {result?.meta?.source === 'mock' && <span className="mock-badge">Mock data</span>}
          </div>
          <button type="button" className="header-btn" onClick={generateReport} disabled={status !== 'ready'}>Generate report</button>
          <button type="button" className="header-btn primary" onClick={shareIncident} disabled={status !== 'ready'}>Share incident</button>
        </div>
      </header>

      {status === 'loading' && <section className="map-status">Loading Sentinel-1 scene…</section>}
      {status === 'error' && <section className="map-status error"><strong>Scene unavailable</strong><span>{error}</span></section>}
      {status === 'ready' && result && (
        <>
          {/* A declined attribution is a RESULT, not an error. On the real Gulf
              scene this is what the system returns, so it needs to look like a
              deliberate finding rather than a blank panel. */}
          {declined && (
            <section className="verdict-banner verdict-declined" role="status">
              <strong>No attribution</strong>
              <span>
                {summary?.note || 'No vessel meets the attribution threshold.'}
                {' '}Scored {summary?.n_scored ?? vessels.length} vessels against a
                threshold of {summary?.threshold ?? 0.45}; the evidence does not
                separate a single vessel, so the system declines to name one.
              </span>
            </section>
          )}

          <div className="workspace">
            <MapView
              result={result}
              assetUrls={assetUrls}
              selectedMmsi={selectedMmsi}
              onSelect={setSelectedMmsi}
              highlight={highlight}
              onHighlight={setHighlight}
            />
            <EvidencePanel result={result} highlight={highlight} selectedMmsi={selectedMmsi} />
          </div>

          <section className="attribution-deck">
            <div className="attribution-row">
              <VesselTable
                vessels={vessels}
                onSelect={setSelectedMmsi}
                selectedMmsi={selectedMmsi}
              />
              <ScoreBreakdown
                vessel={selectedVessel}
                threshold={summary?.threshold ?? 0.45}
              />
            </div>
            <ExonerationRecord vessels={vessels} />
          </section>
        </>
      )}
      {notice && <div className="notice" role="status">{notice}</div>}
    </div>
  )
}
