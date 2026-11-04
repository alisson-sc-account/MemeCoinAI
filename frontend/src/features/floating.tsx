import { useEffect, useState } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { apiClient } from '../api/client'
import type { ExitPlan } from '../api/types'
import { openAxiom } from '../lib/axiom'

/** Janela de venda que fica por cima de tudo (Alt+Tab para a Axiom continua mostrando). Picture-in-Picture de documento. */
const POLL_MS = 1500
const COLORS = { sell_now: '#e3262b', reduce: '#f97316', hold: '#16c75f', no_data: '#8c8c91' } as Record<string, string>
const TITLE = { sell_now: 'VENDER AGORA', reduce: 'REDUZIR', hold: 'SEGURAR', no_data: 'SEM DADOS' } as Record<string, string>

type PipApi = { requestWindow: (o: { width: number; height: number }) => Promise<Window> }
const pip = () => (window as unknown as { documentPictureInPicture?: PipApi }).documentPictureInPicture
let current: { win: Window; root: Root } | null = null

const pct = (v: number | null | undefined) => v == null ? '—' : `${v > 0 ? '+' : ''}${(v * 100).toFixed(1)}%`
const price = (v: number | null | undefined) => v == null ? '—' : v < 0.01 ? `$${v.toPrecision(4)}` : `$${v.toFixed(4)}`

function beep(win: Window) {
  try {
    const Ctx = (win as unknown as { AudioContext: typeof AudioContext }).AudioContext
    const ctx = new Ctx()
    const o = ctx.createOscillator(), g = ctx.createGain()
    o.frequency.value = 880; g.gain.value = 0.15; o.connect(g); g.connect(ctx.destination); o.start(); o.stop(ctx.currentTime + 0.35)
  } catch { /* sem áudio */ }
}

function FloatingView({ chainId, address, symbol, win }: { chainId: string; address: string; symbol: string; win: Window }) {
  const [p, setP] = useState<ExitPlan | null>(null)
  const [err, setErr] = useState('')
  const [at, setAt] = useState(0)
  useEffect(() => {
    let alive = true, last = ''
    const tick = async () => {
      try {
        void apiClient.watch(chainId, address).catch(() => undefined)  // mantém o preço ao vivo (~1 s) mesmo com a aba escondida
        const plan = await apiClient.exitPlan(chainId, address)
        if (!alive) return
        if (last && plan.urgency !== last && (plan.urgency === 'sell_now' || plan.urgency === 'reduce')) beep(win)
        last = plan.urgency
        setP(plan); setErr(''); setAt(Date.now())
      } catch (e) { if (alive) setErr(e instanceof Error ? e.message : 'falha') }
    }
    void tick()
    const t = win.setInterval(() => void tick(), POLL_MS)
    return () => { alive = false; win.clearInterval(t) }
  }, [chainId, address, win])
  const color = COLORS[p?.urgency ?? 'no_data']
  const age = at ? Math.round((Date.now() - at) / 1000) : null
  return <div style={{ fontFamily: 'Inter,system-ui,sans-serif', color: '#eef1ef', background: '#08090a', height: '100vh', padding: 12, boxSizing: 'border-box', display: 'grid', gap: 8, alignContent: 'start', borderTop: `4px solid ${color}` }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
      <b style={{ fontSize: 15 }}>{symbol}</b>
      <small style={{ color: '#7f8a85' }}>{err ? 'sem conexão' : age == null ? '…' : `ao vivo · ${p?.live?.status ?? ''}`}</small>
    </div>
    <div style={{ background: color, color: '#050506', borderRadius: 8, padding: '8px 10px', fontWeight: 800, fontSize: 20, textAlign: 'center' }}>
      {TITLE[p?.urgency ?? 'no_data']}{p?.sell_percent_now ? ` ${p.sell_percent_now}%` : ''}
    </div>
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 14 }}>
      <span>Preço <b>{price(p?.current_price_usd)}</b></span>
      <span style={{ color: (p?.change_from_reference ?? 0) >= 0 ? '#16c75f' : '#e3262b', fontWeight: 700 }}>{pct(p?.change_from_reference)}</span>
    </div>
    {p?.stop && <div style={{ fontSize: 13, color: p.stop.reached ? '#e3262b' : '#a3aca7' }}>Stop {price(p.stop.price_usd)} ({pct(p.stop.change_from_now)} daqui){p.stop.reached ? ' · ATINGIDO' : ''}</div>}
    {p?.take_profits?.slice(0, 2).map(t => <div key={t.label} style={{ fontSize: 13, color: '#a3aca7' }}>{t.label}: {price(t.price_usd)} ({pct(t.change_from_now)}) → vender {t.sell_percent}%</div>)}
    <div style={{ fontSize: 12, color: '#a3aca7', lineHeight: 1.35 }}>{p?.headline}{p?.reasons?.[0] ? ` · ${p.reasons[0]}` : ''}</div>
    <button onClick={() => openAxiom(address)} style={{ marginTop: 4, background: '#16c75f', color: '#03130a', border: 0, borderRadius: 8, padding: '8px', fontWeight: 700, cursor: 'pointer' }}>Abrir na Axiom</button>
  </div>
}

export function floatingSupported() {
  return !!pip()
}

export async function openFloating(chainId: string, address: string, symbol: string) {
  const api = pip()
  if (!api) return false
  current?.win.close()
  const win = await api.requestWindow({ width: 330, height: 300 })
  win.document.title = `Venda · ${symbol}`
  win.document.body.style.margin = '0'
  const host = win.document.createElement('div')
  win.document.body.appendChild(host)
  const root = createRoot(host)
  root.render(<FloatingView chainId={chainId} address={address} symbol={symbol} win={win} />)
  current = { win, root }
  win.addEventListener('pagehide', () => { root.unmount(); if (current?.win === win) current = null })
  return true
}

export function FloatingSellButton({ chainId, address, symbol, className }: { chainId: string; address: string; symbol: string; className?: string }) {
  if (!floatingSupported()) return null
  return <button type="button" className={className} title="Fica por cima de tudo, até quando você der Alt+Tab para a Axiom"
    onClick={() => void openFloating(chainId, address, symbol)}>Janela flutuante de venda</button>
}
