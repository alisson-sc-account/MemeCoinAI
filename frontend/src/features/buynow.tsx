import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../api/client'
import type { Opportunity } from '../api/types'
import { percent, price, relativeTime, shortAddress, usd } from '../lib/format'
import styles from './buynow.module.css'
import { FavoriteStar } from './favorites'
import { REFRESH_MS } from './signals'

const TIERS = [
  { key: 'priority_buy', label: 'Compra prioritária' },
  { key: 'possible_buy', label: 'Compra possível' },
  { key: 'watch', label: 'Observar' },
  { key: 'avoid', label: 'Evitar' },
] as const
const DEFAULT_TIERS = ['priority_buy', 'possible_buy', 'watch']
const SORTS = [
  { key: 'tier', label: 'Nível e score' },
  { key: 'score', label: 'Score' },
  { key: 'score_change', label: 'Mudança do score' },
  { key: 'liquidity_usd', label: 'Liquidez' },
  { key: 'volume_h24', label: 'Volume 24 h' },
  { key: 'price_change_h1', label: 'Variação 1 h' },
  { key: 'risk_score', label: 'Menor risco' },
]
const SAFETY: Record<string, string> = { danger: 'Perigo', caution: 'Atenção', clear: 'Sem alertas', unknown: 'Sem dados' }
const QUALITY: Record<string, string> = { ok: 'Dados completos', partial: 'Análise parcial', no_reliable_signal: 'Sem sinal confiável' }

const frac = (v: number | null | undefined) => v == null ? '—' : `${Math.round(v * 100)}%`
const delta = (v: number | null | undefined) => v == null || v === 0 ? '' : v > 0 ? styles.deltaUp : styles.deltaDown
const num = (v: number | null | undefined) => v == null ? '—' : new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1 }).format(v)

/** Hora local exata em que o sinal foi emitido; inclui a data se não for hoje. */
export function signalTime(iso: string | null | undefined, now = new Date()): string | null {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  const time = d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  return d.toDateString() === now.toDateString() ? time : `${d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })} às ${time}`
}

function CopyAddress({ address }: { address: string }) {
  const [done, setDone] = useState(false)
  return <button type="button" className={styles.addr} title={address} aria-label="Copiar endereço"
    onClick={e => { e.preventDefault(); e.stopPropagation(); void navigator.clipboard?.writeText(address).then(() => { setDone(true); window.setTimeout(() => setDone(false), 1200) }).catch(() => undefined) }}>
    {done ? 'Copiado' : shortAddress(address)} ⧉
  </button>
}

export function OpportunityCard({ o }: { o: Opportunity }) {
  const change = o.score_change
  const money = o.allocation ? new Intl.NumberFormat('pt-BR', { style: 'currency', currency: o.allocation.currency === 'USD' ? 'USD' : 'BRL' }).format(o.allocation.amount) : null
  const issuedAt = signalTime(o.signal_since)
  return <Link to={o.link} className={`${styles.card} ${styles[o.tier] ?? ''}`} aria-label={`${o.token.symbol ?? 'Token'}: ${o.tier_label}`}>
    <div className={styles.head}>
      <div className={styles.identity}>
        {o.token.image_url ? <img className={styles.logo} src={o.token.image_url} alt="" loading="lazy" /> : <span className={styles.logo} aria-hidden="true">{(o.token.symbol || '?').slice(0, 1).toUpperCase()}</span>}
        <div><div className={styles.symbol}>{o.token.symbol || o.token.name || 'Token sem nome'}</div><CopyAddress address={o.token.address} /></div>
      </div>
      <span className={styles.headRight}><span className={`${styles.tier} ${styles[o.tier] ?? ''}`}>{o.tier_label}</span><FavoriteStar chainId={o.token.chain_id} address={o.token.address} signalId={o.signal_id} symbol={o.token.symbol} /></span>
    </div>
    <div className={styles.priceRow}>
      <div className={styles.price}>{price(o.price_usd)}</div>
      <div className={styles.deltas}>
        <span className={`${styles.delta} ${delta(o.price_change_h1)}`}>1 h {percent(o.price_change_h1)}</span>
        <span className={`${styles.delta} ${delta(o.price_change_h24)}`}>24 h {percent(o.price_change_h24)}</span>
      </div>
    </div>
    <div className={styles.scoreBox}>
      <div className={styles.scoreLine}>
        <span>Score <b>{num(o.score)}</b>{change != null && change !== 0 && <span className={change > 0 ? styles.up : styles.down}> ({change > 0 ? '+' : ''}{num(change)})</span>}</span>
        <span>Risco <b>{num(o.risk_score)}</b></span>
      </div>
      <div className={styles.meter} aria-hidden="true"><i className={styles[o.tier] ?? ''} style={{ width: `${Math.min(100, Math.max(0, o.score ?? 0))}%` }} /></div>
      <div className={styles.scores}>
        <span>Confiança <b>{frac(o.confidence)}</b></span>
        <span>Cobertura <b>{frac(o.coverage)}</b></span>
      </div>
    </div>
    <div className={styles.metrics}>
      <div><small>Liquidez</small><b>{usd(o.liquidity_usd)}</b></div>
      <div><small>Volume 24 h</small><b>{usd(o.volume_h24)}</b></div>
    </div>
    {o.critical_blocks.length > 0 && <div className={styles.block}>Bloqueio: {o.critical_blocks.join('; ')}</div>}
    {money && o.allocation && <div className={styles.alloc}>Simulação: {num(o.allocation.percent_of_balance)}% do saldo ({money})</div>}
    {o.reasons_for.length > 0 && <ul className={styles.list}>{o.reasons_for.slice(0, 2).map(r => <li key={r}>{r}</li>)}</ul>}
    {o.reasons_against.length > 0 && <div className={styles.against}>Contra: {o.reasons_against[0]}</div>}
    <div className={`${styles.safety} ${styles[`safety_${o.security_verdict}`] ?? ''}`}>Segurança: <b>{SAFETY[o.security_verdict] ?? 'Sem dados'}</b></div>
    <div className={styles.issued}>{issuedAt ? <>Sinal emitido: <b>{issuedAt}</b></> : 'Sem sinal emitido'}</div>
    <div className={styles.meta}>{QUALITY[o.decision_quality]} · dados {o.freshness.status === 'fresh' ? 'atualizados' : o.freshness.status === 'delayed' ? 'atrasados' : o.freshness.status === 'stale' ? 'desatualizados' : 'ausentes'} ({relativeTime(o.freshness.observed_at)})</div>
  </Link>
}

