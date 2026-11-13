// Types mirror backend/app/schemas.py. The backend computes every score; the frontend only shows them.

export type GameStatus = 'pending' | 'verified' | 'needs_review' | 'skipped' | 'manual'
export type Roll = string | null // "X", "/", "-", "1".."9"; null = unreadable
export type Rolls = Roll[][]

export interface Mark {
  frame: number
  ball: number
  kind: 'foul' | 'split'
}

export interface Game {
  id: number
  status: GameStatus
  played_on: string | null // YYYY-MM-DD
  captured_at: string | null
  photo_id: number | null
  photo_name: string | null
  name_on_board: string | null
  frames: Rolls | null
  marks: Mark[]
  printed_cumulative: (number | null)[] | null
  printed_total: number | null
  scores: (number | null)[] | null
  total: number | null
  missing_rolls: [number, number][]
  review_reasons: string[]
}

export interface BoardRow {
  index: number
  name: string
  final_total: number | null
  matches_alias: boolean
}

export interface GameDetail extends Game {
  rows: BoardRow[]
  notes: string | null
}

export interface GameEdit {
  frames?: Rolls
  played_on?: string | null
  printed_cumulative?: (number | null)[]
  printed_total?: number | null
}

export interface Alias {
  id: number
  name: string
  confirm: boolean
}

export interface TrendPoint {
  game_id: number
  played_on: string | null
  total: number
  rolling_average: number
}

export interface Stats {
  games_played: number
  average: number | null
  high: number | null
  low: number | null
  strikes: number
  strike_chances: number
  strike_rate: number | null
  spares: number
  spare_chances: number
  spare_rate: number | null
  open_frames: number
  frames: number
  open_rate: number | null
  trend: TrendPoint[]
}

export class ApiError extends Error {
  readonly status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    let message = response.statusText
    try {
      const body: unknown = await response.json()
      if (body && typeof body === 'object' && 'detail' in body) {
        const detail = (body as { detail: unknown }).detail
        message = typeof detail === 'string' ? detail : JSON.stringify(detail)
      }
    } catch {
      // keep the status text
    }
    throw new ApiError(response.status, message)
  }
  return (response.status === 204 ? undefined : await response.json()) as T
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: body === undefined ? undefined : JSON.stringify(body),
})

export const api = {
  games: (status?: GameStatus) =>
    request<Game[]>(status ? `/api/games?status=${status}` : '/api/games'),
  game: (id: number) => request<GameDetail>(`/api/games/${id}`),
  editGame: (id: number, edit: GameEdit) =>
    request<GameDetail>(`/api/games/${id}`, json('PATCH', edit)),
  pickRow: (id: number, rowIndex: number, saveAlias: boolean) =>
    request<GameDetail>(
      `/api/games/${id}/pick-row`,
      json('POST', { row_index: rowIndex, save_alias: saveAlias }),
    ),
  skip: (id: number) => request<GameDetail>(`/api/games/${id}/skip`, json('POST')),
  unskip: (id: number) => request<GameDetail>(`/api/games/${id}/unskip`, json('POST')),
  retry: (id: number) => request<GameDetail>(`/api/games/${id}/retry`, json('POST')),
  addManual: (playedOn: string, frames: Rolls) =>
    request<GameDetail>('/api/games', json('POST', { played_on: playedOn, frames })),
  deleteGame: (id: number) => request<void>(`/api/games/${id}`, { method: 'DELETE' }),
  rematch: () => request<Game[]>('/api/games/rematch', json('POST')),
  aliases: () => request<Alias[]>('/api/aliases'),
  addAlias: (name: string, confirm: boolean) =>
    request<Alias>('/api/aliases', json('POST', { name, confirm })),
  setAliasConfirm: (id: number, confirm: boolean) =>
    request<Alias>(`/api/aliases/${id}`, json('PATCH', { confirm })),
  deleteAlias: (id: number) => request<void>(`/api/aliases/${id}`, { method: 'DELETE' }),
  stats: () => request<Stats>('/api/stats'),
  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<{ game: GameDetail; duplicate: boolean }>('/api/photos', {
      method: 'POST',
      body: form,
    })
  },
  photoUrl: (photoId: number) => `/api/photos/${photoId}/image`,
}

export const STATUS_LABEL: Record<GameStatus, string> = {
  pending: 'Not read yet',
  verified: 'Verified',
  needs_review: 'Needs review',
  skipped: 'Skipped',
  manual: 'Entered by hand',
}
