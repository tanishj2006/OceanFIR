import { useState } from 'react'
import {
  firstGap,
  formatCoord,
  formatKm,
  incidentStatus,
  percentage,
  primaryVessel,
  timestamp,
} from '../sceneUtils'
import './EvidencePanel.css'

export default function EvidencePanel({ result, highlight, selectedMmsi }) {
  const vessel = result.vessels.find((item) => item.mmsi === selectedMmsi) ?? primaryVessel(result)
  const slick = result.detection?.slick
  const gap = vessel ? firstGap(vessel.track) : null
  const status = incidentStatus(result, vessel)

  return (
    <aside className="evidence-panel" aria-label="Incident evidence">
      <section className={`glance-card ${highlight?.kind === 'vessel' || highlight?.kind === 'slick' ? 'is-hot' : ''}`}>
        <p className="eyebrow">At a glance</p>
        {vessel ? (
          <>
            <h2>{vessel.name || `MMSI ${vessel.mmsi}`}</h2>
            <p className="glance-type">{vessel.type || 'Unknown type'}</p>
            <p className="glance-status">{status}</p>
            <ul className="glance-stats">
              {Number.isFinite(vessel.score) && (
                <li>
                  <span>High-risk association</span>
                  <strong>{percentage(vessel.score)} match</strong>
                </li>
              )}
              {Number.isFinite(vessel.ais_gap_min) && (
                <li>
                  <span>AIS gap</span>
                  <strong>{vessel.ais_gap_min} min</strong>
                </li>
              )}
              {Number.isFinite(vessel.dist_km) && (
                <li>
                  <span>Proximity</span>
                  <strong>{formatKm(vessel.dist_km, vessel.dist_km < 1 ? 2 : 1)}</strong>
                </li>
              )}
            </ul>
          </>
        ) : (
          <>
            <h2>No attribution</h2>
            <p className="glance-status">{result.summary?.note || 'No vessel was accused for this scene.'}</p>
          </>
        )}
        {result.summary?.note && <p className="glance-note">{result.summary.note}</p>}
      </section>

      <Timeline result={result} vessel={vessel} gap={gap} highlight={highlight} />

      <section className="metrics-card">
        <h2>Key metrics</h2>
        <MetricBar label="Correlation score" value={vessel?.score} tone="amber" active={highlight?.kind === 'vessel'} />
        <MetricBar label="Detection confidence" value={result.detection?.confidence} tone="cyan" active={highlight?.kind === 'slick'} />
        <MetricBar label="Temporal alignment" value={vessel?.temporality} tone="green" active={highlight?.kind === 'gap'} />
      </section>

      <div className="detail-stack">
        <DetailCard id="attribution" title="Vessel attribution" open={highlight?.kind === 'vessel' || highlight?.kind === 'gap'}>
          {vessel ? (
            <>
              <p><strong>{vessel.name}</strong> · MMSI {vessel.mmsi}</p>
              <p>Type {vessel.type || '—'}{Number.isFinite(vessel.len_m) ? ` · ${vessel.len_m} m` : ''}</p>
              <p>Verdict: {vessel.verdict}</p>
              {Number.isFinite(vessel.score) && <p>Correlation score: {percentage(vessel.score)}</p>}
              {Number.isFinite(vessel.proximity) && <p>Proximity component: {percentage(vessel.proximity)}</p>}
              {Number.isFinite(vessel.parity) && <p>Track/slick parity: {percentage(vessel.parity)}</p>}
              {Number.isFinite(vessel.silence) && <p>Silence component: {percentage(vessel.silence)}</p>}
              {vessel.dark && <p>Dark-activity flag is set on this vessel.</p>}

              {/* Look the vessel up on the public registries. OceanFIR names a
                  candidate from one scene; an investigator still has to check
                  who owns it and whether it has a record. These open in a new
                  tab and the app does not depend on them -- the demo works with
                  the network off, which is the whole reason there are no map
                  tiles either. */}
              <div className="vessel-lookup">
                <span className="vessel-lookup-label">Look up this vessel</span>
                <a
                  href={`https://www.marinetraffic.com/en/ais/details/ships/mmsi:${vessel.mmsi}`}
                  target="_blank"
                  rel="noreferrer noopener"
                >Live position &amp; particulars ↗</a>
                <a
                  href="https://www.equasis.org/"
                  target="_blank"
                  rel="noreferrer noopener"
                >Equasis — owner, class, PSC record ↗</a>
                <a
                  href="https://www.iomou.org/inspmain.htm"
                  target="_blank"
                  rel="noreferrer noopener"
                >Indian Ocean MoU — inspection history ↗</a>
              </div>
            </>
          ) : <p>No accused or suspect vessel in this result.</p>}
        </DetailCard>

        <DetailCard id="sar" title="SAR detection" open={highlight?.kind === 'slick'}>
          <p>Method: {result.detection?.method || '—'}</p>
          <p>Confidence: {percentage(result.detection?.confidence) || '—'}</p>
          {Number.isFinite(result.detection?.lookalike_prob) && <p>Look-alike probability: {percentage(result.detection.lookalike_prob)}</p>}
          {Number.isFinite(slick?.area_km2) && <p>Slick area: {slick.area_km2.toFixed(1)} km²</p>}
          {Number.isFinite(slick?.length_km) && <p>Length: {slick.length_km.toFixed(1)} km</p>}
          {Number.isFinite(slick?.coverage_pct) && <p>Scene coverage: {percentage(slick.coverage_pct)}</p>}
          {Array.isArray(slick?.age_hours_est) && <p>Estimated age: {slick.age_hours_est.join('–')} hours</p>}
          <p>Scene time: {timestamp(result.scene?.time_iso) || result.scene?.time || '—'}</p>
        </DetailCard>

        <DetailCard id="ais" title="AIS analysis" open={highlight?.kind === 'gap'}>
          {vessel ? (
            <>
              <p>AIS gap: {Number.isFinite(vessel.ais_gap_min) ? `${vessel.ais_gap_min} min` : 'None recorded'}</p>
              {gap?.before && <p>Last known position: {formatCoord(gap.before[0], gap.before[1])}</p>}
              {gap?.after && <p>Resume position: {formatCoord(gap.after[0], gap.after[1])}</p>}
              {!gap && <p>No AIS reporting gap is encoded in this track.</p>}
              <p>Track points are lon/lat pairs; individual AIS timestamps are not present in this result.</p>
            </>
          ) : <p>No vessel track selected.</p>}
        </DetailCard>

        <DetailCard id="drift" title="Drift prediction" open={highlight?.kind === 'prediction'}>
          {result.drift ? (
            <>
              <p>Method: {result.drift.method || '—'}</p>
              <p>Origin time: {timestamp(result.drift.origin_time_iso) || '—'}</p>
              {result.drift.origin && <p>Origin: {formatCoord(result.drift.origin[0], result.drift.origin[1])}</p>}
              <p>Uncertainty: {formatKm(result.drift.uncertainty_km) || '—'}</p>
              <p>Path samples: {result.drift.path?.length ?? 0}</p>
            </>
          ) : <p>No drift product is available for this scene.</p>}
        </DetailCard>

        <DetailCard id="confidence" title="Confidence & correlation">
          <p>Detection confidence: {percentage(result.detection?.confidence) || '—'}</p>
          <p>Correlation score: {percentage(vessel?.score) || '—'}</p>
          <p>Temporal alignment: {percentage(vessel?.temporality) || '—'}</p>
          <p>Decision threshold: {percentage(result.summary?.threshold) || '—'}</p>
          <p>Vessels scored: {result.summary?.n_scored ?? result.vessels.length}</p>
          <p>Suspects: {result.summary?.n_suspect ?? '—'} · Cleared: {result.summary?.n_cleared ?? '—'}</p>
        </DetailCard>
      </div>

      <section className="similar-card">
        <h2>Similar incidents</h2>
        <p>No historical incidents available yet.</p>
      </section>
    </aside>
  )
}