export function BuyNowPage() {
  const [sp, setSp] = useSearchParams()
  const selected = sp.getAll('tier').length ? sp.getAll('tier') : DEFAULT_TIERS
  const sort = sp.get('sort') ?? 'tier'
  const minLiq = sp.get('min_liquidity') ?? ''
  const query = new URLSearchParams()
  selected.forEach(t => query.append('tier', t))
  query.set('sort', sort)
  query.set('page_size', '60')
  if (minLiq) query.set('min_liquidity', minLiq)
  const q = useQuery({ queryKey: ['opportunities', query.toString()], queryFn: () => apiClient.opportunities(query.toString()), refetchInterval: REFRESH_MS, refetchIntervalInBackground: false })
  const update = (fn: (p: URLSearchParams) => void) => { const next = new URLSearchParams(sp); fn(next); setSp(next, { replace: true }) }
  const toggleTier = (key: string) => update(p => {
    const set = new Set(selected)
    if (set.has(key)) set.delete(key); else set.add(key)
    p.delete('tier')
    ;(set.size ? [...set] : DEFAULT_TIERS).forEach(t => p.append('tier', t))
  })
  return <>
    <header>
      <h1 className={styles.title}>Compre agora</h1>
      <p className={styles.meta}>As melhores moedas para comprar agora, da melhor para a pior{q.data ? ` · atualizado ${relativeTime(q.data.generated_at)}` : ''}. Não é garantia de lucro.</p>
    </header>
    <div className={styles.toolbar} role="group" aria-label="Filtrar por nível">
      {TIERS.map(t => <button key={t.key} type="button" className={styles.chip} aria-pressed={selected.includes(t.key)} onClick={() => toggleTier(t.key)}>
        <i className={`${styles.dot} ${styles[t.key] ?? ''}`} aria-hidden="true" />{t.label}<b>{q.data?.counts?.[t.key] ?? '·'}</b>
      </button>)}
      <label className={styles.meta}>Ordenar <select className={styles.select} value={sort} onChange={e => update(p => p.set('sort', e.target.value))}>
        {SORTS.map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
      </select></label>
      <label className={styles.meta}>Liquidez mín. <select className={styles.select} value={minLiq} onChange={e => update(p => { if (e.target.value) p.set('min_liquidity', e.target.value); else p.delete('min_liquidity') })}>
        <option value="">qualquer</option><option value="10000">US$ 10 mil</option><option value="50000">US$ 50 mil</option><option value="200000">US$ 200 mil</option>
      </select></label>
      <Link to="/tokens" className={styles.meta}>Explorar todos os tokens →</Link>
    </div>
    {q.isPending ? <p className={styles.meta}>Carregando ranking…</p>
      : q.isError ? <p role="alert" className={styles.block}>{(q.error as Error).message}</p>
      : q.data.items.length === 0 ? <p className={styles.meta}>Nenhum token nos níveis selecionados. {q.data.counts.avoid ? `${q.data.counts.avoid} token(s) estão em "Evitar".` : 'O coletor adiciona tokens enquanto está rodando.'}</p>
      : <div className={styles.grid}>{q.data.items.map(o => <OpportunityCard key={o.token.address} o={o} />)}</div>}
    {q.data && <p className={styles.meta}>{q.data.disclaimer}</p>}
  </>
}

export function WorkerStatusCard() {
  const q = useQuery({ queryKey: ['health'], queryFn: apiClient.health, refetchInterval: REFRESH_MS, refetchIntervalInBackground: false })
  if (q.isPending) return <p className={styles.meta}>Verificando…</p>
  if (q.isError) return <p role="alert" className={styles.workerBad}>API desconectada: {(q.error as Error).message}</p>
  const w = q.data.worker
  const slowCycle = w.last_cycle_duration_seconds != null && w.last_cycle_duration_seconds > w.expected_interval_seconds
  const cycleDuration = w.last_cycle_duration_seconds == null ? '' : new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1 }).format(w.last_cycle_duration_seconds)
  const label = w.status === 'running' ? 'Coletor rodando' : w.status === 'stopped' ? 'Coletor parado' : 'Coletor sem execuções'
  return <div>
    <p className={w.status === 'running' ? styles.workerOk : styles.workerBad}>{label}</p>
    <p className={styles.meta}>Última coleta: {w.last_cycle_at ? relativeTime(w.last_cycle_at) : 'nunca'} · esperado a cada {w.expected_interval_seconds} s · banco {q.data.database === 'ok' ? 'ok' : 'com erro'} · versão {q.data.version}</p>
    {slowCycle && <p className={styles.meta}>Coleta levando {cycleDuration} s (intervalo configurado: {w.expected_interval_seconds} s). Reduza MAX_TRACKED_TOKENS no backend/.env se quiser ciclos mais curtos.</p>}
    {w.status !== 'running' && <p className={styles.meta}>Os dados exibidos envelhecem até o coletor voltar. Inicie com start.bat (ou run-local.ps1).</p>}
  </div>
}

