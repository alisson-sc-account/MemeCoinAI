import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../api/client'
import type { Security } from '../api/types'
import { relativeTime, shortAddress } from '../lib/format'
import styles from './security.module.css'

const STATUS_MARK: Record<string, string> = { ok: '✓', warn: '!', danger: '✕', unknown: '?' }
const VERDICT_TEXT: Record<string, string> = {
  danger: 'Não compre: há sinais de golpe.',
  caution: 'Cuidado: há pontos de atenção.',
  clear: 'Nada encontrado no que deu para verificar. Não garante que é segura.',
  unknown: 'Ainda não deu para verificar.',
}

function walletKind(h: Security['holders'][number]): string {
  if (h.insider) return 'insider'
  if (h.cluster) return 'mesma origem'
  if (h.fresh) return `nova, ${(h.age_hours ?? 0).toFixed(0)} h`
  if (h.fresh === false) return 'antiga'
  return 'idade desconhecida'
}

/** Veredito em uma linha. O detalhe fica guardado para não poluir a tela da moeda. */
export function SecurityPanel({ chainId, address }: { chainId: string; address: string }) {
  const q = useQuery({ queryKey: ['security', chainId, address], queryFn: () => apiClient.security(chainId, address), refetchInterval: 10_000, refetchIntervalInBackground: false })
  if (q.isPending) return <section className={styles.panel} aria-label="Segurança"><p className={styles.meta}>Carregando segurança…</p></section>
  if (q.isError) return <section className={styles.panel} aria-label="Segurança"><p role="alert" className={styles.dangerText}>{(q.error as Error).message}</p></section>
  const s = q.data
  const alerts = s.checks.filter(c => c.status === 'danger' || c.status === 'warn')
  return <section className={`${styles.panel} ${styles[s.verdict] ?? ''}`} aria-label="Segurança">
    <div className={styles.top}>
      <p className={styles.line}><b className={styles.verdict}>{s.label}</b> <span>{s.rugged_at ? `Golpe detectado: ${s.rug_reason ?? 'queda brusca de preço e liquidez'}.` : VERDICT_TEXT[s.verdict]}</span></p>
      <small className={styles.meta}>{s.checked_at ? `Verificado ${relativeTime(s.checked_at)}` : s.service_running ? 'Verificando…' : 'Verificação parada'}</small>
    </div>
    {alerts.length > 0 && <ul className={styles.alerts}>{alerts.map(c => <li key={c.key} className={styles[`s_${c.status}`]}>{c.detail}</li>)}</ul>}
    <details>
      <summary className={styles.meta}>Ver todas as verificações e carteiras</summary>
      <ul className={styles.checks}>
        {s.checks.map(c => <li key={c.key} className={styles[`s_${c.status}`]}>
          <span className={styles.mark} aria-hidden="true">{STATUS_MARK[c.status]}</span>
          <span><b>{c.label}</b> {c.detail}</span>
        </li>)}
      </ul>
      {s.holders.length > 0 && <table className={styles.wallets}>
        <thead><tr><th>Carteira</th><th>Moedas</th><th>Tipo</th></tr></thead>
        <tbody>{s.holders.slice(0, 10).map(h => <tr key={h.owner}><td className="mono">{shortAddress(h.owner)}</td><td>{h.pct.toFixed(1)}%</td><td>{walletKind(h)}</td></tr>)}</tbody>
      </table>}
      <ul className={styles.limits}>{s.limitations.map(l => <li key={l}>{l}</li>)}</ul>
    </details>
  </section>
}
