import { useEffect, useState } from 'react'

const NAMES = ['accent', 'deemph', 'surface', 'grid', 'axis', 'muted', 'ink'] as const
export type ThemeColors = Record<(typeof NAMES)[number], string>

function read(): ThemeColors {
  const style = getComputedStyle(document.documentElement)
  return Object.fromEntries(
    NAMES.map((name) => [name, style.getPropertyValue(`--${name}`).trim()]),
  ) as ThemeColors
}

/** The CSS color tokens as values. SVG attributes (which Recharts sets) can't use var(). */
export function useThemeColors(): ThemeColors {
  const [colors, setColors] = useState(read)
  useEffect(() => {
    const query = window.matchMedia('(prefers-color-scheme: dark)')
    const update = () => setColors(read())
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])
  return colors
}
