import { describe, expect, it } from 'vitest'
import { buildCandles, candleSeconds, coinSimulation, formatChartTick, priceMinMove } from './chartMath'

const point = (seconds: number, value: number) => ({
  t: new Date(seconds * 1000).toISOString(), price_usd: value, liquidity_usd: null, market_cap: null,
  volume_h1: null, buys_h1: null, sells_h1: null,
})

describe('PriceChart aggregation and simulation', () => {
  it('aggregates observed snapshots and live quotes into green/red candle values', () => {
    const bucket = Math.floor(Date.now() / 60) * 60 - 30
    const candles = buildCandles(
      [point(bucket + 1, 1), point(bucket + 15, 3)],
      [{ t: new Date((bucket + 25) * 1000).toISOString(), price: 2 }],
      '1h',
    )
    expect(candles).toHaveLength(1)
    expect(candles[0]).toMatchObject({ time: Math.floor((bucket + 1) / 60) * 60, open: 1, high: 3, low: 1, close: 2 })
  })

  it('uses candle intervals that fit the selected visible range', () => {
    expect(['1h', '6h', '24h', '7d'].map(candleSeconds)).toEqual([60, 300, 900, 3600])
  })

  it('simulates 1000 coins bought at the buy signal, with no input from the user', () => {
    expect(coinSimulation(0.5, 0.75)).toEqual({ paid: 500, value: 750, pnl: 250, pnlPercent: 50, valueOf1000: 1500 })
    expect(coinSimulation(0.5, 0.25)).toMatchObject({ pnl: -250, pnlPercent: -50, valueOf1000: 500 })
    expect(coinSimulation(null, 0.75)).toBeNull()
    expect(coinSimulation(0.5, null)).toBeNull()
  })

  it('keeps the price axis precise for tiny memecoin prices', () => {
    expect(priceMinMove(0.00001409)).toBeCloseTo(1e-9, 15)
    expect(priceMinMove(31296.44)).toBe(1)
  })

  it('formats chart ticks in the browser local time zone', () => {
    const seconds = Math.floor(Date.UTC(2026, 9, 30, 17, 0) / 1000)
    const expected = new Intl.DateTimeFormat('pt-BR', {
      hour: '2-digit', minute: '2-digit', timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    }).format(new Date(seconds * 1000))
    expect(formatChartTick(seconds as never, '24h')).toBe(expected)
  })
})
