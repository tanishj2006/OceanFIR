import { useCallback, useEffect, useRef, useState } from 'react'
import { firstGap, formatCoord, formatKm, isPoint, percentage, timestamp } from '../sceneUtils'
import './MapView.css'

const COLORS = {
  slick: '#E0503C',
  track: '#E0A54B',
  gap: '#5CC8D4',
  drift: '#FFFFFF',
}

const MIN_ZOOM = 1
const MAX_ZOOM = 6

const DEFAULT_LAYERS = {
  slick: true,
  aisTrack: true,
  aisGap: true,
  drift: true,
  darkContact: true,
  prediction: true,
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

function projectPoint(map, bbox, lon, lat) {
  const [lonMin, latMin, lonMax, latMax] = bbox
  return {
    x: map.x + ((lon - lonMin) / (lonMax - lonMin)) * map.width,
    y: map.y + ((latMax - lat) / (latMax - latMin)) * map.height,
  }
}

function distanceToSegment(point, start, end) {
  const dx = end.x - start.x
  const dy = end.y - start.y
  const denominator = dx * dx + dy * dy
  if (!denominator) return Math.hypot(point.x - start.x, point.y - start.y)
  const t = Math.max(0, Math.min(1, ((point.x - start.x) * dx + (point.y - start.y) * dy) / denominator))
  return Math.hypot(point.x - (start.x + t * dx), point.y - (start.y + t * dy))
}

function pointInPolygon(point, polygon) {
  let inside = false
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const xi = polygon[i].x
    const yi = polygon[i].y
    const xj = polygon[j].x
    const yj = polygon[j].y
    if ((yi > point.y) !== (yj > point.y) && point.x < ((xj - xi) * (point.y - yi)) / (yj - yi) + xi) {
      inside = !inside
    }
  }
  return inside
}

function viewMap(size, bbox, view) {
  const baseMap = fittedMap(size, bbox)
  const centerX = size.width / 2
  const centerY = size.height / 2
  return {
    x: centerX + view.panX + (baseMap.x - centerX) * view.zoom,
    y: centerY + view.panY + (baseMap.y - centerY) * view.zoom,
    width: baseMap.width * view.zoom,
    height: baseMap.height * view.zoom,
  }
}

