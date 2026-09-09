import { useCallback, useEffect, useRef, useState } from 'react'
import { API_BASE, MOCK_RESULT_URL } from '../api'
import './MapView.css'

const COLORS = {
  slick: '#E0503C',
  track: '#E0A54B',
  gap: '#5CC8D4',
  drift: '#FFFFFF',
}

const MIN_ZOOM = 1
const MAX_ZOOM = 6

function isPoint(value) {
  return Array.isArray(value) && Number.isFinite(value[0]) && Number.isFinite(value[1])
}

function validateResult(data) {
  const bbox = data?.scene?.bbox
  if (!Array.isArray(bbox) || bbox.length !== 4 || !bbox.every(Number.isFinite)) {
    throw new Error('The result did not contain a valid scene bounding box.')
  }
  if (!data?.detection?.slick?.polygon || !Array.isArray(data.vessels)) {
    throw new Error('The result did not contain the required scene data.')
  }
  return data
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.crossOrigin = 'anonymous'
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error(`Could not load scene imagery: ${url}`))
    image.src = url
  })
}

function sceneAssetUrl(result, filename) {
  if (!filename) return null
  const folder = result.meta?.source === 'mock' ? 'mock' : result.scene.id
  return `${API_BASE}/static/${encodeURIComponent(folder)}/${encodeURIComponent(filename)}`
}

function distanceToSegment(point, start, end) {
  const dx = end.x - start.x
  const dy = end.y - start.y
  const denominator = dx * dx + dy * dy
  if (!denominator) return Math.hypot(point.x - start.x, point.y - start.y)
  const t = Math.max(0, Math.min(1, ((point.x - start.x) * dx + (point.y - start.y) * dy) / denominator))
  return Math.hypot(point.x - (start.x + t * dx), point.y - (start.y + t * dy))
}

function fittedMap(size, bbox) {
  const [lonMin, latMin, lonMax, latMax] = bbox
  const longitudeScale = Math.cos(((latMin + latMax) / 2) * Math.PI / 180)
  const geographicAspect = ((lonMax - lonMin) * longitudeScale) / (latMax - latMin)
  let width = size.width
  let height = width / geographicAspect
  if (height > size.height) { height = size.height; width = height * geographicAspect }
  return { x: (size.width - width) / 2, y: (size.height - height) / 2, width, height }
}

function percentage(value) {
  return Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : null
}

function timestamp(value) {
  if (!value) return null
  const date = new Date(value)
  if (Number.isNaN(date.valueOf())) return null
  return `${new Intl.DateTimeFormat('en-GB', {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'UTC', hour12: false,
  }).format(date)} UTC`
}

function Metric({ label, value, tone }) {
  if (value === null || value === undefined || value === '') return null
  return <div className="metric"><dt>{label}</dt><dd className={tone ? `metric-${tone}` : ''}>{value}</dd></div>
}

