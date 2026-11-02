import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../api/client'
import type { ExitPlan } from '../api/types'
import { ageText, price } from '../lib/format'
import styles from './signals.module.css'

export const SELL_PLAN_REFRESH_MS = 1_000

const URGENCY_CLASS: Record<string, string> = { sell_now: styles.sell, reduce: styles.avoid, hold: styles.buy, no_data: '' }

const pct = (v: number | null | undefined) => v == null ? '—' : `${v > 0 ? '+' : ''}${new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 0 }).format(v * 100)}%`

/** Moeda aberta: consulta a cada 1 s. A pista rápida do backend lê a blockchain no mesmo ritmo. */
export function nextPollMs(_p?: ExitPlan): number {
  return SELL_PLAN_REFRESH_MS
}

const LIVE_LABEL: Record<string, string> = { live: 'AO VIVO', waiting: 'CONECTANDO', unavailable: 'SEM AO VIVO', off: 'AO VIVO DESLIGADO' }

/** A frase principal: o que fazer agora. */
function whatToDoNow(urgency: string, percent: number | null | undefined, reasons: string[] = []): { title: string; detail: string } {
  if (urgency === 'no_data') return { title: 'Sem preço agora', detail: 'Ainda não há preço atual desta moeda.' }
  if (urgency === 'hold' || !percent) return { title: 'Segure', detail: 'Sem motivo para vender agora.' }
  if (percent >= 100 && reasons.some(r => r.includes('golpe'))) return { title: 'Venda tudo agora', detail: 'Golpe: tiraram o dinheiro da pool desta moeda.' }
  if (percent >= 100) return { title: 'Venda tudo agora', detail: reasons[0] ?? 'Sinais fortes de queda.' }
  return { title: `Venda ${percent}% agora`, detail: reasons[0] ?? `Guarde o resto.` }
}

function useNow(ms = 1000) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => { const id = window.setInterval(() => setNow(Date.now()), ms); return () => window.clearInterval(id) }, [ms])
  return now
}

/** Painel "Quando vender": consulta o plano a cada 1 s e mostra a idade do preço. */
export function SellPlanPanel({ chainId, address, plan, pending, error, sharedQuery = false }: {
  chainId: string
  address: string
  plan?: ExitPlan
  pending?: boolean
  error?: unknown
  updatedAt?: number
  sharedQuery?: boolean
}) {
  const q = useQuery({
    queryKey: ['exit-plan', chainId, address], queryFn: () => apiClient.exitPlan(chainId, address),
    refetchInterval: nextPollMs(), refetchIntervalInBackground: false, enabled: !sharedQuery,
  })
  const now = useNow()
  const p = sharedQuery ? plan : q.data
  const isPending = sharedQuery ? pending : q.isPending
  const queryError = sharedQuery ? error : q.error
  if (!p && isPending) return <section className={styles.hero} aria-label="Quando vender"><p className={styles.meta}>Montando o plano de venda…</p></section>
  if (!p && queryError) return <section className={styles.hero} aria-label="Quando vender"><p className={styles.error} role="alert">{(queryError as Error).message}</p></section>
  if (!p) return <section className={styles.hero} aria-label="Quando vender"><p className={styles.meta}>Plano de venda indisponível.</p></section>
  const stale = p.freshness.status === 'stale' || p.freshness.status === 'no_data'
  const todo = whatToDoNow(p.urgency, p.sell_percent_now, p.reasons)
  const live = p.live
  return <section className={`${styles.hero} ${URGENCY_CLASS[p.urgency] ?? ''}`} aria-label="Quando vender">
    <div className={styles.liveRow}>
      <h2 className={styles.panelTag}>Quando vender</h2>
      <span className={`${styles.liveBadge} ${live.status === 'live' ? styles.liveOn : ''}`}>{LIVE_LABEL[live.status]}</span>
    </div>
    <p className={styles.call}>{todo.title}</p>
    <p className={styles.callWhy}>{todo.detail}</p>
    {p.flow && <p className={styles.flowLine}>Últimos 30 s: <b className={styles.up}>{p.flow.buys} compras</b> · <b className={styles.down}>{p.flow.sells} vendas</b></p>}
    <p className={stale ? styles.error : styles.meta} aria-live="polite">
      Atualizado {ageText(p.freshness.observed_at, now)}{live.status === 'live' ? ` · preço a cada ${live.interval_seconds} s` : ` · ${live.note}`} · preço {price(p.current_price_usd)}
    </p>

    <details>
      <summary className={styles.meta}>Ver plano de saída</summary>
      {p.reference_price_usd != null && p.stop && <ol className={styles.steps}>
        {p.take_profits.map(t => <li key={t.label} className={t.reached ? styles.stepDone : undefined}>
          Se o preço <b className={styles.up}>subir</b> até <b>{price(t.price_usd)}</b> ({pct(t.change_from_now)} a partir de agora): venda <b>{t.sell_percent}%</b> do que você tinha{t.reached ? ' — já chegou' : ''}.
        </li>)}
        <li className={p.stop.reached ? styles.stepAlert : undefined}>
          Se o preço <b className={styles.down}>cair</b> até <b>{price(p.stop.price_usd)}</b> ({pct(p.stop.change_from_now)} a partir de agora): venda <b>tudo</b>{p.stop.reached ? ' — já chegou' : ''}.
        </li>
      </ol>}
      <p className={styles.meta}>{p.reference_price_usd != null && `As contas partem de ${price(p.reference_price_usd)}: ${p.reference_kind}. `}{p.disclaimer}</p>
    </details>
  </section>
}