export default function MapView({
  result,
  assetUrls,
  selectedMmsi,
  onSelect,
  highlight,
  onHighlight,
}) {
  const canvasRef = useRef(null)
  const containerRef = useRef(null)
  const geometryRef = useRef(null)
  const panRef = useRef(null)
  const didPanRef = useRef(false)
  const viewRef = useRef({ zoom: MIN_ZOOM, panX: 0, panY: 0 })
  const [size, setSize] = useState({ width: 0, height: 0, dpr: 1 })
  const [view, setView] = useState({ zoom: MIN_ZOOM, panX: 0, panY: 0 })
  const [layers, setLayers] = useState(DEFAULT_LAYERS)
  const [slickOpacity, setSlickOpacity] = useState(0.22)
  const [maskOpacity, setMaskOpacity] = useState(0.45)
  const [tooltip, setTooltip] = useState(null)
  const [layersOpen, setLayersOpen] = useState(false)
  const layersRef = useRef(null)

  viewRef.current = view

  useEffect(() => {
    if (!layersOpen) return undefined
    const onDown = (e) => {
      if (layersRef.current && !layersRef.current.contains(e.target)) setLayersOpen(false)
    }
    const onKey = (e) => { if (e.key === 'Escape') setLayersOpen(false) }
    document.addEventListener('pointerdown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [layersOpen])

  useEffect(() => {
    const element = containerRef.current
    if (!element) return undefined
    const apply = (width, height) => setSize({
      width: Math.floor(width),
      height: Math.floor(height),
      dpr: Math.min(window.devicePixelRatio || 1, 2),
    })
    // Measure once on mount. The observer's first notification can be dropped
    // by the browser when layout is still settling (the evidence column is
    // still growing as its content loads), and without a fallback measurement
    // size stays 0x0 -- the canvas keeps its default 300x150 and the scene
    // imagery renders at zero width, i.e. a blank map until something else
    // forces a resize.
    const rect = element.getBoundingClientRect()
    if (rect.width && rect.height) apply(rect.width, rect.height)
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      apply(width, height)
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  const inspect = useCallback((local, data, geometry) => {
    if (!data || !geometry) return null
    const project = ([lon, lat]) => projectPoint(geometry.map, geometry.bbox, lon, lat)
    let nearest = null

    if (layers.darkContact) {
      for (const contact of data.dark_contacts || []) {
        if (!Number.isFinite(contact.lon) || !Number.isFinite(contact.lat)) continue
        const point = project([contact.lon, contact.lat])
        const distance = Math.hypot(local.x - point.x, local.y - point.y)
        if (distance < 12 && (!nearest || distance < nearest.distance)) {
          nearest = { kind: 'dark', distance, contact }
        }
      }
    }

    data.vessels.forEach((vessel) => {
      const track = Array.isArray(vessel.track) ? vessel.track : []
      for (let index = 1; index < track.length; index += 1) {
        const prev = track[index - 1]
        const next = track[index]
        if (prev == null || next == null) {
          const before = isPoint(prev) ? prev : [...track.slice(0, index)].reverse().find(isPoint)
          const after = isPoint(next) ? next : track.slice(index + 1).find(isPoint)
          if (layers.aisGap && isPoint(before) && isPoint(after)) {
            const distance = distanceToSegment(local, project(before), project(after))
            if (distance < 10 && (!nearest || distance < nearest.distance)) {
              nearest = { kind: 'gap', distance, vessel, before, after }
            }
          }
          continue
        }
        if (layers.aisTrack && isPoint(prev) && isPoint(next)) {
          const distance = distanceToSegment(local, project(prev), project(next))
          if (distance < 10 && (!nearest || distance < nearest.distance)) {
            nearest = { kind: 'vessel', distance, vessel }
          }
        }
      }
    })

    if (layers.prediction && data.drift?.origin && Number.isFinite(data.drift.uncertainty_km)) {
      const origin = project(data.drift.origin)
      const kmPerPixel = ((geometry.bbox[3] - geometry.bbox[1]) * 111) / geometry.map.height
      const radius = Math.max(2, data.drift.uncertainty_km / kmPerPixel)
      const distance = Math.hypot(local.x - origin.x, local.y - origin.y)
      if (Math.abs(distance - radius) < 8 || distance <= radius) {
        if (!nearest) nearest = { kind: 'prediction', distance, drift: data.drift }
      }
    }

    if (!nearest && layers.slick) {
      const polygon = data.detection.slick.polygon.filter(isPoint).map(project)
      if (polygon.length > 2 && pointInPolygon(local, polygon)) {
        nearest = { kind: 'slick', distance: 0, slick: data.detection.slick }
      }
    }

    return nearest
  }, [layers])

  const draw = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas || !result || !size.width || !size.height) return

    canvas.width = Math.round(size.width * size.dpr)
    canvas.height = Math.round(size.height * size.dpr)
    canvas.style.width = `${size.width}px`
    canvas.style.height = `${size.height}px`
    const context = canvas.getContext('2d')
    context.setTransform(size.dpr, 0, 0, size.dpr, 0, 0)
    context.clearRect(0, 0, size.width, size.height)

    const bbox = result.scene.bbox
    const map = viewMap(size, bbox, view)
    geometryRef.current = { map, bbox }
    const project = ([lon, lat]) => projectPoint(map, bbox, lon, lat)
    const strokePath = (points, style, width, dash = []) => {
      if (points.length < 2) return
      context.save(); context.strokeStyle = style; context.lineWidth = width; context.setLineDash(dash)
      context.beginPath(); points.forEach((point, index) => { const p = project(point); index ? context.lineTo(p.x, p.y) : context.moveTo(p.x, p.y) })
      context.stroke(); context.restore()
    }

    const slick = result.detection.slick
    const polygon = slick.polygon.filter(isPoint)
    const slickActive = highlight?.kind === 'slick'
    if (layers.slick && polygon.length > 1) {
      context.save()
      context.strokeStyle = COLORS.slick
      context.lineWidth = slickActive ? 4 : 2.5
      context.fillStyle = `rgba(224, 80, 60, ${slickActive ? Math.min(0.45, slickOpacity + 0.16) : slickOpacity})`
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

    if (result.drift?.path?.length && (layers.drift || layers.prediction)) {
      if (layers.drift) strokePath(result.drift.path.filter(isPoint), COLORS.drift, highlight?.kind === 'prediction' ? 2.4 : 1.5, [2, 6])
      if (layers.prediction && isPoint(result.drift.origin)) {
        const origin = project(result.drift.origin)
        const kmPerPixel = ((bbox[3] - bbox[1]) * 111) / map.height
        const radius = Math.max(2, result.drift.uncertainty_km / kmPerPixel)
        context.save()
        context.fillStyle = highlight?.kind === 'prediction' ? 'rgba(92,200,212,0.16)' : 'rgba(92,200,212,0.08)'
        context.strokeStyle = 'rgba(255,255,255,.85)'
        context.lineWidth = 1
        context.setLineDash([3, 4])
        context.beginPath()
        context.arc(origin.x, origin.y, radius, 0, Math.PI * 2)
        context.fill()
        context.stroke()
        context.restore()
      }
    }

    result.vessels.forEach((vessel) => {
      const selected = selectedMmsi === vessel.mmsi || highlight?.vessel?.mmsi === vessel.mmsi
      const alpha = selectedMmsi == null || selected || highlight?.kind === 'slick' ? 1 : 0.22
      const track = Array.isArray(vessel.track) ? vessel.track : []
      context.save(); context.globalAlpha = alpha
      let run = []
      const flushRun = () => {
        if (layers.aisTrack) strokePath(run, COLORS.track, selected ? 2.8 : 1.5)
        run = []
      }
      track.forEach((point, index) => {
        if (isPoint(point)) { run.push(point); return }
        flushRun()
        const before = track[index - 1]
        const after = track.slice(index + 1).find(isPoint)
        if (layers.aisGap && isPoint(before) && isPoint(after)) {
          const gapActive = highlight?.kind === 'gap' && highlight.vessel?.mmsi === vessel.mmsi
          strokePath([before, after], COLORS.gap, gapActive || selected ? 4.5 : 3, [8, 6])
          const a = project(before); const b = project(after)
          context.save(); context.globalAlpha = 1; context.fillStyle = COLORS.gap; context.font = '600 11px system-ui, sans-serif'
          context.fillText(`AIS gap ${vessel.ais_gap_min ?? 0} min`, (a.x + b.x) / 2 + 6, (a.y + b.y) / 2 - 6)
          context.restore()
        }
      })
      flushRun(); context.restore()
    })

    if (layers.darkContact) {
      ;(result.dark_contacts || []).forEach((contact) => {
        if (!Number.isFinite(contact.lon) || !Number.isFinite(contact.lat)) return
        const point = project([contact.lon, contact.lat])
        const active = highlight?.kind === 'dark' && highlight.contact?.id === contact.id
        context.save()
        context.strokeStyle = COLORS.gap
        context.lineWidth = active ? 3 : 2
        context.fillStyle = active ? 'rgba(92,200,212,0.25)' : 'transparent'
        context.fillRect(point.x - 5, point.y - 5, 10, 10)
        context.strokeRect(point.x - 5, point.y - 5, 10, 10)
        context.restore()
      })
    }
  }, [highlight, layers, result, selectedMmsi, size, slickOpacity, view])

  useEffect(() => { draw() }, [draw])

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

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return undefined
    const onWheel = (event) => {
      event.preventDefault()
      const rect = canvas.getBoundingClientRect()
      const factor = event.deltaY < 0 ? 1.2 : 1 / 1.2
      const current = viewRef.current
      zoomAt(current.zoom * factor, event.clientX - rect.left, event.clientY - rect.top)
    }
    canvas.addEventListener('wheel', onWheel, { passive: false })
    return () => canvas.removeEventListener('wheel', onWheel)
  }, [zoomAt])

  const localPoint = (event) => {
    const rect = event.currentTarget.getBoundingClientRect()
    return { x: event.clientX - rect.left, y: event.clientY - rect.top }
  }

  const handleClick = (event) => {
    if (didPanRef.current) {
      didPanRef.current = false
      return
    }
    const hit = inspect(localPoint(event), result, geometryRef.current)
    if (hit?.vessel) onSelect?.(hit.vessel.mmsi)
  }

  const handlePointerDown = (event) => {
    panRef.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, panX: view.panX, panY: view.panY }
    didPanRef.current = false
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  const handlePointerMove = (event) => {
    const pan = panRef.current
    if (pan && pan.pointerId === event.pointerId) {
      const deltaX = event.clientX - pan.x
      const deltaY = event.clientY - pan.y
      if (Math.hypot(deltaX, deltaY) > 3) didPanRef.current = true
      setView((current) => ({ ...current, panX: pan.panX + deltaX, panY: pan.panY + deltaY }))
      setTooltip(null)
      return
    }
    const local = localPoint(event)
    const hit = inspect(local, result, geometryRef.current)
    onHighlight?.(hit)
    if (!hit) {
      setTooltip(null)
      return
    }
    setTooltip({ x: local.x, y: local.y, hit })
  }

  const handlePointerUp = (event) => {
    if (panRef.current?.pointerId === event.pointerId) panRef.current = null
  }

  const handlePointerLeave = () => {
    setTooltip(null)
    onHighlight?.(null)
  }

  const toggleLayer = (key) => setLayers((current) => ({ ...current, [key]: !current[key] }))

  // The map block takes its height from the SCENE's own geometry, not from
  // whatever the evidence panel happens to be doing. Before this, .canvas-wrap
  // was flex:1 inside a stretched grid row, so expanding an accordion on the
  // right grew the map too -- and the imagery sat centred in the extra space.
  const [bLonMin, bLatMin, bLonMax, bLatMax] = result.scene.bbox
  const geoAspect = ((bLonMax - bLonMin) *
    Math.cos(((bLatMin + bLatMax) / 2) * Math.PI / 180)) / (bLatMax - bLatMin)

  const baseMap = size.width && size.height ? fittedMap(size, result.scene.bbox) : null
  const imageryStyle = baseMap ? {
    left: baseMap.x,
    top: baseMap.y,
    width: baseMap.width,
    height: baseMap.height,
    transform: `translate(${view.panX}px, ${view.panY}px) scale(${view.zoom})`,
  } : undefined

  const tooltipCopy = tooltip?.hit ? tooltipContent(tooltip.hit) : null

  return (
    <section className="map-view" aria-label="SAR scene map">
      <div className="map-toolbar">
        <div>
          <strong>{result.scene.satellite}</strong>
          <span> · {result.scene.mode} · {result.scene.polarisation}</span>
        </div>
        <div className="map-toolbar-status">
          <div className="layers-menu" ref={layersRef}>
            <button
              type="button"
              className="layers-trigger"
              aria-expanded={layersOpen}
              aria-haspopup="true"
              onClick={() => setLayersOpen((open) => !open)}
            >
              Layers <span className="chev" aria-hidden="true">{layersOpen ? '▴' : '▾'}</span>
            </button>
            {layersOpen && (
              <div className="layers-panel" role="group" aria-label="Layer controls">
                <h2>Layers</h2>
                <LayerToggle label="Oil slick" color="#E0503C" checked={layers.slick} onChange={() => toggleLayer('slick')} />
                <LayerToggle label="AIS track" color="#E0A54B" checked={layers.aisTrack} onChange={() => toggleLayer('aisTrack')} />
                <LayerToggle label="AIS gap / blackout" color="#5CC8D4" checked={layers.aisGap} onChange={() => toggleLayer('aisGap')} />
                <LayerToggle label="Drift path" color="#FFFFFF" checked={layers.drift} onChange={() => toggleLayer('drift')} />
                <LayerToggle label="Dark contact" color="#5CC8D4" checked={layers.darkContact} onChange={() => toggleLayer('darkContact')} />
                <LayerToggle label="Prediction zone" color="#7fd4de" checked={layers.prediction} onChange={() => toggleLayer('prediction')} />
                <label className="opacity-control">
                  <span>Slick opacity</span>
                  <input type="range" min="0.05" max="0.6" step="0.01" value={slickOpacity} onChange={(event) => setSlickOpacity(Number(event.target.value))} />
                </label>
                <label className="opacity-control">
                  <span>Detection mask</span>
                  <input type="range" min="0" max="0.8" step="0.01" value={maskOpacity} onChange={(event) => setMaskOpacity(Number(event.target.value))} />
                </label>
              </div>
            )}
          </div>
          <span className="status-ok">SAR image loaded</span>
          {result.meta?.source === 'mock' && <span className="mock-badge">Mock data</span>}
        </div>
      </div>
      <div className="canvas-wrap" ref={containerRef} style={{ aspectRatio: geoAspect }}>
        <div className="scene-layers" style={imageryStyle}>
          <img className="scene-image" src={assetUrls?.sceneUrl} alt="Sentinel-1 SAR scene" />
          <img className="scene-mask" src={assetUrls?.maskUrl} alt="" style={{ opacity: maskOpacity }} />
        </div>
        <canvas
          ref={canvasRef}
          onClick={handleClick}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerUp}
          onPointerLeave={handlePointerLeave}
          aria-label="Oil slick, vessel tracks, AIS gaps, and drift visualization"
        />
        <div className="map-controls" aria-label="Map controls">
          <button type="button" onClick={() => zoomAt(view.zoom * 1.3, size.width / 2, size.height / 2)} aria-label="Zoom in">+</button>
          <button type="button" onClick={() => zoomAt(view.zoom / 1.3, size.width / 2, size.height / 2)} aria-label="Zoom out">−</button>
          <button type="button" className="reset-view" onClick={() => setView({ zoom: MIN_ZOOM, panX: 0, panY: 0 })}>Fit</button>
          <span className="zoom-readout">{Math.round(view.zoom * 100)}%</span>
        </div>
        {tooltipCopy && (
          <div className="map-tooltip" style={{ left: tooltip.x + 14, top: tooltip.y + 14 }} role="tooltip">
            <strong>{tooltipCopy.title}</strong>
            {tooltipCopy.lines.map((line) => <span key={line}>{line}</span>)}
          </div>
        )}
      </div>
      <div className="map-footer">
        <div className="legend">
          <span><i className="slick-key" />Oil slick</span>
          <span><i className="track-key" />AIS track</span>
          <span><i className="gap-key" />AIS gap / blackout</span>
          <span><i className="drift-key" />Drift path</span>
          <span><i className="dark-key" />Dark contact</span>
        </div>
        <span>Drag to pan · Scroll to zoom</span>
      </div>
    </section>
  )
}

