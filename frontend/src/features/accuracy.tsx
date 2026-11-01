import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../api/client'
import type { AccuracyItem, AccuracyPage as AccuracyData } from '../api/types'
import { dateTime, price, shortAddress } from '../lib/format'
import { FavoriteStar } from './favorites'
import styles from './accuracy.module.css'
import { REFRESH_MS } from './signals'

const HORIZONS = [{ key: '15m', label: '15 min' }, { key: '1h', label: '1 hora' }, { key: '6h', label: '6 horas' }] as const
const RESULTS = [
  { key: '', label: 'Todos' }, { key: 'hit', label: 'Acertos' }, { key: 'miss', label: 'Erros' },
  { key: 'pending', label: 'Pendentes' }, { key: 'unevaluable', label: 'Inavaliáveis' },
] as const
const TIERS = [
  { key: 'priority_buy', label: 'Compra prioritária', note: 'acerta se subiu' },
  { key: 'possible_buy', label: 'Compra possível', note: 'acerta se subiu' },
  { key: 'watch', label: 'Observar', note: 'referência: subiu sem sinal' },
  { key: 'sell', label: 'Venda', note: 'acerta se caiu' },
] as const
const STATUS_LABEL: Record<string, string> = { hit: 'Acertou', miss: 'Errou', pending: 'Pendente', unevaluable: 'Inavaliável' }

const pct = (v: number | null | undefined) => v == null ? '—' : `${v > 0 ? '+' : ''}${new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1 }).format(v * 100)}%`
/** Tempo até uma data futura: "em 47 min", "em 2 h 5 min". */
function untilText(iso: string): string {
  const secs = Math.max(0, Math.round((new Date(iso).getTime() - Date.now()) / 1000))
  if (secs < 60) return secs ? `em ${secs} s` : 'agora'
  const h = Math.floor(secs / 3600), m = Math.floor((secs % 3600) / 60)
  return h ? `em ${h} h ${m} min` : `em ${m} min`
}
const rate = (v: number | null | undefined) => v == null ? '—' : `${Math.round(v * 100)}%`

function Counts({ title, c }: { title: string; c: AccuracyData['summary'][string][string] }) {
  return <div className={styles.box}>
    <h2>{title}</h2>
    <div><b className={styles.hit}>{c.hits} acertos</b> · <b className={styles.miss}>{c.misses} erros</b> · taxa {rate(c.hit_rate)}</div>
    <span className={styles.muted}>{c.pending} pendentes · {c.unevaluable} inavaliáveis</span>
  </div>
}

function Row({ item, horizon }: { item: AccuracyItem; horizon: string }) {
  const r = item.results[horizon]
  return <Link to={item.link} className={styles.row}>
    <span className={`${styles.badge} ${styles[r.status] ?? ''}`}>{STATUS_LABEL[r.status]}</span>
    <span>
      <b>{item.token.symbol || shortAddress(item.token.address)}</b> · {item.tier_label} · {item.prediction}
      <span className={styles.muted}> · sinal em {dateTime(item.created_at)} a {price(item.reference_price_usd)}</span>
    </span>
    <span className={styles.muted}>
      {r.status === 'hit' || r.status === 'miss'
        ? <>no fim: <b className={(r.end_return ?? 0) >= 0 ? styles.up : styles.down}>{pct(r.end_return)}</b> · máx {pct(r.max_return)} · mín {pct(r.min_return)}</>
        : r.status === 'pending' ? `resolve ${untilText(r.resolves_at)}` : 'sem coleta contínua na janela'}
    </span>
    <FavoriteStar chainId={item.token.chain_id} address={item.token.address} signalId={item.signal_id} symbol={item.token.symbol} />
  </Link>
}

