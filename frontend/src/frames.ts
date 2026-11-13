// Converting between the backend's rolls and the editable scoreboard boxes.
// Only notation lives here; scoring stays on the backend (backend/app/scoring.py).

import type { Rolls } from './api'

export const FRAMES = 10
export type Slots = string[][] // 10 frames; 2 boxes each, 3 in frame 10; "" = blank

/** Normalize one typed character to notation, or return null to reject it. */
export function cleanMark(typed: string): string | null {
  const c = typed.trim()
  if (c === '') return ''
  if (c === 'x' || c === 'X') return 'X'
  if (c === '/') return '/'
  if (['-', '0', 'g', 'G', '.', '·'].includes(c)) return '-'
  if (/^[1-9]$/.test(c)) return c
  return null
}

export function rollsToSlots(rolls: Rolls | null): Slots {
  return Array.from({ length: FRAMES }, (_, i) => {
    const frame = rolls?.[i] ?? []
    const size = i === FRAMES - 1 ? 3 : 2
    return Array.from({ length: size }, (_, b) => frame[b] ?? '')
  })
}

/** Blank boxes become null (unreadable). A strike in frames 1-9 has no second ball, and
 * frame 10 gets its third ball only when earned. */
export function slotsToRolls(slots: Slots): Rolls {
  const roll = (s: string) => (s === '' ? null : s)
  return slots.map((boxes, i) => {
    if (i < FRAMES - 1) {
      return boxes[0] === 'X' ? ['X'] : [roll(boxes[0]), roll(boxes[1])]
    }
    const earned = boxes[0] === 'X' || boxes[1] === 'X' || boxes[1] === '/'
    const balls = earned ? boxes : boxes.slice(0, 2)
    return balls.map(roll)
  })
}

export function isBlank(slots: Slots): boolean {
  return slots.every((boxes) => boxes.every((b) => b === ''))
}
