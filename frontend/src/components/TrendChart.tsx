import {
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from 'recharts'
import type { TrendPoint } from '../api'
import { useThemeColors } from '../useThemeColors'

interface Row extends TrendPoint {
  n: number // game number in play order, 1-based
}

/** Emphasis form: the 10-game rolling average is the story (accent line); each game is
 * context (gray dots). One y-axis. Crosshair + tooltip on hover; the table view below
 * carries every value too. */
export default function TrendChart({ trend }: { trend: TrendPoint[] }) {
  const colors = useThemeColors()
  const rows: Row[] = trend.map((point, i) => ({ ...point, n: i + 1 }))
  const last = rows[rows.length - 1]
  const totals = rows.map((r) => r.total)
  const low = Math.floor((Math.min(...totals) - 5) / 25) * 25
  const high = Math.ceil((Math.max(...totals) + 5) / 25) * 25
  const ticks = Array.from({ length: (high - low) / 25 + 1 }, (_, i) => low + i * 25)

  return (
    <div>
      <div className="legend" aria-hidden="true">
        <span className="key">
          <svg width="18" height="10">
            <line x1="1" y1="5" x2="17" y2="5" stroke={colors.accent} strokeWidth="2" strokeLinecap="round" />
          </svg>
          10-game average
        </span>
        <span className="key">
          <svg width="12" height="12">
            <circle cx="6" cy="6" r="4" fill={colors.deemph} />
          </svg>
          Game score
        </span>
      </div>
      <div style={{ width: '100%', height: 340 }}>
        <ResponsiveContainer>
          <ComposedChart data={rows} margin={{ top: 16, right: 92, bottom: 24, left: 0 }}>
            <CartesianGrid vertical={false} stroke={colors.grid} strokeWidth={1} />
            <XAxis
              dataKey="n"
              type="number"
              domain={[1, Math.max(rows.length, 2)]}
              tickCount={8}
              allowDecimals={false}
              stroke={colors.axis}
              tick={{ fill: colors.muted, fontSize: 12 }}
              label={{ value: 'Game (in play order)', position: 'insideBottom', offset: -14, fill: colors.muted, fontSize: 12 }}
            />
            <YAxis
              domain={[low, high]}
              ticks={ticks}
              stroke={colors.axis}
              tick={{ fill: colors.muted, fontSize: 12 }}
              width={44}
            />
            <Tooltip
              content={<TrendTooltip />}
              cursor={{ stroke: colors.axis, strokeWidth: 1 }}
              isAnimationActive={false}
            />
            <Line
              dataKey="total"
              name="Game score"
              stroke="none"
              isAnimationActive={false}
              dot={{ r: 4, fill: colors.deemph, stroke: colors.surface, strokeWidth: 2 }}
              activeDot={{ r: 6, fill: colors.deemph, stroke: colors.surface, strokeWidth: 2 }}
            />
            <Line
              dataKey="rolling_average"
              name="10-game average"
              stroke={colors.accent}
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
              dot={false}
              activeDot={{ r: 5, fill: colors.accent, stroke: colors.surface, strokeWidth: 2 }}
              isAnimationActive={false}
              label={(props: { x?: number; y?: number; index?: number }) =>
                props.index === rows.length - 1 && props.x !== undefined && props.y !== undefined ? (
                  <text x={props.x + 10} y={props.y + 4} fill={colors.ink} fontSize={12}>
                    avg {last.rolling_average.toFixed(1)}
                  </text>
                ) : (
                  <g />
                )
              }
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

function TrendTooltip({ active, payload }: TooltipProps<number, string>) {
  if (!active || !payload?.length) return null
  const row = payload[0].payload as Row
  return (
    <div className="chart-tooltip">
      <div className="muted">
        Game {row.n} · {row.played_on ?? 'no date'}
      </div>
      <div>
        <span className="val">{row.total}</span> <span className="secondary">score</span>
      </div>
      <div>
        <span className="val">{row.rolling_average.toFixed(1)}</span>{' '}
        <span className="secondary">10-game average</span>
      </div>
    </div>
  )
}