export function AccuracyPage() {
  const [sp, setSp] = useSearchParams()
  const horizon = sp.get('horizon') ?? '1h'
  const result = sp.get('result') ?? ''
  const tier = sp.get('tier') ?? ''
  const query = new URLSearchParams({ horizon, page_size: '100' })
  if (result) query.set('result', result)
  if (tier) query.set('tier', tier)
  const q = useQuery({ queryKey: ['accuracy', query.toString()], queryFn: () => apiClient.accuracy(query.toString()), refetchInterval: REFRESH_MS, refetchIntervalInBackground: false })
  const set = (key: string, value: string) => { const next = new URLSearchParams(sp); if (value) next.set(key, value); else next.delete(key); setSp(next, { replace: true }) }
  const s = q.data?.summary[horizon]
  return <>
    <header>
      <h1>Acertos</h1>
      <p className={styles.muted}>Quantas previsões de subida (sinal COMPRAR) e de queda (sinal VENDER) acertaram, conferidas pelo preço depois de cada horizonte.</p>
    </header>
    <div className={styles.toolbar} role="group" aria-label="Horizonte">
      {HORIZONS.map(h => <button key={h.key} type="button" className={styles.chip} aria-pressed={horizon === h.key} onClick={() => set('horizon', h.key === '1h' ? '' : h.key)}>{h.label}</button>)}
      <span className={styles.muted}>|</span>
    </div>
    <div className={styles.toolbar} role="group" aria-label="Nível">
      <button type="button" className={styles.chip} aria-pressed={tier === ''} onClick={() => set('tier', '')}>Todos os níveis</button>
      {TIERS.map(t => <button key={t.key} type="button" className={styles.chip} aria-pressed={tier === t.key} onClick={() => set('tier', t.key)}>{t.label}</button>)}
    </div>
    {q.isPending ? <p className={styles.muted}>Carregando…</p>
      : q.isError ? <p role="alert" className={styles.miss}>{(q.error as Error).message}</p>
      : s && <>
        <div className={styles.kpis}>
          <div className={styles.kpi}><small>Acertou</small><b className={styles.hit}>{s.all.hits}</b></div>
          <div className={styles.kpi}><small>Errou</small><b className={styles.miss}>{s.all.misses}</b></div>
          <div className={styles.kpi}><small>Taxa de acerto</small><b>{rate(s.all.hit_rate)}</b><span className={styles.muted}>{s.all.evaluated} avaliadas</span></div>
          <div className={styles.kpi}><small>Aguardando o horizonte</small><b>{s.all.pending}</b><span className={styles.muted}>{s.all.unevaluable} inavaliáveis</span></div>
        </div>
        <div className={styles.box}>
          <h2>Qual nível acerta mais ({HORIZONS.find(h => h.key === horizon)?.label})</h2>
          <div className={styles.tableWrap}><table className={styles.table}>
            <thead><tr><th>Nível</th><th>Acertos</th><th>Erros</th><th>Taxa</th><th>Avaliadas</th><th>Regra</th></tr></thead>
            <tbody>{TIERS.map(t => { const c = s[t.key]; return c && <tr key={t.key} aria-selected={tier === t.key}>
              <td><button type="button" className={styles.linkButton} onClick={() => set('tier', t.key)}>{t.label}</button></td>
              <td className={styles.hit}>{c.hits}</td><td className={styles.miss}>{c.misses}</td>
              <td><b>{rate(c.hit_rate)}</b></td><td>{c.evaluated}</td><td className={styles.muted}>{t.note}</td>
            </tr> })}</tbody>
          </table></div>
          <span className={styles.muted}>Se um nível de compra acerta menos que "Observar", o sinal está pior do que simplesmente esperar. Amostras pequenas (poucas avaliadas) ainda não dizem muito.</span>
        </div>
        <div className={styles.split}>
          <Counts title="Previsões de subida (COMPRAR)" c={s.buy} />
          <Counts title="Previsões de queda (VENDER)" c={s.sell} />
        </div>
        <div className={styles.toolbar} role="group" aria-label="Resultado">
          {RESULTS.map(r => <button key={r.key} type="button" className={styles.chip} aria-pressed={result === r.key} onClick={() => set('result', r.key)}>{r.label}</button>)}
        </div>
        {q.data.items.length === 0
          ? <p className={styles.muted}>Nenhuma previsão com esse filtro ainda. Sinais de compra e venda aparecem aqui assim que o coletor os emite; o resultado sai depois do horizonte.</p>
          : <div className={styles.list}>{q.data.items.map(i => <Row key={i.signal_id} item={i} horizon={horizon} />)}</div>}
        <p className={styles.muted}>{q.data.definition} Regra {q.data.rules_version}. Últimos 14 dias.</p>
      </>}
  </>
}
