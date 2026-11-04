import { useEffect, useState } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { apiClient } from '../api/client'
import type { ExitPlan } from '../api/types'
import { openAxiom } from '../lib/axiom'

/** Janela de venda que fica por cima de tudo (Alt+Tab para a Axiom continua mostrando). Picture-in-Picture de documento. */
const POLL_MS = 1500
const COLORS = { sell_now: '#f43f5e', reduce: '#fb923c', hold: '#10b981', no_data: '#a1a1aa' } as Record<string, string>
const TITLE = { sell_now: 'Vender agora', reduce: 'Reduzir', hold: 'Segurar', no_data: 'Sem dados' } as Record<string, string>

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
  const age = at ? Math.round((Date.now() - at) / 1000) : null
  const u = p?.urgency ?? 'no_data'
  const color = COLORS[u]
  const chg = p?.change_from_reference
  const up = (chg ?? 0) >= 0
  const stop = p?.stop?.price_usd, tgt = p?.take_profits?.[0]?.price_usd, cur = p?.current_price_usd
  const pos = stop && tgt && cur && tgt > stop ? Math.max(0, Math.min(1, (cur - stop) / (tgt - stop))) : null
  const muted = '#a1a1aa', faint = '#71717a', line = '#232327'
  const row = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 12.5 } as const
  return <div style={{ fontFamily: 'Inter,"Segoe UI",system-ui,sans-serif', color: '#fafafa', background: '#09090b', minHeight: '100vh', padding: 14, boxSizing: 'border-box', display: 'flex', flexDirection: 'column', gap: 12 }}>
    <div style={row}>
      <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <img src="/brand/mark.png" alt="" width={18} height={18} />
        <b style={{ fontSize: 14, letterSpacing: '-.01em' }}>{symbol}</b>
      </span>
      <span style={{ display: 'flex', alignItems: 'center', gap: 6, color: err ? '#f43f5e' : faint, fontSize: 11 }}>
        <i style={{ width: 6, height: 6, borderRadius: 9, background: err ? '#f43f5e' : p?.live?.status === 'live' ? '#10b981' : '#facc15', display: 'inline-block' }} />
        {err ? 'sem conexão' : age == null ? 'conectando' : p?.live?.status === 'live' ? 'ao vivo' : 'atrasado'}
      </span>
    </div>
    <div style={{ border: `1px solid ${color}55`, background: `${color}14`, borderRadius: 12, padding: '12px 14px' }}>
      <div style={{ fontSize: 11, color: muted, textTransform: 'uppercase', letterSpacing: '.08em', fontWeight: 600 }}>Agora</div>
      <div style={{ fontSize: 22, fontWeight: 700, color, letterSpacing: '-.02em', marginTop: 2 }}>
        {TITLE[u]}{p?.sell_percent_now ? ` ${p.sell_percent_now}%` : ''}
      </div>
      <div style={{ fontSize: 12, color: muted, marginTop: 4, lineHeight: 1.4 }}>{p?.reasons?.[0] ?? p?.headline ?? 'Carregando o plano…'}</div>
    </div>
    <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
      <span style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-.02em', fontVariantNumeric: 'tabular-nums' }}>{price(cur)}</span>
      <span style={{ fontSize: 14, fontWeight: 600, color: up ? '#10b981' : '#f43f5e', fontVariantNumeric: 'tabular-nums' }}>{pct(chg)}</span>
    </div>
    {pos != null && <div>
      <div style={{ height: 6, borderRadius: 6, background: 'linear-gradient(90deg,#f43f5e33,#27272a 40%,#10b98133)', position: 'relative' }}>
        <i style={{ position: 'absolute', left: `calc(${pos * 100}% - 5px)`, top: -2, width: 10, height: 10, borderRadius: 10, background: '#fafafa', boxShadow: '0 0 0 3px #09090b' }} />
      </div>
      <div style={{ ...row, marginTop: 6, color: faint, fontSize: 11 }}><span>Stop {price(stop)}</span><span>Alvo {price(tgt)}</span></div>
    </div>}
    <div style={{ borderTop: `1px solid ${line}`, paddingTop: 10, display: 'grid', gap: 6 }}>
      {p?.stop && <div style={row}><span style={{ color: muted }}>Stop{p.stop.reached ? ' · atingido' : ''}</span><span style={{ color: p.stop.reached ? '#f43f5e' : '#fafafa', fontVariantNumeric: 'tabular-nums' }}>{pct(p.stop.change_from_now)}</span></div>}
      {p?.take_profits?.slice(0, 2).map(t => <div key={t.label} style={row}><span style={{ color: muted }}>{t.label} · vender {t.sell_percent}%</span><span style={{ fontVariantNumeric: 'tabular-nums' }}>{pct(t.change_from_now)}</span></div>)}
    </div>
    <button onClick={() => openAxiom(address)} style={{ marginTop: 'auto', background: '#fafafa', color: '#09090b', border: 0, borderRadius: 10, padding: '10px', fontWeight: 600, fontSize: 13, cursor: 'pointer', fontFamily: 'inherit' }}>Abrir na Axiom ↗</button>
  </div>
}

export function floatingSupported() {
  return !!pip()
}

function popupFallback(chainId: string, address: string, symbol: string) {
  // Plano B: janela pequena comum (não fica por cima sozinha, mas atualiza ao vivo).
  const url = `/flutuante/${encodeURIComponent(chainId)}/${encodeURIComponent(address)}?s=${encodeURIComponent(symbol)}`
  return !!window.open(url, 'mcai-venda', 'popup,width=340,height=420')
}

export async function openFloating(chainId: string, address: string, symbol: string) {
  const api = pip()
  if (!api) return popupFallback(chainId, address, symbol)
  let win: Window
  try {
    const pending = api.requestWindow({ width: 320, height: 380 })  // pedido antes de qualquer await: precisa do clique do usuário
    current?.win.close()
    win = await pending
  } catch {
    return popupFallback(chainId, address, symbol)
  }
  win.document.title = `Venda · ${symbol}`
  win.document.body.style.margin = '0'
  win.document.body.style.background = '#09090b'
  const host = win.document.createElement('div')
  win.document.body.appendChild(host)
  const root = createRoot(host)
  root.render(<FloatingView chainId={chainId} address={address} symbol={symbol} win={win} />)
  current = { win, root }
  win.addEventListener('pagehide', () => { root.unmount(); if (current?.win === win) current = null })
  return true
}

/** Página da janela comum (plano B): /flutuante/:chainId/:address */
export function FloatingPage({ chainId, address, symbol }: { chainId: string; address: string; symbol: string }) {
  useEffect(() => { document.title = `Venda · ${symbol}` }, [symbol])
  return <FloatingView chainId={chainId} address={address} symbol={symbol} win={window} />
}

export function FloatingSellButton({ chainId, address, symbol, className }: { chainId: string; address: string; symbol: string; className?: string }) {
  return <button type="button" className={className} title="Fica por cima de tudo, até quando você der Alt+Tab para a Axiom"
    onClick={() => void openFloating(chainId, address, symbol)}>Janela flutuante de venda</button>
}
