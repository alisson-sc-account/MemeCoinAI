import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { apiClient } from '../api/client'
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
  chainId?: string
  address?: string
}

const clock = (iso: string) => new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
const MIN_VISIBLE_BARS = 40
const coins = new Intl.NumberFormat('pt-BR').format(SIMULATED_COINS)

export default function PriceChart({ points, range, downsampled, live, fallbackPrice, fallbackAt, simulation, chainId, address }: Props) {
  const qc = useQueryClient()
  // Parar de contar: grava o ganho deste instante em Favoritados e congela o painel.
  const stop = useMutation({
    mutationFn: () => apiClient.addFavorite(chainId ?? '', address ?? '', simulation?.signal_id ?? null),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['favorites'] }),
  })
  const frozen = stop.data
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

  // Histórico com buraco (sistema desligado) e preço ao vivo de outra fonte geravam uma vela solta lá no alto:
  // só junta o ao vivo quando o histórico é recente.
  const lastAt = points.length ? Date.parse(points[points.length - 1].t) : 0
  const historyFresh = points.length === 0 || Date.now() - lastAt < 30 * 60_000
  const allCandles = useMemo(() => buildCandles(points, historyFresh ? livePoints : [], range), [points, livePoints, range, historyFresh])
  // O eixo do tempo não mostra buracos: horas com o sistema desligado viravam um degrau falso entre duas velas.
  // Mostra só o trecho contínuo mais recente e avisa que há um buraco.
  const gapAt = useMemo(() => {
    for (let i = allCandles.length - 1; i > 0; i--) if (Number(allCandles[i].time) - Number(allCandles[i - 1].time) > 30 * 60) return i
    return 0
  }, [allCandles])
  const candles = useMemo(() => allCandles.slice(gapAt), [allCandles, gapAt])
  // Sem sinal de compra, conta desde que a moeda foi aberta: o lucro sempre aparece subindo ou descendo ao vivo.
  const openedRef = useRef<{ price: number; at: string } | null>(null)
  if (!openedRef.current && currentPrice) openedRef.current = { price: currentPrice, at: new Date().toISOString() }
  const entryPrice = simulation?.entry_price_usd ?? openedRef.current?.price ?? null
  const entryAt = simulation?.signal_at ?? openedRef.current?.at ?? null
  const sim = useMemo(() => coinSimulation(entryPrice, currentPrice), [entryPrice, currentPrice])
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
      rightPriceScale: { borderColor: line, mode: 1, scaleMargins: { top: 0.08, bottom: 0.08 } },  // escala logarítmica: alta forte não achata o resto
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
    series.setMarkers([{ time: nearest.time, position: 'belowBar', color: '#22c55e', shape: 'arrowUp', text: 'INICIOU AQUI' }])
  }, [candles, simulation])

  const good = sim != null && sim.pnl >= 0
  return <div className={styles.layout}>
    <div className={styles.chartColumn}>
      <div role="img" aria-label={`Gráfico de candles do preço em dólares, ${candles.length} candles observados`}><div ref={container} className={styles.chart} style={candles.length ? undefined : { display: 'none' }}/></div>
      {candles.length === 0 && <div className={styles.emptyChart}>Sem histórico nesse intervalo.</div>}
      {downsampled && <p className={styles.chartNote}>Histórico amostrado pelo sistema.</p>}
      {gapAt > 0 && <p className={styles.chartNote}>Mostrando desde {new Date(Number(candles[0]?.time) * 1000).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}: antes disso o sistema ficou sem coletar.</p>}
    </div>

    <aside className={styles.panel} aria-label="Simulação" aria-live="polite">
      {sim && entryAt ? <>
        <small className={styles.meta}>{simulation ? 'Iniciou no sinal das' : 'Sem sinal de compra: contando desde que abriu, às'} <b>{clock(entryAt)}</b> ({coins} moedas)</small>
        <small className={styles.meta}>Lucro até agora</small>
        <strong className={`${styles.pnl} ${good ? styles.positive : styles.negative}`}>{percent(sim.pnlPercent)}</strong>
        {chainId && address && (frozen
          ? <Link to="/favoritados" className={styles.stopDone}>Salvo em Favoritados com {percent(frozen.gain_at_favorite == null ? null : frozen.gain_at_favorite * 100)} no clique →</Link>
          : <button type="button" className={styles.stopButton} disabled={stop.isPending} onClick={() => stop.mutate()}>{stop.isPending ? 'Salvando…' : 'Parar de contar'}</button>)}
        {stop.isError && <small className={styles.negative}>{(stop.error as Error).message}</small>}
        <div className={styles.metrics}>
          <div><small>Pagou</small><b>{price(sim.paid)}</b></div>
          <div><small>Vale agora</small><b>{price(sim.value)}</b></div>
          <div><small>Preço na compra</small><b>{price(entryPrice)}</b></div>
          <div><small>Preço agora</small><b>{price(currentPrice)}</b></div>
        </div>
        <p className={styles.meta}>Com US$ 1.000 no mesmo sinal, teria agora <b className={good ? styles.positive : styles.negative}>{usd(sim.valueOf1000)}</b>.</p>
      </> : <p className={styles.meta}>Aguardando preço para calcular.</p>}
      <small className={styles.meta}>{currentAt ? `Atualizado ${ageText(currentAt, now)}` : 'Sem cotação agora'} · sem taxas nem slippage</small>
    </aside>
  </div>
}