function LayerToggle({ label, color, checked, onChange }) {
  return (
    <label className="layer-toggle">
      <input type="checkbox" checked={checked} onChange={onChange} />
      <i style={{ background: color }} />
      <span>{label}</span>
    </label>
  )
}

function tooltipContent(hit) {
  if (hit.kind === 'slick') {
    return {
      title: 'Oil slick',
      lines: [
        hit.slick.area_km2 != null ? `Area ${hit.slick.area_km2.toFixed(1)} km²` : null,
        hit.slick.length_km != null ? `Length ${hit.slick.length_km.toFixed(1)} km` : null,
      ].filter(Boolean),
    }
  }
  if (hit.kind === 'vessel') {
    return {
      title: hit.vessel.name || `MMSI ${hit.vessel.mmsi}`,
      lines: [
        hit.vessel.type ? `Type ${hit.vessel.type}` : null,
        `MMSI ${hit.vessel.mmsi}`,
        percentage(hit.vessel.score) ? `Score ${percentage(hit.vessel.score)}` : null,
        formatKm(hit.vessel.dist_km) ? `Proximity ${formatKm(hit.vessel.dist_km)}` : null,
      ].filter(Boolean),
    }
  }
  if (hit.kind === 'gap') {
    const gap = firstGap(hit.vessel.track)
    return {
      title: 'AIS blackout',
      lines: [
        `${hit.vessel.name || hit.vessel.mmsi}`,
        Number.isFinite(hit.vessel.ais_gap_min) ? `Duration ${hit.vessel.ais_gap_min} min` : null,
        gap?.before ? `Last report ${formatCoord(gap.before[0], gap.before[1])}` : null,
        gap?.after ? `Resume ${formatCoord(gap.after[0], gap.after[1])}` : null,
      ].filter(Boolean),
    }
  }
  if (hit.kind === 'dark') {
    return {
      title: 'Dark contact',
      lines: [
        hit.contact.id,
        formatCoord(hit.contact.lon, hit.contact.lat),
        Number.isFinite(hit.contact.len_px) ? `${hit.contact.len_px} px signature` : null,
      ].filter(Boolean),
    }
  }
  if (hit.kind === 'prediction') {
    return {
      title: 'Prediction zone',
      lines: [
        hit.drift.method || 'Back-advection',
        timestamp(hit.drift.origin_time_iso),
        formatKm(hit.drift.uncertainty_km) ? `Uncertainty ${formatKm(hit.drift.uncertainty_km)}` : null,
      ].filter(Boolean),
    }
  }
  return { title: 'Scene', lines: [] }
}
