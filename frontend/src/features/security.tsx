import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../api/client'
import type { Security } from '../api/types'
import { relativeTime, shortAddress } from '../lib/format'
import { packBubbles } from './bubbles'
import styles from './security.module.css'

const STATUS_MARK: Record<string, string> = { ok: '✓', warn: '!', danger: '✕', unknown: '?' }
const VERDICT_TEXT: Record<string, string> = {
  danger: 'Não compre: há sinais de golpe.',
  caution: 'Cuidado: veja os pontos abaixo.',
  clear: 'Nada encontrado no que deu para verificar. Isso não garante que é segura.',
  unknown: 'Ainda não deu para verificar esta moeda.',
}

type Holder = Security['holders'][number]

function holderKind(h: Holder): { cls: string; label: string } {
  if (h.insider) return { cls: styles.insider, label: 'insider' }
  if (h.cluster) return { cls: styles.cluster, label: 'mesma origem' }
  if (h.fresh) return { cls: styles.fresh, label: 'carteira nova' }
  if (h.fresh === false) return { cls: styles.old, label: 'carteira antiga' }
  return { cls: styles.unknownWallet, label: 'idade desconhecida' }
}

/** Mapa de carteiras: bolha maior = mais moedas; linha liga carteiras com a mesma origem do dinheiro. */
function BubbleMap({ holders }: { holders: Holder[] }) {
  const layout = useMemo(() => packBubbles(holders.map(h => h.pct)), [holders])
  const linked = holders.map((h, i) => ({ h, i })).filter(x => x.h.cluster)
  return <figure className={styles.map}>
    <svg viewBox={`0 0 ${layout.width} ${layout.height}`} role="img" aria-label={`Mapa das ${holders.length} maiores carteiras`}>
      {linked.slice(1).map(({ i }) => <line key={i} x1={layout.circles[linked[0].i].x} y1={layout.circles[linked[0].i].y} x2={layout.circles[i].x} y2={layout.circles[i].y} className={styles.link} />)}
      {holders.map((h, i) => {
        const c = layout.circles[i]
        const kind = holderKind(h)
        return <g key={h.owner}>
          <circle cx={c.x} cy={c.y} r={c.r} className={kind.cls}><title>{`${shortAddress(h.owner)}: ${h.pct.toFixed(2)}% · ${kind.label}${h.age_hours != null ? ` · ${h.age_hours.toFixed(0)} h` : ''}`}</title></circle>
          {c.r >= 16 && <text x={c.x} y={c.y + 4} textAnchor="middle" className={styles.bubbleText}>{h.pct.toFixed(1)}%</text>}
        </g>
      })}
    </svg>
    <figcaption className={styles.legend}>
      <span><i className={styles.insider} />insider</span>
      <span><i className={styles.cluster} />mesma origem</span>
      <span><i className={styles.fresh} />carteira nova</span>
      <span><i className={styles.old} />antiga</span>
      <span><i className={styles.unknownWallet} />idade desconhecida</span>
    </figcaption>
  </figure>
}

export function SecurityPanel({ chainId, address }: { chainId: string; address: string }) {
  const q = useQuery({ queryKey: ['security', chainId, address], queryFn: () => apiClient.security(chainId, address), refetchInterval: 10_000, refetchIntervalInBackground: false })
  if (q.isPending) return <section className={styles.panel} aria-label="Segurança"><p className={styles.meta}>Carregando segurança…</p></section>
  if (q.isError) return <section className={styles.panel} aria-label="Segurança"><p role="alert" className={styles.dangerText}>{(q.error as Error).message}</p></section>
  const s = q.data
  return <section className={`${styles.panel} ${styles[s.verdict] ?? ''}`} aria-label="Segurança">
    <div className={styles.top}>
      <div>
        <small className={styles.meta}>Segurança</small>
        <p className={styles.verdict}>{s.label}</p>
        <p className={styles.why}>{s.rugged_at ? `Golpe detectado: ${s.rug_reason ?? 'queda brusca de preço e liquidez'}.` : VERDICT_TEXT[s.verdict]}</p>
      </div>
      <small className={styles.meta}>{s.checked_at ? `Verificado ${relativeTime(s.checked_at)}` : s.service_running ? 'Verificando…' : 'Verificação de segurança parada: rode start.bat'}</small>
    </div>
    <div className={styles.grid}>
      {s.checks.length > 0 && <ul className={styles.checks}>
        {s.checks.map(c => <li key={c.key} className={styles[`s_${c.status}`]}>
          <span className={styles.mark} aria-hidden="true">{STATUS_MARK[c.status]}</span>
          <span><b>{c.label}</b> {c.detail}</span>
        </li>)}
      </ul>}
      {s.holders.length > 0 && <BubbleMap holders={s.holders} />}
    </div>
    <details>
      <summary className={styles.meta}>O que esta verificação não consegue ver</summary>
      <ul className={styles.limits}>{s.limitations.map(l => <li key={l}>{l}</li>)}</ul>
    </details>
  </section>
}