/** Todos os agentes por categoria, com o estado real de cada um. */
export function AgentsPanel() {
  const q = useQuery({ queryKey: ['agents'], queryFn: apiClient.agents, refetchInterval: 15_000, refetchIntervalInBackground: false })
  if (q.isPending) return <p className={styles.meta}>Carregando agentes…</p>
  if (q.isError) return <p role="alert" className={styles.block}>{(q.error as Error).message}</p>
  const running = q.data.filter(a => a.status === 'running').length
  const categories = [...new Set(q.data.map(a => a.category))]
  return <>
    <p className={styles.meta}>{running} de {q.data.length} agentes rodando. Cada um usa só a própria fonte, e um lento não atrasa os outros.</p>
    {categories.map(c => <div key={c} className={styles.agentGroup}>
      <h3>{c}</h3>
      {q.data.filter(a => a.category === c).map(a => <div key={a.name} className={styles.agent}>
        <i className={`${styles.dot} ${a.status === 'running' && !a.last_error ? styles.priority_buy : a.status === 'stopped' || a.last_error ? styles.avoid : ''}`} aria-hidden="true" />
        <span><b>{a.label}</b><span className={styles.meta}> · {a.source}</span>{a.last_error && <span className={styles.against}> · {a.last_error}</span>}</span>
        <span className={styles.meta}>{a.status === 'unknown' ? 'ainda não rodou' : a.status === 'stopped' ? `parado ${relativeTime(a.last_tick_at)}` : relativeTime(a.last_tick_at)}</span>
      </div>)}
    </div>)}
  </>
}

const CLASS_STYLE: Record<string, string> = { A: styles.clsA, B: styles.clsB, C: styles.clsC, D: styles.clsD }

export function SourcesRegistry() {
  const q = useQuery({ queryKey: ['registry'], queryFn: apiClient.registry, staleTime: 5 * 60_000 })
  if (q.isPending) return <p className={styles.meta}>Carregando fontes…</p>
  if (q.isError) return <p role="alert" className={styles.block}>{(q.error as Error).message}</p>
  const active = q.data.filter(s => s.enabled).length
  return <>
    <p className={styles.meta}>{active} de {q.data.length} fontes ativas. Só fontes da classe A ficam ligadas: custo zero, sem chave. As demais estão registradas para referência e desligadas.</p>
    <div className={styles.tableWrap}><table className={styles.table}>
      <thead><tr><th>Fonte</th><th>Classe</th><th>Estado</th><th>Verificação</th><th>Limites</th></tr></thead>
      <tbody>{q.data.map(s => <tr key={s.key}>
        <td><b>{s.name}</b><div className={styles.meta}>{s.role}</div></td>
        <td><span className={`${styles.cls} ${CLASS_STYLE[s.access_class] ?? ''}`}>{s.access_class}</span><div className={styles.meta}>{s.access_label}</div></td>
        <td>{s.enabled ? 'Ligada' : 'Desligada'}<div className={styles.meta}>{s.integration}</div></td>
        <td>{s.verified_on ?? '—'}<div className={styles.meta}>{s.verification}</div></td>
        <td className={styles.meta}>{s.limits}</td>
      </tr>)}</tbody>
    </table></div>
  </>
}
