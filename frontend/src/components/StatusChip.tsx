import { STATUS_LABEL, type GameStatus } from '../api'

const ICON: Record<GameStatus, string> = {
  verified: '✓',
  manual: '✎',
  needs_review: '!',
  pending: '…',
  skipped: '–',
}

/** Status shown as icon + label, never color alone. */
export default function StatusChip({ status }: { status: GameStatus }) {
  return (
    <span className={`chip ${status}`}>
      <span aria-hidden="true">{ICON[status]}</span>
      {STATUS_LABEL[status]}
    </span>
  )
}
