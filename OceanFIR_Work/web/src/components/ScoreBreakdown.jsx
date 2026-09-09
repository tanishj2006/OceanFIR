import './VesselAttribution.css'
export default function ScoreBreakdown({ vessel, threshold = 0.45 }) {
  if (!vessel) {
    return (
      <section className="score-panel">
        <div className="score-header">
          <div>
            <p className="score-eyebrow">FORENSIC SCORE</p>
            <h2>Score Breakdown</h2>
          </div>
        </div>

        <div className="score-empty">
          Select a vessel to inspect its attribution score.
        </div>
      </section>
    )
  }

  const factors = [
    { key: 'proximity', label: 'Proximity', weight: 0.30 },
    { key: 'parity', label: 'Parity', weight: 0.10 },
    { key: 'temporality', label: 'Temporality', weight: 0.18 },
    { key: 'silence', label: 'Silence', weight: 0.42 },
  ]

  const formatScore = (value) =>
    value === null || value === undefined
      ? '—'
      : Number(value).toFixed(2)

  const total = factors.reduce(
    (sum, factor) =>
      sum + (Number(vessel[factor.key]) || 0) * factor.weight,
    0
  )

  return (
    <section className="score-panel">
      <div className="score-header">
        <div>
          <p className="score-eyebrow">FORENSIC SCORE</p>
          <h2>Score Breakdown</h2>
        </div>

        <div className="score-total">
          <strong>{formatScore(total)}</strong>
          <span> / {formatScore(threshold)}</span>
        </div>
      </div>

      <div className="score-factors">
        {factors.map((factor) => {
          const raw = Number(vessel[factor.key]) || 0
          const contribution = raw * factor.weight

          return (
            <div
              className={`score-factor ${
                factor.key === 'silence' ? 'score-factor-silence' : ''
              }`}
              key={factor.key}
            >
              <div className="score-factor-top">
                <span>{factor.label}</span>
                <span className="score-weight">
                  Weight {factor.weight.toFixed(2)}
                </span>
              </div>

              <div className="score-bar-track">
                <div
                  className="score-bar-fill"
                  style={{ width: `${Math.max(0, Math.min(100, raw * 100))}%` }}
                />
              </div>

              <div className="score-factor-values">
                <span>Raw {formatScore(raw)}</span>
                <span>Contribution +{formatScore(contribution)}</span>
              </div>
            </div>
          )
        })}
      </div>

      <div className="score-summary">
        <span>Computed score</span>
        <strong>{formatScore(total)}</strong>
      </div>
    </section>
  )
}