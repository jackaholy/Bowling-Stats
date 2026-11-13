import { useEffect, useState } from 'react'
import { api, type GameDetail, type GameEdit } from '../api'
import { FRAMES, rollsToSlots, slotsToRolls, type Slots } from '../frames'
import FrameGrid from './FrameGrid'
import StatusChip from './StatusChip'

interface Props {
  gameId: number
  /** Called with the updated game after every change, so lists can refresh. */
  onChanged: (game: GameDetail) => void
  onDeleted: (gameId: number) => void
}

interface Draft {
  slots: Slots
  printed: string[]
  printedTotal: string
  playedOn: string
}

const toText = (n: number | null | undefined) => (n === null || n === undefined ? '' : String(n))
const toNumber = (s: string) => (s === '' ? null : Number(s))

function draftOf(game: GameDetail): Draft {
  return {
    slots: rollsToSlots(game.frames),
    printed: Array.from({ length: FRAMES }, (_, i) => toText(game.printed_cumulative?.[i])),
    printedTotal: toText(game.printed_total),
    playedOn: game.played_on ?? '',
  }
}

export default function GameEditor({ gameId, onChanged, onDeleted }: Props) {
  const [game, setGame] = useState<GameDetail | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [saveAlias, setSaveAlias] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let current = true
    setGame(null)
    setError(null)
    api.game(gameId).then(
      (loaded) => {
        if (!current) return
        setGame(loaded)
        setDraft(draftOf(loaded))
      },
      (e: Error) => current && setError(e.message),
    )
    return () => {
      current = false
    }
  }, [gameId])

  if (error && !game) return <p className="error">{error}</p>
  if (!game || !draft) return <p className="muted">Loading…</p>

  const saved = draftOf(game)
  const rollsChanged = JSON.stringify(draft.slots) !== JSON.stringify(saved.slots)
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved)
  const isManual = game.status === 'manual'
  const canRetry = game.photo_id !== null && !['verified', 'manual'].includes(game.status)

  async function run(label: string, action: () => Promise<GameDetail | void>) {
    setBusy(label)
    setError(null)
    try {
      const result = await action()
      if (result) {
        setGame(result)
        setDraft(draftOf(result))
        onChanged(result)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  function save() {
    if (!game || !draft) return
    const edit: GameEdit = {}
    if (rollsChanged) edit.frames = slotsToRolls(draft.slots)
    if (draft.playedOn !== saved.playedOn) edit.played_on = draft.playedOn || null
    if (!isManual && game.frames !== null) {
      if (JSON.stringify(draft.printed) !== JSON.stringify(saved.printed)) {
        edit.printed_cumulative = draft.printed.map(toNumber)
      }
      if (draft.printedTotal !== saved.printedTotal) edit.printed_total = toNumber(draft.printedTotal)
    }
    void run('save', () => api.editGame(game.id, edit))
  }

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <div className="row">
          <h2 style={{ margin: 0 }}>
            {game.total ?? <span className="secondary">No score yet</span>}
            <span className="secondary" style={{ fontWeight: 400 }}>
              {' '}
              · {game.played_on ?? 'no date'}
              {game.name_on_board ? ` · ${game.name_on_board}` : ''}
            </span>
          </h2>
          <StatusChip status={game.status} />
        </div>
        <span className="muted">{game.photo_name ?? 'Entered by hand'}</span>
      </div>

      {game.review_reasons.length > 0 && game.status !== 'verified' && (
        <ul className="reasons" aria-label="Why this game needs attention">
          {game.review_reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
      {error && <p className="error">{error}</p>}

      <div className="editor-top">
        {game.photo_id !== null && (
          <a className="photo" href={api.photoUrl(game.photo_id)} target="_blank" rel="noreferrer">
            <img src={api.photoUrl(game.photo_id)} alt={`Scoreboard photo ${game.photo_name ?? ''}`} />
          </a>
        )}
        <div className="stack">
          {game.rows.length > 0 && (
            <div className="card">
              <h3>Rows on the board</h3>
              <table className="board-rows">
                <tbody>
                  {game.rows.map((row) => {
                    const mine = row.name === game.name_on_board && game.frames !== null
                    return (
                      <tr key={row.index} className={mine ? 'mine' : undefined}>
                        <td>{row.name || <span className="muted">(no name)</span>}</td>
                        <td className="secondary">{row.final_total ?? '?'}</td>
                        <td className="muted">{row.matches_alias ? 'your name' : ''}</td>
                        <td style={{ textAlign: 'right' }}>
                          <button
                            disabled={busy !== null}
                            onClick={() =>
                              run('pick', () =>
                                api.pickRow(game.id, row.index, saveAlias && !row.matches_alias),
                              )
                            }
                          >
                            {mine ? 'Confirm: this is me' : 'This is me'}
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              <label className="row" style={{ marginTop: '0.5rem' }}>
                <input
                  type="checkbox"
                  checked={saveAlias}
                  onChange={(e) => setSaveAlias(e.target.checked)}
                />
                Remember a new name as one of mine
              </label>
              {game.notes && <p className="muted">Claude noted: {game.notes}</p>}
            </div>
          )}

          <label className="row">
            Date played
            <input
              type="date"
              value={draft.playedOn}
              onChange={(e) => setDraft({ ...draft, playedOn: e.target.value })}
            />
          </label>
        </div>
      </div>

      {game.frames === null && !isManual ? (
        <p className="secondary">Pick your row above to see and fix its rolls.</p>
      ) : (
        <FrameGrid
          slots={draft.slots}
          onSlotsChange={(slots) => setDraft({ ...draft, slots })}
          scores={game.scores}
          stale={rollsChanged}
          printed={isManual ? undefined : draft.printed}
          printedTotal={draft.printedTotal}
          onPrintedChange={(printed, printedTotal) => setDraft({ ...draft, printed, printedTotal })}
          missing={game.missing_rolls}
          marks={game.marks}
        />
      )}
      {game.missing_rolls.length > 0 && (
        <p className="secondary">
          Highlighted boxes couldn't be read from the photo. Fill them in if you know them.
        </p>
      )}

      <div className="row">
        <button className="primary" disabled={!dirty || busy !== null} onClick={save}>
          {busy === 'save' ? 'Saving…' : 'Save and re-check'}
        </button>
        {dirty && (
          <button disabled={busy !== null} onClick={() => setDraft(saved)}>
            Undo changes
          </button>
        )}
        {game.photo_id !== null &&
          (game.status === 'skipped' ? (
            <button disabled={busy !== null} onClick={() => run('unskip', () => api.unskip(game.id))}>
              Unskip
            </button>
          ) : (
            <button disabled={busy !== null} onClick={() => run('skip', () => api.skip(game.id))}>
              Skip this game
            </button>
          ))}
        {canRetry && (
          <button
            disabled={busy !== null}
            title="Calls Claude again; costs about $0.05"
            onClick={() => run('retry', () => api.retry(game.id))}
          >
            {busy === 'retry' ? 'Reading…' : 'Read photo again (~$0.05)'}
          </button>
        )}
        {isManual && (
          <button
            className="danger"
            disabled={busy !== null}
            onClick={() => {
              if (window.confirm('Delete this hand-entered game?')) {
                void run('delete', async () => {
                  await api.deleteGame(game.id)
                  onDeleted(game.id)
                })
              }
            }}
          >
            Delete
          </button>
        )}
      </div>
    </div>
  )
}
