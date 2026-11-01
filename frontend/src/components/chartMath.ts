import type { Time, UTCTimestamp } from 'lightweight-charts'
import type { History } from '../api/types'

type Point = History['points'][number]
export type Candle = { time: UTCTimestamp; open: number; high: number; low: number; close: number; closeAt: number }
export type Sample = { t: string; price: number }
export type SimulationEntry = { time: number; price: number }

const CANDLE_SECONDS: Record<string, number> = { '1h': 60, '6h': 300, '24h': 900, '7d': 3600 }
const RANGE_SECONDS: Record<string, number> = { '1h': 3600, '6h': 21600, '24h': 86400, '7d': 604800 }

export function candleSeconds(range: string): number { return CANDLE_SECONDS[range] ?? CANDLE_SECONDS['24h'] }

function epochSeconds(time: Time): number {
  if (typeof time === 'number') return time
  if (typeof time === 'string') return Math.floor(new Date(time).getTime() / 1000)
  return Math.floor(Date.UTC(time.year, time.month - 1, time.day) / 1000)
}

/** Agrega apenas preços observados em candles; não inventa negócios nem volume. */
export function buildCandles(points: Point[], livePoints: Sample[], range: string): Candle[] {
  const step = candleSeconds(range)
  const samples = [
    ...points.flatMap(point => point.price_usd != null && Number.isFinite(point.price_usd)
      ? [{ t: point.t, price: point.price_usd }]
      : []),
    ...livePoints,
  ].map(point => ({ ...point, seconds: Math.floor(new Date(point.t).getTime() / 1000) }))
    .filter(point => Number.isFinite(point.seconds) && point.price > 0 && Number.isFinite(point.price))
    .sort((a, b) => a.seconds - b.seconds)

  const cutoff = Date.now() / 1000 - (RANGE_SECONDS[range] ?? RANGE_SECONDS['24h'])
  const buckets = new Map<number, Candle>()
  for (const sample of samples) {
    if (sample.seconds < cutoff) continue
    const time = (Math.floor(sample.seconds / step) * step) as UTCTimestamp
    const candle = buckets.get(time)
    if (!candle) buckets.set(time, { time, open: sample.price, high: sample.price, low: sample.price, close: sample.price, closeAt: sample.seconds })
    else {
      candle.high = Math.max(candle.high, sample.price)
      candle.low = Math.min(candle.low, sample.price)
      candle.close = sample.price
      candle.closeAt = sample.seconds
    }
  }
  return [...buckets.values()].sort((a, b) => a.time - b.time)
}

export const SIMULATED_COINS = 1000

/** Quanto teria ganhado comprando no preço do sinal. Bruto: sem taxas nem slippage. */
export function coinSimulation(entryPrice: number | null, currentPrice: number | null, coins = SIMULATED_COINS) {
  if (!(entryPrice && entryPrice > 0) || !(currentPrice && currentPrice > 0)) return null
  const paid = coins * entryPrice
  const value = coins * currentPrice
  return { paid, value, pnl: value - paid, pnlPercent: (currentPrice / entryPrice - 1) * 100, valueOf1000: 1000 * currentPrice / entryPrice }
}

/** Menor passo do eixo de preço: 4 casas abaixo do primeiro dígito do preço. */
export function priceMinMove(value: number): number {
  return 10 ** (Math.floor(Math.log10(value)) - 4)
}

export function dateFromChartTime(time: Time): Date { return new Date(epochSeconds(time) * 1000) }

export function formatChartTick(time: Time, range: string): string {
  const date = dateFromChartTime(time)
  const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone
  const options: Intl.DateTimeFormatOptions = range === '7d'
    ? { day: '2-digit', month: '2-digit' }
    : { hour: '2-digit', minute: '2-digit' }
  return new Intl.DateTimeFormat('pt-BR', { ...options, timeZone }).format(date)
}
