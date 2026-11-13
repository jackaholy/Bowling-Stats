import { useState } from 'react'
import { api, STATUS_LABEL } from '../api'

interface Item {
  file: File
  state: 'waiting' | 'reading' | 'done' | 'error'
  result?: string
}

const COST_PER_PHOTO = 0.05

/** Upload photos one at a time (each is read by Claude, ~10 s and ~$0.05; duplicates are free).
 * For hundreds of photos, the bulk script is faster: backend/scripts/import_photos.py. */
export default function UploadPage({ onGamesChanged }: { onGamesChanged: () => void }) {
  const [items, setItems] = useState<Item[]>([])
  const [running, setRunning] = useState(false)

  const update = (index: number, patch: Partial<Item>) =>
    setItems((current) => current.map((item, i) => (i === index ? { ...item, ...patch } : item)))

  async function start() {
    setRunning(true)
    for (const [index, item] of items.entries()) {
      if (item.state !== 'waiting') continue
      update(index, { state: 'reading' })
      try {
        const { game, duplicate } = await api.upload(item.file)
        const outcome = duplicate
          ? 'already imported'
          : `${STATUS_LABEL[game.status]}${game.total !== null ? ` · ${game.total}` : ''}${
              game.review_reasons[0] ? ` · ${game.review_reasons[0]}` : ''
            }`
        update(index, { state: 'done', result: outcome })
      } catch (e) {
        update(index, { state: 'error', result: e instanceof Error ? e.message : String(e) })
      }
    }
    setRunning(false)
    onGamesChanged()
  }

  const waiting = items.filter((item) => item.state === 'waiting').length

  return (
    <div className="card stack" style={{ maxWidth: '48rem' }}>
      <h1>Upload photos</h1>
      <p className="secondary" style={{ margin: 0 }}>
        Each new photo is read by Claude (about 10 seconds and ${COST_PER_PHOTO.toFixed(2)}). Photos
        you've already imported are recognized and skipped for free.
      </p>
      <input
        type="file"
        accept="image/*,.heic,.heif"
        multiple
        disabled={running}
        aria-label="Choose photos"
        onChange={(e) =>
          setItems(Array.from(e.target.files ?? []).map((file) => ({ file, state: 'waiting' })))
        }
      />
      {items.length > 0 && (
        <>
          <div className="row">
            <button className="primary" disabled={running || waiting === 0} onClick={() => void start()}>
              {running ? 'Importing…' : `Import ${waiting} photo(s) (up to ~$${(waiting * COST_PER_PHOTO).toFixed(2)})`}
            </button>
          </div>
          <table className="data-table" style={{ width: '100%' }}>
            <tbody>
              {items.map((item, i) => (
                <tr key={`${item.file.name}-${i}`}>
                  <td>{item.file.name}</td>
                  <td style={{ textAlign: 'left' }} className={item.state === 'error' ? 'error' : 'secondary'}>
                    {item.state === 'waiting' && 'waiting'}
                    {item.state === 'reading' && 'reading…'}
                    {(item.state === 'done' || item.state === 'error') && item.result}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  )
}
