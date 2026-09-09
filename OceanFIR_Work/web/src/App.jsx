import { useState } from 'react'
import MapView from './components/MapView'

export default function App() {
  const [selectedMmsi, setSelectedMmsi] = useState(null)

  return (
    <main className="app-shell">
      <header className="app-header">
        <div>
          <p className="eyebrow">MARITIME INTELLIGENCE</p>
          <h1>OCEAN<span>FIR</span></h1>
        </div>
        <p>Sentinel-1 scene analysis and vessel attribution</p>
      </header>
      <MapView selectedMmsi={selectedMmsi} onSelect={setSelectedMmsi} />
    </main>
  )
}