function Timeline({ result, vessel, gap, highlight }) {
  const sarTime = timestamp(result.scene?.time_iso)
  const driftTime = timestamp(result.drift?.origin_time_iso)
  const events = [
    {
      id: 'last-ais',
      title: 'Last known AIS position',
      detail: gap?.before ? formatCoord(gap.before[0], gap.before[1]) : 'Not encoded as a timestamped AIS fix',
      time: null,
      kind: 'ais',
    },
    {
      id: 'blackout-start',
      title: 'Blackout start',
      detail: Number.isFinite(vessel?.ais_gap_min)
        ? `${vessel.ais_gap_min} min gap begins after the last AIS report`
        : 'No AIS gap duration in this result',
      time: null,
      kind: 'blackout',
    },
    {
      id: 'blackout-end',
      title: 'Blackout end',
      detail: gap?.after ? `Resume ${formatCoord(gap.after[0], gap.after[1])}` : 'Resume position not available',
      time: null,
      kind: 'blackout',
    },
    {
      id: 'sar',
      title: 'SAR detection',
      detail: `${result.scene?.satellite || 'Sentinel-1'} ${result.scene?.mode || ''}`.trim(),
      time: sarTime,
      kind: 'sar',
    },
    {
      id: 'drift',
      title: 'Drift prediction',
      detail: result.drift
        ? `${result.drift.method || 'Back-advection'}${result.drift.uncertainty_km != null ? ` · ${formatKm(result.drift.uncertainty_km)} uncertainty` : ''}`
        : 'No drift product',
      time: driftTime,
      kind: 'drift',
    },
  ]

  return (
    <section className="timeline-card" aria-label="Incident timeline">
      <h2>Timeline</h2>
      <div className="timeline-track">
        <div className="timeline-blackout" title={Number.isFinite(vessel?.ais_gap_min) ? `AIS blackout ${vessel.ais_gap_min} min` : 'AIS blackout'} />
        {events.map((event) => (
          <div
            key={event.id}
            className={`timeline-node ${event.kind} ${highlight?.kind === 'gap' && event.kind === 'blackout' ? 'is-hot' : ''} ${highlight?.kind === 'slick' && event.kind === 'sar' ? 'is-hot' : ''} ${highlight?.kind === 'prediction' && event.kind === 'drift' ? 'is-hot' : ''}`}
          >
            <button type="button" className="timeline-dot" aria-describedby={`${event.id}-tip`}>
              <span className="timeline-label">{event.title}</span>
            </button>
            <div className="timeline-tip" id={`${event.id}-tip`} role="tooltip">
              <strong>{event.title}</strong>
              {event.time && <span>{event.time}</span>}
              <span>{event.detail}</span>
            </div>
          </div>
        ))}
      </div>
      {Number.isFinite(vessel?.ais_gap_min) && (
        <p className="timeline-caption">AIS blackout highlighted: {vessel.ais_gap_min} min. Event times are shown only when present in the result.</p>
      )}
    </section>
  )
}

function MetricBar({ label, value, tone, active }) {
  const pct = Number.isFinite(value) ? Math.max(0, Math.min(100, value * 100)) : null
  return (
    <div className={`metric-bar ${active ? 'is-hot' : ''}`}>
      <div className="metric-bar-head">
        <span>{label}</span>
        <strong>{pct == null ? '—' : `${pct.toFixed(1)}%`}</strong>
      </div>
      <div className="metric-bar-track" aria-hidden="true">
        <div className={`metric-bar-fill tone-${tone}`} style={{ width: pct == null ? '0%' : `${pct}%` }} />
      </div>
    </div>
  )
}

function DetailCard({ id, title, open, children }) {
  const [userOpen, setUserOpen] = useState(Boolean(open))
  const expanded = userOpen || Boolean(open)
  return (
    <details className="detail-card" open={expanded} onToggle={(event) => setUserOpen(event.currentTarget.open)}>
      <summary>{title}</summary>
      <div className="detail-body" id={id}>{children}</div>
    </details>
  )
}
