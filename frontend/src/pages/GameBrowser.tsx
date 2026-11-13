import { useCallback, useEffect, useState } from 'react'
import { api, STATUS_LABEL, type Game, type GameDetail, type GameStatus } from '../api'
import GameEditor from '../components/GameEditor'
import StatusChip from '../components/StatusChip'

interface Props {
  /** Review mode: only games that need attention, and move on once one is resolved. */
  review: boolean
  onGamesChanged: () => void
}

const REVIEW: GameStatus[] = ['needs_review', 'pending']
const FILTERS: (GameStatus | 'all')[] = ['all', 'verified', 'manual', 'needs_review', 'pending', 'skipped']

export default function GameBrowser({ review, onGamesChanged }: Props) {
  const [games, setGames] = useState<Game[] | null>(null)
  const [filter, setFilter] = useState<GameStatus | 'all'>('all')
  const [selected, setSelected] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    api.games().then(setGames, (e: Error) => setError(e.message))
  }, [])
  useEffect(load, [load])

  const shown = (games ?? []).filter((game) =>
    review ? REVIEW.includes(game.status) : filter === 'all' || game.status === filter,
  )
  // Review newest first; the full list keeps play order.
  if (review) shown.reverse()

  useEffect(() => {
    if (selected === null && shown.length > 0) setSelected(shown[0].id)
  }, [selected, shown])

  function changed(game: GameDetail) {
    onGamesChanged()
    setGames((current) => current?.map((g) => (g.id === game.id ? game : g)) ?? null)
    if (review && !REVIEW.includes(game.status)) {
      // Resolved: move on to the next game in the queue.
      const index = shown.findIndex((g) => g.id === game.id)
      const next = shown[index + 1] ?? shown[index - 1]
      setSelected(next && next.id !== game.id ? next.id : null)
    }
  }

  function deleted(gameId: number) {
    onGamesChanged()
    setGames((current) => current?.filter((g) => g.id !== gameId) ?? null)
    setSelected(null)
  }

  if (error) return <p className="error">{error}</p>
  if (!games) return <p className="muted">Loading…</p>

  return (
    <div className="browser">
      <div className="card" style={{ padding: 0 }}>
        <div style={{ padding: '0.75rem 0.75rem 0.5rem' }}>
          {review ? (
            <h1>
              {shown.length} to review
            </h1>
          ) : (
            <label className="row">
              <h1 style={{ margin: 0 }}>Games</h1>
              <select value={filter} onChange={(e) => setFilter(e.target.value as GameStatus | 'all')}>
                {FILTERS.map((f) => (
                  <option key={f} value={f}>
                    {f === 'all' ? `All (${games.length})` : `${STATUS_LABEL[f]} (${games.filter((g) => g.status === f).length})`}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
        {shown.length === 0 ? (
          <p className="muted" style={{ padding: '0 0.75rem' }}>
            {review ? 'Nothing to review. Every game is verified, entered by hand, or skipped.' : 'No games.'}
          </p>
        ) : (
          <ul className="game-list">
            {shown.map((game) => (
              <li key={game.id}>
                <button aria-current={game.id === selected} onClick={() => setSelected(game.id)}>
                  <div className="line1">
                    <span>
                      <strong>{game.total ?? '—'}</strong>{' '}
                      <span className="secondary">{game.played_on ?? 'no date'}</span>
                    </span>
                    <StatusChip status={game.status} />
                  </div>
                  <div className="reason">
                    {game.status === 'verified' || game.status === 'manual'
                      ? (game.name_on_board ?? game.photo_name ?? '')
                      : (game.review_reasons[0] ?? game.photo_name ?? '')}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="card">
        {selected === null ? (
          <p className="muted">Select a game.</p>
        ) : (
          <GameEditor key={selected} gameId={selected} onChanged={changed} onDeleted={deleted} />
        )}
      </div>
    </div>
  )
}
