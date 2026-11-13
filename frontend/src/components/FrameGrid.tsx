import type { Mark } from '../api'
import { cleanMark, FRAMES, type Slots } from '../frames'

interface Props {
  slots: Slots
  onSlotsChange?: (slots: Slots) => void
  /** Running totals computed by the backend from the saved rolls. */
  scores: (number | null)[] | null
  /** True when the rolls were edited since the scores were computed. */
  stale?: boolean
  /** The board's printed running totals plus final total (photo games only). */
  printed?: string[]
  printedTotal?: string
  onPrintedChange?: (printed: string[], printedTotal: string) => void
  missing?: [number, number][]
  marks?: Mark[]
  /** Hide the computed-score row (hand entry: nothing is computed until the game is saved). */
  hideScores?: boolean
}

const frameNumbers = Array.from({ length: FRAMES }, (_, i) => i)

/** One scoreboard row. Typing X, /, -, or a digit fills a box and moves to the next. */
export default function FrameGrid({
  slots,
  onSlotsChange,
  scores,
  stale = false,
  printed,
  printedTotal = '',
  onPrintedChange,
  missing = [],
  marks = [],
  hideScores = false,
}: Props) {
  const isMissing = (f: number, b: number) => missing.some(([mf, mb]) => mf === f && mb === b)
  const hasMark = (f: number, b: number, kind: Mark['kind']) =>
    marks.some((m) => m.frame === f && m.ball === b && m.kind === kind)
  const total = scores?.[FRAMES - 1] ?? null

  function setBox(frame: number, ball: number, typed: string, input: HTMLInputElement) {
    const mark = cleanMark(typed.slice(-1))
    if (mark === null || !onSlotsChange) return
    const next = slots.map((boxes) => [...boxes])
    next[frame][ball] = mark
    if (frame < FRAMES - 1 && ball === 0 && mark === 'X') next[frame][1] = ''
    onSlotsChange(next)
    if (mark !== '') {
      const boxes = Array.from(
        input.closest('table')?.querySelectorAll<HTMLInputElement>('input.ball') ?? [],
      )
      const after = boxes.slice(boxes.indexOf(input) + 1).find((box) => !box.disabled)
      after?.focus()
      after?.select()
    }
  }

  function setPrinted(index: number, value: string) {
    if (!printed || !onPrintedChange || !/^\d{0,3}$/.test(value)) return
    if (index === FRAMES) {
      onPrintedChange(printed, value)
    } else {
      const next = [...printed]
      next[index] = value
      onPrintedChange(next, printedTotal)
    }
  }

  const printedAt = (i: number) => (i === FRAMES ? printedTotal : (printed?.[i] ?? ''))
  const scoreAt = (i: number) => (i === FRAMES ? total : (scores?.[i] ?? null))
  const mismatch = (i: number) => {
    const board = printedAt(i)
    const computed = scoreAt(i)
    return !stale && board !== '' && computed !== null && Number(board) !== computed
  }

  return (
    <div className="scroll-x">
      <table className="frame-grid">
        <thead>
          <tr>
            <th className="rowhead" scope="col">
              Frame
            </th>
            {frameNumbers.map((i) => (
              <th key={i} scope="col">
                {i + 1}
              </th>
            ))}
            <th scope="col">Total</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <th className="rowhead" scope="row">
              Rolls
            </th>
            {slots.map((boxes, f) => (
              <td key={f}>
                <div className="balls">
                  {boxes.map((value, b) => {
                    const strikeFrame = f < FRAMES - 1 && b === 1 && boxes[0] === 'X'
                    const classes = ['ball']
                    if (value === '' && isMissing(f, b)) classes.push('blank-unreadable')
                    if (hasMark(f, b, 'split')) classes.push('split')
                    const notes = [
                      hasMark(f, b, 'foul') ? 'foul' : '',
                      hasMark(f, b, 'split') ? 'split' : '',
                      value === '' && isMissing(f, b) ? 'unreadable' : '',
                    ].filter(Boolean)
                    return (
                      <input
                        key={b}
                        className={classes.join(' ')}
                        value={value}
                        disabled={!onSlotsChange || strikeFrame}
                        aria-label={`Frame ${f + 1} ball ${b + 1}${notes.length ? ` (${notes.join(', ')})` : ''}`}
                        title={notes.join(', ') || undefined}
                        onChange={(e) => setBox(f, b, e.target.value, e.target)}
                        onFocus={(e) => e.target.select()}
                      />
                    )
                  })}
                </div>
              </td>
            ))}
            <td />
          </tr>
          <tr hidden={hideScores}>
            <th className="rowhead" scope="row">
              Score from rolls
            </th>
            {[...frameNumbers, FRAMES].map((i) => {
              const value = scoreAt(i)
              const cls = stale ? 'stale' : mismatch(i) ? 'mismatch' : undefined
              return (
                <td key={i} className={cls} title={mismatch(i) ? "Doesn't match the board" : undefined}>
                  {stale ? '…' : value === null ? '?' : value}
                  {mismatch(i) && <span aria-label="doesn't match the board"> ≠</span>}
                </td>
              )
            })}
          </tr>
          {printed && (
            <tr>
              <th className="rowhead" scope="row">
                Board shows
              </th>
              {[...frameNumbers, FRAMES].map((i) => (
                <td key={i}>
                  <input
                    className="printed"
                    inputMode="numeric"
                    value={printedAt(i)}
                    disabled={!onPrintedChange}
                    aria-label={i === FRAMES ? 'Final total on the board' : `Board total after frame ${i + 1}`}
                    onChange={(e) => setPrinted(i, e.target.value)}
                  />
                </td>
              ))}
            </tr>
          )}
        </tbody>
      </table>
      {stale && <p className="muted">Save to recompute the scores and re-check against the board.</p>}
    </div>
  )
}
