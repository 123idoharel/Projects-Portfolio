import { useState } from 'react'
import { useParking } from './hooks/useParking.js'
import DriverView from './views/DriverView.jsx'
import OperatorView from './views/OperatorView.jsx'

const TABS = [
  { id: 'driver',   label: '👤 נהג' },
  { id: 'operator', label: '🖥️ מפעיל' },
]

function TabBar({ active, onChange }) {
  return (
    <div style={{
      display: 'flex',
      background: 'rgba(255,255,255,0.05)',
      borderBottom: '1px solid rgba(255,255,255,0.08)',
      padding: '0 12px',
      gap: 4,
      flexShrink: 0,
    }}>
      {TABS.map(t => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          style={{
            background: active === t.id ? 'rgba(33,150,243,0.15)' : 'transparent',
            color: active === t.id ? '#2196F3' : 'rgba(255,255,255,0.45)',
            border: 'none',
            borderBottom: active === t.id ? '2px solid #2196F3' : '2px solid transparent',
            padding: '12px 18px',
            fontFamily: 'Rubik,sans-serif',
            fontSize: 14,
            fontWeight: active === t.id ? 700 : 500,
            cursor: 'pointer',
            transition: 'all 0.15s',
          }}
        >
          {t.label}
        </button>
      ))}
      <div style={{ flex: 1 }} />
      <div style={{
        display: 'flex', alignItems: 'center',
        fontSize: 13, color: 'rgba(255,255,255,0.3)',
        gap: 6, padding: '0 8px',
      }}>
        🅿️ <span style={{ fontWeight: 700, color: 'rgba(255,255,255,0.6)' }}>Smart Parking</span>
      </div>
    </div>
  )
}

function LoadingScreen() {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center',
      height: '100%', gap: 16,
    }}>
      <div style={{ fontSize: 48 }}>🅿️</div>
      <div style={{ fontSize: 18, color: 'rgba(255,255,255,0.6)', fontWeight: 600 }}>
        טוען מערכת חנייה...
      </div>
      <div style={{
        width: 200, height: 4, background: 'rgba(255,255,255,0.1)',
        borderRadius: 2, overflow: 'hidden',
      }}>
        <div style={{
          height: '100%',
          background: 'linear-gradient(90deg, #2196F3, #E45B73)',
          borderRadius: 2,
          animation: 'loading 1.5s ease-in-out infinite',
        }} />
      </div>
      <style>{`
        @keyframes loading {
          0%   { width: 0%; margin-left: 0%; }
          50%  { width: 60%; margin-left: 20%; }
          100% { width: 0%; margin-left: 100%; }
        }
      `}</style>
    </div>
  )
}

function ErrorScreen({ error }) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center',
      height: '100%', gap: 16, direction: 'rtl',
    }}>
      <div style={{ fontSize: 48 }}>⚠️</div>
      <div style={{ fontSize: 18, color: '#f44336', fontWeight: 700 }}>שגיאת חיבור לשרת</div>
      <div style={{ fontSize: 14, color: 'rgba(255,255,255,0.5)', maxWidth: 300, textAlign: 'center' }}>
        {error}
      </div>
      <div style={{ fontSize: 13, color: 'rgba(255,255,255,0.3)', maxWidth: 350, textAlign: 'center' }}>
        ודא שהשרת רץ: <code style={{ color: '#90CAF9' }}>python -m uvicorn server:app --reload</code>
      </div>
      <button onClick={() => location.reload()} style={{
        background: '#2196F3', color: '#fff', border: 'none',
        borderRadius: 8, padding: '10px 24px', fontSize: 14,
        cursor: 'pointer', fontFamily: 'Rubik,sans-serif', fontWeight: 600,
      }}>🔄 נסה שוב</button>
    </div>
  )
}

export default function App() {
  const [mode, setMode] = useState('driver')

  const parking = useParking()

  if (parking.loading) return (
    <div style={{ height: '100vh' }}><LoadingScreen /></div>
  )

  if (parking.error) return (
    <div style={{ height: '100vh' }}><ErrorScreen error={parking.error} /></div>
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100dvh', minHeight: '100dvh', overflow: 'hidden' }}>
      <TabBar active={mode} onChange={setMode} />
      <div style={{ flex: 1, overflow: 'hidden' }}>
        {mode === 'driver' ? (
          <DriverView
            layout={parking.layout}
            spots={parking.spots}
            vehicles={parking.vehicles}
            assignUser={parking.assignUser}
            resetSim={parking.resetSim}
          />
        ) : (
          <OperatorView
            layout={parking.layout}
            spots={parking.spots}
            vehicles={parking.vehicles}
            stats={parking.stats}
            eventLog={parking.eventLog}
            scenarioName={parking.scenarioName}
            speed={parking.speed}
            loadLayout={parking.loadLayout}
            spawnVehicle={parking.spawnVehicle}
            stealSpot={parking.stealSpot}
            freeSpot={parking.freeSpot}
            removeVehicle={parking.removeVehicle}
            resetSim={parking.resetSim}
            setSpeed={parking.setSpeed}
          />
        )}
      </div>
    </div>
  )
}
