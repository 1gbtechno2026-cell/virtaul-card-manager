import { useEffect, useMemo, useState } from 'react'
import { API_BASE } from './apiBase'

const LINE_COLOR = '#6d28d9' // var(--primary) -- single series, title names it, no legend needed

function buildDailySeries(cards) {
  if (cards.length === 0) return []

  const counts = new Map()
  for (const card of cards) {
    if (!card.created_at) continue
    const day = card.created_at.slice(0, 10) // YYYY-MM-DD
    counts.set(day, (counts.get(day) || 0) + 1)
  }

  const days = [...counts.keys()].sort()
  if (days.length === 0) return []

  const start = new Date(days[0])
  const end = new Date(days[days.length - 1])
  const series = []
  for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
    const key = d.toISOString().slice(0, 10)
    series.push({ date: key, count: counts.get(key) || 0 })
  }
  return series
}

function LineChart({ data }) {
  const [hoverIndex, setHoverIndex] = useState(null)
  const width = 640
  const height = 220
  const padding = { top: 16, right: 16, bottom: 28, left: 36 }
  const innerW = width - padding.left - padding.right
  const innerH = height - padding.top - padding.bottom

  const maxCount = Math.max(1, ...data.map((d) => d.count))
  const yMax = Math.ceil(maxCount / 5) * 5 || 5

  const xFor = (i) =>
    padding.left + (data.length === 1 ? innerW / 2 : (i / (data.length - 1)) * innerW)
  const yFor = (v) => padding.top + innerH - (v / yMax) * innerH

  if (data.length === 0) {
    return <div className="chart-empty">No card creation history yet.</div>
  }

  const linePath = data.map((d, i) => `${i === 0 ? 'M' : 'L'} ${xFor(i)} ${yFor(d.count)}`).join(' ')
  const areaPath = `${linePath} L ${xFor(data.length - 1)} ${padding.top + innerH} L ${xFor(0)} ${
    padding.top + innerH
  } Z`

  const yTicks = [0, yMax / 2, yMax].map((v) => Math.round(v))
  const last = data[data.length - 1]

  const formatShortDate = (isoDate) => {
    const d = new Date(`${isoDate}T00:00:00`)
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  }

  const maxXTicks = 6
  const xTickIndices =
    data.length <= maxXTicks
      ? data.map((_, i) => i)
      : Array.from({ length: maxXTicks }, (_, i) =>
          Math.round((i * (data.length - 1)) / (maxXTicks - 1))
        )

  const handleMove = (e) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const x = ((e.clientX - rect.left) / rect.width) * width
    const idx = Math.round(((x - padding.left) / innerW) * (data.length - 1))
    setHoverIndex(Math.min(data.length - 1, Math.max(0, idx)))
  }

  const hovered = hoverIndex !== null ? data[hoverIndex] : null

  return (
    <div className="line-chart-wrap">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="line-chart-svg"
        onMouseMove={handleMove}
        onMouseLeave={() => setHoverIndex(null)}
      >
        {yTicks.map((t) => (
          <g key={t}>
            <line
              x1={padding.left}
              x2={width - padding.right}
              y1={yFor(t)}
              y2={yFor(t)}
              className="chart-gridline"
            />
            <text x={padding.left - 8} y={yFor(t) + 4} className="chart-axis-label" textAnchor="end">
              {t}
            </text>
          </g>
        ))}

        {xTickIndices.map((i) => (
          <text
            key={i}
            x={xFor(i)}
            y={height - 8}
            className="chart-axis-label"
            textAnchor="middle"
          >
            {formatShortDate(data[i].date)}
          </text>
        ))}

        {data.length > 1 && <path d={areaPath} fill={LINE_COLOR} opacity="0.1" stroke="none" />}
        <path
          d={linePath}
          fill="none"
          stroke={LINE_COLOR}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        <circle cx={xFor(data.length - 1)} cy={yFor(last.count)} r="5" fill={LINE_COLOR} className="chart-end-dot" />
        <text x={xFor(data.length - 1)} y={yFor(last.count) - 12} textAnchor="end" className="chart-end-label">
          {last.count}
        </text>

        {hovered && (
          <>
            <line
              x1={xFor(hoverIndex)}
              x2={xFor(hoverIndex)}
              y1={padding.top}
              y2={padding.top + innerH}
              className="chart-crosshair"
            />
            <circle cx={xFor(hoverIndex)} cy={yFor(hovered.count)} r="5" fill={LINE_COLOR} className="chart-end-dot" />
          </>
        )}
      </svg>

      {hovered && (
        <div className="chart-tooltip" style={{ left: `${(xFor(hoverIndex) / width) * 100}%` }}>
          <div className="chart-tooltip-value">{hovered.count}</div>
          <div className="chart-tooltip-label">{hovered.date}</div>
        </div>
      )}
    </div>
  )
}

function AnalyticsPage({ token, onAuthExpired }) {
  const [cards, setCards] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [mongoConfigured, setMongoConfigured] = useState(true)
  const [showTable, setShowTable] = useState(false)

  const authHeaders = { Authorization: `Bearer ${token}` }

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      setError('')
      try {
        const res = await fetch(`${API_BASE}/api/cards`, { headers: authHeaders })
        if (res.status === 401) {
          onAuthExpired()
          return
        }
        const body = await res.json()
        if (!res.ok) {
          setMongoConfigured(false)
          setError(body.error || 'Could not load cards.')
          return
        }
        setMongoConfigured(true)
        setCards(body.cards)
      } catch {
        setError('Could not reach the backend.')
      } finally {
        setLoading(false)
      }
    }
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const series = useMemo(() => buildDailySeries(cards), [cards])

  return (
    <div className="page">
      <header className="hero">
        <div className="hero-icon">📊</div>
        <div className="hero-text">
          <h1>Dashboard</h1>
          <p className="hint">An overview of every virtual card you've created.</p>
        </div>
      </header>

      {!mongoConfigured && (
        <div className="notice">
          MongoDB is not configured on the backend (set <code>MONGODB_URI</code> in{' '}
          <code>backend/.env</code>) -- the dashboard needs it to show history.
        </div>
      )}
      {error && mongoConfigured && <div className="error">{error}</div>}

      <div className="stat-tile">
        <div className="stat-tile-label">Total cards created</div>
        <div className="stat-tile-value">{loading ? '—' : cards.length}</div>
      </div>

      <div className="panel">
        <div className="panel-title-row">
          <h2 className="panel-title">Cards created over time</h2>
          <button
            type="button"
            className="secondary-btn small-btn"
            onClick={() => setShowTable((v) => !v)}
          >
            {showTable ? 'View chart' : 'View as table'}
          </button>
        </div>

        {loading ? (
          <div className="chart-empty">Loading...</div>
        ) : showTable ? (
          <div className="table-wrap">
            <table className="cards-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Cards Created</th>
                </tr>
              </thead>
              <tbody>
                {series.map((d) => (
                  <tr key={d.date}>
                    <td>{d.date}</td>
                    <td>{d.count}</td>
                  </tr>
                ))}
                {series.length === 0 && (
                  <tr>
                    <td colSpan={2} className="table-empty">
                      No data yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        ) : (
          <LineChart data={series} />
        )}
      </div>
    </div>
  )
}

export default AnalyticsPage
