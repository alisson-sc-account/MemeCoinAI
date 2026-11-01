import { useEffect, useMemo, useRef, useState } from 'react'
import { createChart, type IChartApi, type Time, type TickMarkFormatter, type TimeFormatterFn } from 'lightweight-charts'
import type { BuySimulation, ExitPlan, History } from '../api/types'
import { ageText, percent, price, usd } from '../lib/format'
import { buildCandles, coinSimulation, dateFromChartTime, formatChartTick, priceMinMove, SIMULATED_COINS, type Candle, type Sample } from './chartMath'
import styles from './PriceChart.module.css'

type Point = History['points'][number]
type LiveFeed = ExitPlan['live']

type Props = {
  points: Point[]
  range: string
  downsampled: boolean
  live: LiveFeed | null
  fallbackPrice: number | null
  fallbackAt: string | null
  simulation: BuySimulation | null
}

const clock = (iso: string) => new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
const MIN_VISIBLE_BARS = 40
const coins = new Intl.NumberFormat('pt-BR').format(SIMULATED_COINS)

export default function PriceChart({ points, range, downsampled, live, fallbackPrice, fallbackAt, simulation }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ReturnType<IChartApi['addCandlestickSeries']> | null>(null)
  const candlesRef = useRef<Candle[]>([])
  const rangeRef = useRef(range)
  const [livePoints, setLivePoints] = useState<Sample[]>([])
  const now = Date.now()
  const livePrice = live?.status === 'live' ? live.price_usd : null
  const currentPrice = livePrice ?? fallbackPrice
  const currentAt = livePrice != null ? live?.observed_at ?? null : fallbackAt

  useEffect(() => {
    if (live?.status !== 'live' || live.price_usd == null || !live.observed_at) return
    const observedAt = live.observed_at
    const observedPrice = live.price_usd
    setLivePoints(old => {
      if (old.at(-1)?.t === observedAt) return old
      return [...old, { t: observedAt, price: observedPrice }].slice(-7_200)
    })
  }, [live?.observed_at, live?.price_usd, live?.status])

  const candles = useMemo(() => buildCandles(points, livePoints, range), [points, livePoints, range])
  const sim = useMemo(() => coinSimulation(simulation?.entry_price_usd ?? null, currentPrice), [simulation?.entry_price_usd, currentPrice])
  const scalePrice = candles.at(-1)?.close ?? currentPrice

  useEffect(() => {
    const el = container.current
    if (!el) return
    const root = getComputedStyle(document.documentElement)
    const color = (name: string, fallback: string) => root.getPropertyValue(name).trim() || fallback
    const line = color('--border', '#262626')
    const chart = createChart(el, {
      width: Math.max(el.clientWidth, 1), height: 360,
      layout: { background: { color: color('--surface-1', '#111111') }, textColor: color('--text-muted', '#a3a3a3'), fontFamily: "'JetBrains Mono', ui-monospace, monospace", fontSize: 11 },
      grid: { vertLines: { visible: false }, horzLines: { color: line } },
      rightPriceScale: { borderColor: line, scaleMargins: { top: 0.08, bottom: 0.08 } },
      timeScale: {
        borderColor: line, timeVisible: true, secondsVisible: false, barSpacing: 9, rightOffset: 4,
        tickMarkFormatter: ((time: Time) => formatChartTick(time, rangeRef.current)) as TickMarkFormatter,
      },
      localization: {
        locale: 'pt-BR',
        priceFormatter: (value: number) => price(value),
        timeFormatter: ((time: Time) => new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'medium' }).format(dateFromChartTime(time))) as TimeFormatterFn,
      },
    })
    const green = color('--positive', '#22c55e')
    const red = color('--negative', '#f04438')
    const series = chart.addCandlestickSeries({ upColor: green, downColor: red, borderUpColor: green, borderDownColor: red, wickUpColor: green, wickDownColor: red, priceLineVisible: true, lastValueVisible: true })
    chartRef.current = chart
    seriesRef.current = series
    const observer = new ResizeObserver(entries => {
      const width = entries[0]?.contentRect.width
      if (width) chart.applyOptions({ width: Math.max(width, 1) })
    })
    observer.observe(el)
    return () => {
      observer.disconnect()
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
    }
  }, [])

  // O padrão da biblioteca arredonda em 0,01: preços de memecoin viravam uma linha reta invisível.
  useEffect(() => {
    if (scalePrice == null || scalePrice <= 0) return
    seriesRef.current?.applyOptions({ priceFormat: { type: 'custom', minMove: priceMinMove(scalePrice), formatter: (value: number) => price(value) } })
  }, [scalePrice])

  useEffect(() => {
    const chart = chartRef.current
    const series = seriesRef.current
    if (!chart || !series) return
    const timeScale = chart.timeScale()
    const previousRange = timeScale.getVisibleLogicalRange()
    const previousCount = candlesRef.current.length
    const wasFollowingLive = previousRange == null || previousRange.to >= previousCount - 1
    const rangeChanged = rangeRef.current !== range
    series.setData(candles)
    candlesRef.current = candles
    if (candles.length && (previousRange == null || rangeChanged)) {
      // Moeda nova, com poucas velas: esticar para caber deixava uma vela ocupando o gráfico inteiro.
      if (candles.length < MIN_VISIBLE_BARS) timeScale.setVisibleLogicalRange({ from: candles.length - MIN_VISIBLE_BARS, to: candles.length + 2 })
      else timeScale.fitContent()
    }
    else if (previousRange) {
      if (wasFollowingLive) timeScale.scrollToRealTime()
      else try { timeScale.setVisibleLogicalRange(previousRange) } catch { /* Dados novos podem encurtar a faixa. */ }
    }
    rangeRef.current = range
  }, [candles, range])

  useEffect(() => {
    chartRef.current?.applyOptions({ timeScale: { tickMarkFormatter: ((time: Time) => formatChartTick(time, range)) as TickMarkFormatter } })
  }, [range])

  // Seta de COMPRA no candle em que o sinal apitou.
  useEffect(() => {
    const series = seriesRef.current
    if (!series) return
    if (!simulation || candles.length === 0) { series.setMarkers([]); return }
    const at = Date.parse(simulation.signal_at) / 1000
    const first = Number(candles[0].time)
    if (at < first) { series.setMarkers([]); return }
    const nearest = candles.reduce((best, c) => Math.abs(Number(c.time) - at) < Math.abs(Number(best.time) - at) ? c : best, candles[0])
    series.setMarkers([{ time: nearest.time, position: 'belowBar', color: '#22c55e', shape: 'arrowUp', text: 'COMPRA' }])
  }, [candles, simulation])

  const good = sim != null && sim.pnl >= 0
  return <div className={styles.layout}>
    <div className={styles.chartColumn}>
      <div role="img" aria-label={`Gráfico de candles do preço em dólares, ${candles.length} candles observados`}><div ref={container} className={styles.chart} style={candles.length ? undefined : { display: 'none' }}/></div>
      {candles.length === 0 && <div className={styles.emptyChart}>Sem histórico nesse intervalo.</div>}
      {downsampled && <p className={styles.chartNote}>Histórico amostrado pelo sistema.</p>}
    </div>

    <aside className={styles.panel} aria-label="Simulação" aria-live="polite">
      {simulation && sim ? <>
        <small className={styles.meta}>Se você tivesse comprado {coins} moedas no sinal das <b>{clock(simulation.signal_at)}</b></small>
        <strong className={`${styles.pnl} ${good ? styles.positive : styles.negative}`}>{percent(sim.pnlPercent)}</strong>
        <div className={styles.metrics}>
          <div><small>Pagou</small><b>{price(sim.paid)}</b></div>
          <div><small>Vale agora</small><b>{price(sim.value)}</b></div>
          <div><small>Preço na compra</small><b>{price(simulation.entry_price_usd)}</b></div>
          <div><small>Preço agora</small><b>{price(currentPrice)}</b></div>
        </div>
        <p className={styles.meta}>Com US$ 1.000 no mesmo sinal, teria agora <b className={good ? styles.positive : styles.negative}>{usd(sim.valueOf1000)}</b>.</p>
      </> : simulation ? <p className={styles.meta}>Aguardando preço para calcular.</p>
        : <p className={styles.meta}>Esta moeda ainda não teve sinal de compra. A simulação começa sozinha quando apitar.</p>}
      <small className={styles.meta}>{currentAt ? `Atualizado ${ageText(currentAt, now)}` : 'Sem cotação agora'} · sem taxas nem slippage</small>
    </aside>
  </div>
}
