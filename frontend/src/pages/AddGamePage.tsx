import { useEffect, useState } from 'react'
import { api, type Game, type GameDetail } from '../api'
import FrameGrid from '../components/FrameGrid'
import { rollsToSlots, slotsToRolls } from '../frames'

/** Enter a game by hand. Skipped photos (several of your names on one board) are shown
 * here so they're easy to copy from. */
export default function AddGamePage({ onGamesChanged }: { onGamesChanged: () => void }) {
  const [skipped, setSkipped] = useState<Game[]>([])
  const [slots, setSlots] = useState(rollsToSlots(null))
  const [playedOn, setPlayedOn] = useState('')
  const [added, setAdded] = useState<GameDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.games('skipped').then(setSkipped, (e: Error) => setError(e.message))
  }, [])

  async function add() {
    setBusy(true)
    setError(null)
    try {
      const game = await api.addManual(playedOn, slotsToRolls(slots))
      setAdded(game)
      setSlots(rollsToSlots(null))
      onGamesChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="stack">
      <div className="card stack">
        <h1>Add a game by hand</h1>
        <p className="secondary" style={{ margin: 0 }}>
          Type X for a strike, / for a spare, - for a miss, or the number of pins. Hand-entered
          games count towards your stats right away.
        </p>
        <label className="row">
          Date played
          <input type="date" value={playedOn} onChange={(e) => setPlayedOn(e.target.value)} />
        </label>
        <FrameGrid slots={slots} onSlotsChange={setSlots} scores={null} hideScores />
        <div className="row">
          <button className="primary" disabled={busy || playedOn === ''} onClick={add}>
            {busy ? 'Adding…' : 'Add game'}
          </button>
          {error && <span className="error">{error}</span>}
          {added && !error && (
            <span className="secondary">
              Added: {added.total} on {added.played_on}.
            </span>
          )}
        </div>
      </div>

      {skipped.length > 0 && (
        <div className="card">
          <h2>Skipped photos to enter by hand</h2>
          <div className="thumbs">
            {skipped.map((game) => (
              <figure key={game.id} style={{ margin: 0 }}>
                {game.photo_id !== null && (
                  <a href={api.photoUrl(game.photo_id)} target="_blank" rel="noreferrer">
                    <img src={api.photoUrl(game.photo_id)} alt={`Skipped photo ${game.photo_name ?? ''}`} />
                  </a>
                )}
                <figcaption className="secondary" style={{ fontSize: '0.85rem' }}>
                  {game.photo_name} · {game.played_on ?? 'no date'}
                  <br />
                  <span className="muted">{game.review_reasons[0]}</span>
                </figcaption>
              </figure>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
