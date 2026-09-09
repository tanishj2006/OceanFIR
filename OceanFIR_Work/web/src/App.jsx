import { useEffect, useState } from 'react'
import MapView from './components/MapView'
import EvidencePanel from './components/EvidencePanel'
import { MOCK_RESULT_URL, evidenceUrl, sceneAssetUrl } from './api'
import { buildReportText, loadImage, primaryVessel, validateResult } from './sceneUtils'

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
        const response = await fetch(MOCK_RESULT_URL)
        if (!response.ok) throw new Error(`Scene request failed (${response.status}).`)
        const sceneResult = validateResult(await response.json())
        const sceneUrl = sceneAssetUrl(sceneResult, sceneResult.scene.image)
        const maskUrl = sceneAssetUrl(sceneResult, sceneResult.scene.mask)
        await Promise.all([loadImage(sceneUrl), loadImage(maskUrl)])
        if (cancelled) return
        setAssetUrls({ sceneUrl, maskUrl })
        setResult(sceneResult)
        setSelectedMmsi(primaryVessel(sceneResult)?.mmsi ?? null)
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
    const sceneId = result.meta?.source === 'mock' ? 'mock' : result.scene.id
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
      )}
      {notice && <div className="notice" role="status">{notice}</div>}
    </div>
  )
}
