import { useEffect, useState } from 'react'
import { api, type Stats } from '../api'
import TrendChart from '../components/TrendChart'

const pct = (rate: number | null) => (rate === null ? '—' : `${(rate * 100).toFixed(1)}%`)

export default function StatsPage() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.stats().then(setStats, (e: Error) => setError(e.message))
  }, [])

  if (error) return <p className="error">{error}</p>
  if (!stats) return <p className="muted">Loading…</p>
  if (stats.games_played === 0) {
    return <p className="secondary">No verified games yet. Review or add games to see stats.</p>
  }

  return (
    <div className="stack">
      <div className="tiles">
        <div className="card tile hero">
          <div className="label">Average</div>
          <div className="value">{stats.average?.toFixed(1)}</div>
          <div className="sub">over {stats.games_played} games</div>
        </div>
        <div className="card tile">
          <div className="label">High game</div>
          <div className="value">{stats.high}</div>
        </div>
        <div className="card tile">
          <div className="label">Low game</div>
          <div className="value">{stats.low}</div>
        </div>
        <div className="card tile">
          <div className="label">Strike rate</div>
          <div className="value">{pct(stats.strike_rate)}</div>
          <div className="sub">
            {stats.strikes} of {stats.strike_chances} full racks
          </div>
        </div>
        <div className="card tile">
          <div className="label">Spare conversion</div>
          <div className="value">{pct(stats.spare_rate)}</div>
          <div className="sub">
            {stats.spares} of {stats.spare_chances} chances
          </div>
        </div>
        <div className="card tile">
          <div className="label">Open frames</div>
          <div className="value">{pct(stats.open_rate)}</div>
          <div className="sub">
            {stats.open_frames} of {stats.frames} frames
          </div>
        </div>
      </div>

      <div className="card">
        <h2>Scores over time</h2>
        <TrendChart trend={stats.trend} />
        <details>
          <summary className="secondary">Show as a table</summary>
          <div className="scroll-x" style={{ maxHeight: '24rem', overflowY: 'auto' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Game</th>
                  <th>Date</th>
                  <th>Score</th>
                  <th>10-game average</th>
                </tr>
              </thead>
              <tbody>
                {stats.trend.map((point, i) => (
                  <tr key={point.game_id}>
                    <td>{i + 1}</td>
                    <td>{point.played_on ?? '—'}</td>
                    <td>{point.total}</td>
                    <td>{point.rolling_average.toFixed(1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </div>
    </div>
  )
}
