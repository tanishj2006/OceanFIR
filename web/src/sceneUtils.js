export function isPoint(value) {
  return Array.isArray(value) && Number.isFinite(value[0]) && Number.isFinite(value[1])
}

export function validateResult(data) {
  const bbox = data?.scene?.bbox
  if (!Array.isArray(bbox) || bbox.length !== 4 || !bbox.every(Number.isFinite)) {
    throw new Error('The result did not contain a valid scene bounding box.')
  }
  if (!data?.detection?.slick?.polygon || !Array.isArray(data.vessels)) {
    throw new Error('The result did not contain the required scene data.')
  }
  return data
}

export function loadImage(url) {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.crossOrigin = 'anonymous'
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error(`Could not load scene imagery: ${url}`))
    image.src = url
  })
}

export function percentage(value, digits = 1) {
  if (!Number.isFinite(value)) return null
  return `${(value * 100).toFixed(digits)}%`
}

export function formatKm(value, digits = 2) {
  if (!Number.isFinite(value)) return null
  return `${value.toFixed(digits)} km`
}

export function formatCoord(lon, lat) {
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) return null
  return `${lat.toFixed(4)}°, ${lon.toFixed(4)}°`
}

export function timestamp(value) {
  if (!value) return null
  const date = new Date(value)
  if (Number.isNaN(date.valueOf())) return null
  return `${new Intl.DateTimeFormat('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'UTC',
    hour12: false,
  }).format(date)} UTC`
}

export function primaryVessel(result) {
  if (!result?.vessels) return null
  return result.vessels.find((vessel) => vessel.mmsi === result.summary?.accused_mmsi)
    ?? result.vessels.find((vessel) => vessel.verdict === 'suspect' || vessel.verdict === 'accused')
    ?? null
}

export function incidentStatus(result, vessel) {
  const verdict = result?.summary?.verdict
  if (verdict === 'no_attribution') return 'No attribution'
  if (vessel?.verdict === 'accused') return 'Suspected oil spill'
  if (vessel?.verdict === 'suspect') return 'Suspect association'
  if (result?.detection?.slick) return 'Oil slick detected'
  return 'Scene loaded'
}

export function firstGap(track) {
  if (!Array.isArray(track)) return null
  const index = track.findIndex((point) => point == null)
  if (index < 0) return null
  const before = [...track.slice(0, index)].reverse().find(isPoint) ?? null
  const after = track.slice(index + 1).find(isPoint) ?? null
  return { index, before, after }
}

export function buildReportText(result) {
  const vessel = primaryVessel(result)
  const lines = [
    'OceanFIR incident report',
    `Generated (local): ${new Date().toISOString()}`,
    '',
    `Scene: ${result.scene?.id ?? 'unknown'}`,
    `Satellite: ${result.scene?.satellite ?? '—'} · ${result.scene?.mode ?? '—'} · ${result.scene?.polarisation ?? '—'}`,
    `Detection time: ${timestamp(result.scene?.time_iso) ?? result.scene?.time ?? '—'}`,
    `Data source: ${result.meta?.source === 'mock' ? 'Mock data' : result.meta?.source ?? 'pipeline'}`,
    '',
    `Summary: ${result.summary?.note ?? incidentStatus(result, vessel)}`,
    `Verdict: ${result.summary?.verdict ?? '—'}`,
    `Slick area: ${Number.isFinite(result.detection?.slick?.area_km2) ? `${result.detection.slick.area_km2} km²` : '—'}`,
    `Detection confidence: ${percentage(result.detection?.confidence) ?? '—'}`,
  ]
  if (vessel) {
    lines.push(
      '',
      `Vessel: ${vessel.name ?? 'Unknown'}`,
      `MMSI: ${vessel.mmsi ?? '—'}`,
      `Type: ${vessel.type ?? '—'}`,
      `Length: ${Number.isFinite(vessel.len_m) ? `${vessel.len_m} m` : '—'}`,
      `Correlation score: ${percentage(vessel.score) ?? '—'}`,
      `AIS gap: ${Number.isFinite(vessel.ais_gap_min) ? `${vessel.ais_gap_min} min` : '—'}`,
      `Proximity: ${formatKm(vessel.dist_km) ?? '—'}`,
      `Temporal alignment: ${percentage(vessel.temporality) ?? '—'}`,
      `Track/slick parity: ${percentage(vessel.parity) ?? '—'}`,
    )
  }
  if (result.drift) {
    lines.push(
      '',
      `Drift method: ${result.drift.method ?? '—'}`,
      `Origin time: ${timestamp(result.drift.origin_time_iso) ?? '—'}`,
      `Uncertainty: ${formatKm(result.drift.uncertainty_km) ?? '—'}`,
    )
  }
  return lines.join('\n')
}