export default function MapView({ onSelect, selectedMmsi }) {
  const canvasRef = useRef(null)
  const containerRef = useRef(null)
  const resultRef = useRef(null)
  const geometryRef = useRef(null)
  const panRef = useRef(null)
  const didPanRef = useRef(false)
  const [result, setResult] = useState(null)
  const [assetUrls, setAssetUrls] = useState(null)
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState('')
  const [size, setSize] = useState({ width: 0, height: 0, dpr: 1 })
  const [view, setView] = useState({ zoom: MIN_ZOOM, panX: 0, panY: 0 })

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
        resultRef.current = sceneResult
        setAssetUrls({ sceneUrl, maskUrl })
        setResult(sceneResult)
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
    const element = containerRef.current
    if (!element) return undefined
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      setSize({ width: Math.floor(width), height: Math.floor(height), dpr: Math.min(window.devicePixelRatio || 1, 2) })
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  const draw = useCallback(() => {
    const canvas = canvasRef.current
    const data = resultRef.current
    if (!canvas || !data || !size.width || !size.height) return

    canvas.width = Math.round(size.width * size.dpr)
    canvas.height = Math.round(size.height * size.dpr)
    canvas.style.width = `${size.width}px`
    canvas.style.height = `${size.height}px`
    const context = canvas.getContext('2d')
    context.setTransform(size.dpr, 0, 0, size.dpr, 0, 0)
    context.clearRect(0, 0, size.width, size.height)

    const [lonMin, latMin, lonMax, latMax] = data.scene.bbox
    const baseMap = fittedMap(size, data.scene.bbox)
    const centerX = size.width / 2
    const centerY = size.height / 2
    const map = {
      x: centerX + view.panX + (baseMap.x - centerX) * view.zoom,
      y: centerY + view.panY + (baseMap.y - centerY) * view.zoom,
      width: baseMap.width * view.zoom,
      height: baseMap.height * view.zoom,
    }
    geometryRef.current = { map, bbox: data.scene.bbox }
    const project = ([lon, lat]) => ({
      x: map.x + ((lon - lonMin) / (lonMax - lonMin)) * map.width,
      y: map.y + ((latMax - lat) / (latMax - latMin)) * map.height,
    })
    const strokePath = (points, style, width, dash = []) => {
      if (points.length < 2) return
      context.save(); context.strokeStyle = style; context.lineWidth = width; context.setLineDash(dash)
      context.beginPath(); points.forEach((point, index) => { const p = project(point); index ? context.lineTo(p.x, p.y) : context.moveTo(p.x, p.y) })
      context.stroke(); context.restore()
    }

    const slick = data.detection.slick
    const polygon = slick.polygon.filter(isPoint)
    if (polygon.length > 1) {
      context.save(); context.strokeStyle = COLORS.slick; context.lineWidth = 2.5; context.fillStyle = 'rgba(224, 80, 60, 0.22)'
      context.beginPath(); polygon.forEach((point, index) => { const p = project(point); index ? context.lineTo(p.x, p.y) : context.moveTo(p.x, p.y) }); context.closePath(); context.fill(); context.stroke(); context.restore()
      const labelPoint = isPoint(slick.centroid) ? project(slick.centroid) : project(polygon[0])
      const label = 'OIL SLICK DETECTED'
      context.save(); context.font = '700 10px system-ui, sans-serif'
      const labelWidth = context.measureText(label).width + 12
      const labelX = Math.min(map.x + map.width - labelWidth - 4, Math.max(map.x + 4, labelPoint.x + 9))
      const labelY = Math.max(map.y + 16, labelPoint.y - 10)
      context.fillStyle = 'rgba(44, 16, 13, 0.88)'; context.fillRect(labelX, labelY - 13, labelWidth, 17)
      context.strokeStyle = 'rgba(224, 80, 60, 0.85)'; context.lineWidth = 1; context.strokeRect(labelX, labelY - 13, labelWidth, 17)
      context.fillStyle = '#ffd5cc'; context.fillText(label, labelX + 6, labelY - 2); context.restore()
    }

    if (data.drift?.path?.length) {
      strokePath(data.drift.path.filter(isPoint), COLORS.drift, 1.5, [2, 6])
      if (isPoint(data.drift.origin)) {
        const origin = project(data.drift.origin)
        const kmPerPixel = ((latMax - latMin) * 111) / map.height
        const radius = Math.max(2, data.drift.uncertainty_km / kmPerPixel)
        context.save(); context.strokeStyle = 'rgba(255,255,255,.85)'; context.lineWidth = 1; context.setLineDash([3, 4]); context.beginPath(); context.arc(origin.x, origin.y, radius, 0, Math.PI * 2); context.stroke(); context.restore()
      }
    }

    data.vessels.forEach((vessel) => {
      const selected = selectedMmsi === vessel.mmsi
      const alpha = selectedMmsi == null || selected ? 1 : 0.2
      const track = Array.isArray(vessel.track) ? vessel.track : []
      context.save(); context.globalAlpha = alpha
      let run = []
      const flushRun = () => { strokePath(run, COLORS.track, selected ? 2.5 : 1.5); run = [] }
      track.forEach((point, index) => {
        if (isPoint(point)) { run.push(point); return }
        flushRun()
        const before = track[index - 1]
        const after = track.slice(index + 1).find(isPoint)
        if (isPoint(before) && isPoint(after)) {
          strokePath([before, after], COLORS.gap, selected ? 4 : 3, [8, 6])
          const a = project(before); const b = project(after)
          context.save(); context.globalAlpha = 1; context.fillStyle = COLORS.gap; context.font = '600 11px system-ui, sans-serif'; context.fillText(`AIS gap ${vessel.ais_gap_min ?? 0} min`, (a.x + b.x) / 2 + 6, (a.y + b.y) / 2 - 6); context.restore()
        }
      })
      flushRun(); context.restore()
    })

    ;(data.dark_contacts || []).forEach((contact) => {
      if (!Number.isFinite(contact.lon) || !Number.isFinite(contact.lat)) return
      const point = project([contact.lon, contact.lat])
      context.save(); context.strokeStyle = COLORS.gap; context.lineWidth = 2; context.strokeRect(point.x - 5, point.y - 5, 10, 10); context.restore()
    })
  }, [selectedMmsi, size, view])

  useEffect(() => { if (status === 'ready') draw() }, [draw, status, result])

  const handleClick = (event) => {
    if (didPanRef.current) {
      didPanRef.current = false
      return
    }
    const data = resultRef.current
    const geometry = geometryRef.current
    if (!data || !geometry) return
    const rect = event.currentTarget.getBoundingClientRect()
    const click = { x: event.clientX - rect.left, y: event.clientY - rect.top }
    const [lonMin, latMin, lonMax, latMax] = geometry.bbox
    const project = ([lon, lat]) => ({ x: geometry.map.x + ((lon - lonMin) / (lonMax - lonMin)) * geometry.map.width, y: geometry.map.y + ((latMax - lat) / (latMax - latMin)) * geometry.map.height })
    let nearest = null
    data.vessels.forEach((vessel) => {
      const track = Array.isArray(vessel.track) ? vessel.track : []
      for (let index = 1; index < track.length; index += 1) {
        if (!isPoint(track[index - 1]) || !isPoint(track[index])) continue
        const distance = distanceToSegment(click, project(track[index - 1]), project(track[index]))
        if (distance < 10 && (!nearest || distance < nearest.distance)) nearest = { mmsi: vessel.mmsi, distance }
      }
    })
    if (nearest) onSelect?.(nearest.mmsi)
  }

  const zoomAt = useCallback((targetZoom, x, y) => {
    setView((current) => {
      const zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, targetZoom))
      if (zoom === current.zoom) return current
      const centerX = size.width / 2
      const centerY = size.height / 2
      const scale = zoom / current.zoom
      return {
        zoom,
        panX: x - centerX - (x - centerX - current.panX) * scale,
        panY: y - centerY - (y - centerY - current.panY) * scale,
      }
    })
  }, [size])

  const handleWheel = (event) => {
    event.preventDefault()
    const rect = event.currentTarget.getBoundingClientRect()
    const factor = event.deltaY < 0 ? 1.2 : 1 / 1.2
    zoomAt(view.zoom * factor, event.clientX - rect.left, event.clientY - rect.top)
  }

  const handlePointerDown = (event) => {
    panRef.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, panX: view.panX, panY: view.panY }
    didPanRef.current = false
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  const handlePointerMove = (event) => {
    const pan = panRef.current
    if (!pan || pan.pointerId !== event.pointerId) return
    const deltaX = event.clientX - pan.x
    const deltaY = event.clientY - pan.y
    if (Math.hypot(deltaX, deltaY) > 3) didPanRef.current = true
    setView((current) => ({ ...current, panX: pan.panX + deltaX, panY: pan.panY + deltaY }))
  }

  const handlePointerUp = (event) => {
    if (panRef.current?.pointerId === event.pointerId) panRef.current = null
  }

  if (status === 'loading') return <section className="map-status">Loading Sentinel-1 scene…</section>
  if (status === 'error') return <section className="map-status error"><strong>Scene unavailable</strong><span>{error}</span></section>

  const primaryVessel = result.vessels.find((vessel) => vessel.mmsi === result.summary?.accused_mmsi)
    ?? result.vessels.find((vessel) => vessel.verdict === 'suspect' || vessel.verdict === 'accused')
  const hasTimeline = timestamp(result.drift?.origin_time_iso) || timestamp(result.scene?.time_iso)
  const baseMap = size.width && size.height ? fittedMap(size, result.scene.bbox) : null
  const imageryStyle = baseMap ? {
    left: baseMap.x, top: baseMap.y, width: baseMap.width, height: baseMap.height,
    transform: `translate(${view.panX}px, ${view.panY}px) scale(${view.zoom})`,
  } : undefined

  return (
    <section className="map-view" aria-label="SAR scene map">
      <div className="map-toolbar">
        <div><strong>{result.scene.satellite}</strong> · {result.scene.mode} · {result.scene.polarisation}</div>
        {result.meta?.source === 'mock' && <span className="mock-badge">MOCK DATA</span>}
      </div>
      <div className="canvas-wrap" ref={containerRef}>
        <div className="scene-layers" style={imageryStyle}>
          <img className="scene-image" src={assetUrls?.sceneUrl} alt="" />
          <img className="scene-mask" src={assetUrls?.maskUrl} alt="" />
        </div>
        <canvas ref={canvasRef} onClick={handleClick} onWheel={handleWheel} onPointerDown={handlePointerDown} onPointerMove={handlePointerMove} onPointerUp={handlePointerUp} onPointerCancel={handlePointerUp} aria-label="Oil slick, vessel tracks, AIS gaps, and drift visualization" />
        <div className="map-controls" aria-label="Map controls">
          <button type="button" onClick={() => zoomAt(view.zoom * 1.3, size.width / 2, size.height / 2)} aria-label="Zoom in">+</button>
          <button type="button" onClick={() => zoomAt(view.zoom / 1.3, size.width / 2, size.height / 2)} aria-label="Zoom out">−</button>
          <button type="button" className="reset-view" onClick={() => setView({ zoom: MIN_ZOOM, panX: 0, panY: 0 })}>Reset View</button>
        </div>
      </div>
      <div className="map-footer">
        <div className="legend"><span><i className="slick-key" />Oil slick</span><span><i className="track-key" />AIS track</span><span><i className="gap-key" />AIS gap / blackout</span><span><i className="drift-key" />Drift path</span><span><i className="dark-key" />Dark contact</span></div>
        <span>{primaryVessel ? `${primaryVessel.name} - SUSPECTED ASSOCIATION` : 'No attribution'}</span>
      </div>
      <div className="intel-panels">
        <section className="intel-panel" aria-labelledby="incident-analysis-title">
          <h2 id="incident-analysis-title">Incident analysis</h2>
          <dl className="metrics-grid">
            <Metric label="Detection" value="Oil slick" tone="alert" />
            <Metric label="Slick area" value={Number.isFinite(result.detection?.slick?.area_km2) ? `${result.detection.slick.area_km2.toFixed(1)} km²` : null} />
            <Metric label="Detection confidence" value={percentage(result.detection?.confidence)} />
            <Metric label="Status" value={primaryVessel ? 'Suspected association' : 'No attribution'} tone={primaryVessel ? 'alert' : ''} />
            <Metric label="Relevant vessel" value={primaryVessel?.name} />
            <Metric label="AIS blackout" value={Number.isFinite(primaryVessel?.ais_gap_min) ? `${primaryVessel.ais_gap_min} min` : null} />
            <Metric label="Closest approach" value={Number.isFinite(primaryVessel?.dist_km) ? `${primaryVessel.dist_km.toFixed(2)} km` : null} />
            <Metric label="Attribution score" value={percentage(primaryVessel?.score)} />
          </dl>
        </section>

        {primaryVessel && <section className="intel-panel attribution-panel" aria-labelledby="attribution-title">
          <h2 id="attribution-title">Vessel attribution</h2>
          <div className="vessel-heading"><strong>{primaryVessel.name}</strong><span>{percentage(primaryVessel.score)} correlation score</span></div>
          <p className="association-note">Suspected association based on satellite detection and AIS correlation; this is not a determination of cause.</p>
          <ul className="evidence-list">
            {Number.isFinite(primaryVessel.dist_km) && <li>Spatial proximity: {primaryVessel.dist_km.toFixed(2)} km closest approach</li>}
            {primaryVessel.ais_gap_min > 0 && <li>AIS blackout detected: {primaryVessel.ais_gap_min} min</li>}
            {Number.isFinite(primaryVessel.temporality) && <li>Temporal correlation: {percentage(primaryVessel.temporality)}</li>}
            {Number.isFinite(primaryVessel.parity) && <li>Track/slick parity: {percentage(primaryVessel.parity)}</li>}
            {result.drift?.path?.length > 1 && <li>Back-advection path available for review</li>}
          </ul>
        </section>}

        {hasTimeline && <section className="intel-panel timeline-panel" aria-labelledby="timeline-title">
          <h2 id="timeline-title">Timeline</h2>
          <ol className="timeline">
            {timestamp(result.drift?.origin_time_iso) && <li><time>{timestamp(result.drift.origin_time_iso)}</time><span>Back-advection origin</span></li>}
            {timestamp(result.scene?.time_iso) && <li><time>{timestamp(result.scene.time_iso)}</time><span>Satellite detection</span></li>}
            {primaryVessel && <li><time>Result</time><span>Suspected association flagged</span></li>}
          </ol>
          {primaryVessel?.ais_gap_min > 0 && <p className="timeline-note">AIS gap duration is available, but individual AIS track timestamps are not present in this result.</p>}
        </section>}
      </div>
    </section>
  )
}
