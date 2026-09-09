import { useEffect, useState } from 'react'
import MapView from './components/MapView'
import EvidencePanel from './components/EvidencePanel'
import VesselTable from './components/VesselTable'
import ScoreBreakdown from './components/ScoreBreakdown'
import ExonerationRecord from './components/ExonerationRecord'
import { evidenceUrl, resultUrl, sceneAssetUrl, sceneIdFromUrl } from './api'
import { buildReportText, loadImage, primaryVessel, validateResult } from './sceneUtils'
import './components/AttributionDeck.css'

const SCENE_ID = sceneIdFromUrl('mock')

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

  useEffect(() => {
    let cancelled = false
    async function fetchScene() {
      try {
        setStatus('loading')
        const response = await fetch(resultUrl(SCENE_ID))
        if (!response.ok) throw new Error(`Scene request failed (${response.status}).`)
        const sceneResult = validateResult(await response.json())
        // pass SCENE_ID: assets live under the scene FOLDER, which is not the
        // same string as result.scene.id on a real pipeline run
        const sceneUrl = sceneAssetUrl(sceneResult, sceneResult.scene.image, SCENE_ID)
        const maskUrl = sceneAssetUrl(sceneResult, sceneResult.scene.mask, SCENE_ID)
        await Promise.all([loadImage(sceneUrl), loadImage(maskUrl)])
        if (cancelled) return
        setAssetUrls({ sceneUrl, maskUrl })
        setResult(sceneResult)
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
  }, [])

  useEffect(() => {
    if (!notice) return undefined
    const timer = setTimeout(() => setNotice(''), 3200)
    return () => clearTimeout(timer)
  }, [notice])

  async function generateReport() {
    if (!result) return
    const sceneId = result.meta?.source === 'mock' ? 'mock' : SCENE_ID
    try {
      const response = await fetch(evidenceUrl(sceneId))
      if (response.ok) {
        const blob = await response.blob()
        const url = URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = url
        link.download = `oceanfir-${sceneId}.pdf`
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
    link.download = `oceanfir-${sceneId}-report.txt`
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

  const vessels = result?.vessels ?? []
  const selectedVessel = vessels.find((v) => v.mmsi === selectedMmsi) ?? null
  const summary = result?.summary ?? null
  const declined = summary?.verdict === 'no_attribution'

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <img className="brand-logo" src="/oceanfir-logo.png" alt="OceanFIR" />
          <div>
            <p className="eyebrow">Maritime intelligence</p>
            <p className="brand-kicker">Sentinel-1 investigation workspace</p>
          </div>
        </div>
        <div className="header-actions">
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
