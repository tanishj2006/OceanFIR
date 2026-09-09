import './VesselAttribution.css'
export default function VesselTable({ vessels = [], onSelect, selectedMmsi = null }) {
  const rankedVessels = [...vessels].sort(
    (a, b) => (b.score ?? 0) - (a.score ?? 0)
  )

  const formatNumber = (value, digits = 1) => {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
      return '—'
    }

    return Number(value).toFixed(digits)
  }

  const formatInteger = (value) => {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
      return '—'
    }

    return Number(value).toLocaleString()
  }

  const verdictLabel = (verdict) => {
    if (!verdict) return 'unknown'
    return verdict
  }

  if (!vessels.length) {
    return (
      <section className="vessel-table-panel">
        <div className="vessel-table-header">
          <div>
            <p className="vessel-table-eyebrow">VESSEL ATTRIBUTION</p>
            <h2>Ranked Vessels</h2>
          </div>
          <span className="vessel-count">0 vessels</span>
        </div>

        <div className="vessel-empty">
          No vessel attribution records available.
        </div>
      </section>
    )
  }

  return (
    <section className="vessel-table-panel">
      <div className="vessel-table-header">
        <div>
          <p className="vessel-table-eyebrow">VESSEL ATTRIBUTION</p>
          <h2>Ranked Vessels</h2>
        </div>

        <span className="vessel-count">
          {formatInteger(rankedVessels.length)} vessels
        </span>
      </div>

      <div className="vessel-table-scroll">
        <table className="vessel-table">
          <thead>
            <tr>
              <th scope="col">Vessel</th>
              <th scope="col">Type</th>
              <th scope="col">Length</th>
              <th scope="col">Distance</th>
              <th scope="col">AIS gap</th>
              <th scope="col">Score</th>
              <th scope="col">Verdict</th>
            </tr>
          </thead>

          <tbody>
            {rankedVessels.map((vessel) => {
              const isSelected = vessel.mmsi === selectedMmsi

              return (
                <tr
                  key={vessel.mmsi}
                  className={isSelected ? 'vessel-row selected' : 'vessel-row'}
                  onClick={() => onSelect?.(vessel.mmsi)}
                  tabIndex={0}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      onSelect?.(vessel.mmsi)
                    }
                  }}
                >
                  <td className="vessel-name-cell">
                    {vessel.dark && (
                      <span
                        className="dark-contact-dot"
                        title="radar contact, no AIS"
                        aria-label="radar contact, no AIS"
                      />
                    )}

                    <span>{vessel.name || 'Unknown vessel'}</span>
                  </td>

                  <td>{vessel.type || '—'}</td>

                  <td className="numeric-cell">
                    {formatInteger(vessel.len_m)} m
                  </td>

                  <td className="numeric-cell">
                    {formatNumber(vessel.dist_km)} km
                  </td>

                  <td className="numeric-cell">
                    {formatInteger(vessel.ais_gap_min)} min
                  </td>

                  <td className="numeric-cell score-cell">
                    {formatNumber(vessel.score, 2)}
                  </td>

                  <td>
                    <span
                      className={`verdict-pill verdict-${vessel.verdict || 'unknown'}`}
                    >
                      {verdictLabel(vessel.verdict)}
                    </span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}