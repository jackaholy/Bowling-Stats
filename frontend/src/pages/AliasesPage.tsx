import { useCallback, useEffect, useState } from 'react'
import { api, type Alias } from '../api'

export default function AliasesPage({ onGamesChanged }: { onGamesChanged: () => void }) {
  const [aliases, setAliases] = useState<Alias[] | null>(null)
  const [name, setName] = useState('')
  const [confirm, setConfirm] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    api.aliases().then(setAliases, (e: Error) => setError(e.message))
  }, [])
  useEffect(load, [load])

  async function attempt(action: () => Promise<void>) {
    setError(null)
    setMessage(null)
    try {
      await action()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const add = () =>
    attempt(async () => {
      await api.addAlias(name, confirm)
      setName('')
      setConfirm(false)
      load()
      const changed = await api.rematch() // free: re-reads stored readings, no API calls
      setMessage(
        changed.length
          ? `Added. ${changed.length} game(s) that hadn't matched were re-checked.`
          : 'Added.',
      )
      if (changed.length) onGamesChanged()
    })

  return (
    <div className="card stack" style={{ maxWidth: '40rem' }}>
      <h1>Your names</h1>
      <p className="secondary" style={{ margin: 0 }}>
        Rows on a scoreboard are matched to these names, ignoring case and spaces. Mark a name
        that a friend might also use, so its games wait for you to confirm the row.
      </p>
      <div className="row">
        <input
          type="text"
          placeholder="New name"
          value={name}
          aria-label="New name"
          onChange={(e) => setName(e.target.value)}
        />
        <label className="row">
          <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
          A friend might use it
        </label>
        <button className="primary" disabled={name.trim() === ''} onClick={() => void add()}>
          Add
        </button>
      </div>
      {message && <p className="secondary">{message}</p>}
      {error && <p className="error">{error}</p>}
      {aliases && (
        <table className="data-table" style={{ width: '100%' }}>
          <thead>
            <tr>
              <th>Name</th>
              <th style={{ textAlign: 'left' }}>Confirm each game</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {aliases.map((alias) => (
              <tr key={alias.id}>
                <td>{alias.name}</td>
                <td style={{ textAlign: 'left' }}>
                  <input
                    type="checkbox"
                    checked={alias.confirm}
                    aria-label={`Confirm each game matched by ${alias.name}`}
                    onChange={(e) =>
                      void attempt(async () => {
                        await api.setAliasConfirm(alias.id, e.target.checked)
                        load()
                      })
                    }
                  />
                </td>
                <td>
                  <button
                    className="danger"
                    onClick={() => {
                      if (window.confirm(`Remove ${alias.name} from your names?`)) {
                        void attempt(async () => {
                          await api.deleteAlias(alias.id)
                          load()
                        })
                      }
                    }}
                  >
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
