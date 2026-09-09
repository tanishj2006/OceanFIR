import './VesselAttribution.css'
export default function ExonerationRecord({ vessels = [] }) {
  const clearedVessels = vessels.filter(
    (vessel) => vessel.verdict === 'cleared'
  )

  return (
    <section className="exoneration-panel">
      <div className="exoneration-header">
        <div>
          <p className="exoneration-eyebrow">AUDIT TRAIL</p>
          <h2>Exoneration Record</h2>
        </div>

        <span className="exoneration-count">
          {clearedVessels.length.toLocaleString()} vessels cleared
        </span>
      </div>

      {clearedVessels.length === 0 ? (
        <div className="exoneration-empty">
          No cleared vessels in the current result.
        </div>
      ) : (
        <div className="exoneration-list">
          {clearedVessels.map((vessel) => (
            <article className="exoneration-item" key={vessel.mmsi}>
              <div className="exoneration-vessel">
                <strong>{vessel.name || 'Unknown vessel'}</strong>

                <span className="exoneration-mmsi">
                  MMSI {vessel.mmsi}
                </span>
              </div>

              <p>
                {vessel.reason || 'No clearance reason provided.'}
              </p>
            </article>
          ))}
        </div>
      )}
    </section>
  )
}