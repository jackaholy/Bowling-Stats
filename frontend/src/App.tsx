import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import AddGamePage from './pages/AddGamePage'
import AliasesPage from './pages/AliasesPage'
import GameBrowser from './pages/GameBrowser'
import StatsPage from './pages/StatsPage'
import UploadPage from './pages/UploadPage'

const PAGES = ['review', 'stats', 'games', 'add', 'upload', 'names'] as const
type Page = (typeof PAGES)[number]

const TITLES: Record<Page, string> = {
  review: 'Review',
  stats: 'Stats',
  games: 'All games',
  add: 'Add game',
  upload: 'Upload',
  names: 'Your names',
}

function pageFromHash(): Page {
  const hash = window.location.hash.slice(1)
  return (PAGES as readonly string[]).includes(hash) ? (hash as Page) : 'review'
}

export default function App() {
  const [page, setPage] = useState<Page>(pageFromHash)
  const [reviewCount, setReviewCount] = useState<number | null>(null)
  // Bumped whenever games change, so pages that cache data reload.
  const [version, setVersion] = useState(0)

  const refreshCount = useCallback(() => {
    api.games().then(
      (games) =>
        setReviewCount(games.filter((g) => g.status === 'needs_review' || g.status === 'pending').length),
      () => setReviewCount(null),
    )
  }, [])
  useEffect(refreshCount, [refreshCount, version])

  useEffect(() => {
    const onHash = () => setPage(pageFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const gamesChanged = useCallback(() => setVersion((v) => v + 1), [])
  const go = (next: Page) => {
    window.location.hash = next
    setPage(next)
  }

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">Bowling Stats</span>
        <nav aria-label="Pages">
          {PAGES.map((p) => (
            <button key={p} aria-current={p === page ? 'page' : undefined} onClick={() => go(p)}>
              {TITLES[p]}
              {p === 'review' && reviewCount !== null && reviewCount > 0 && (
                <span className="count" aria-label={`${reviewCount} to review`}>
                  {reviewCount}
                </span>
              )}
            </button>
          ))}
        </nav>
      </header>
      <main>
        {page === 'review' && <GameBrowser key="review" review onGamesChanged={gamesChanged} />}
        {page === 'games' && <GameBrowser key="games" review={false} onGamesChanged={gamesChanged} />}
        {page === 'stats' && <StatsPage key={version} />}
        {page === 'add' && <AddGamePage onGamesChanged={gamesChanged} />}
        {page === 'upload' && <UploadPage onGamesChanged={gamesChanged} />}
        {page === 'names' && <AliasesPage onGamesChanged={gamesChanged} />}
      </main>
    </div>
  )
}
