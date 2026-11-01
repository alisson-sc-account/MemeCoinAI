import type { ReactNode } from 'react'
import type { Freshness } from './api/types'
import { relativeTime } from './lib/format'
import styles from './App.module.css'

export function FreshnessBadge({ data }: { data: Freshness }) {
  const label: Record<string, string> = { fresh: 'Atualizado', delayed: `Atrasado (${relativeTime(data.observed_at)})`, stale: `Desatualizado (${relativeTime(data.observed_at)})`, no_data: 'Sem dados' }
  const tone = data.status === 'fresh' ? styles.good : data.status === 'no_data' ? '' : styles.stale
  return <span className={`${styles.badge} ${tone}`}>{label[data.status] ?? data.status}</span>
}

export function RiskBadge({ level, score }: { level: string; score?: number | null }) {
  const labels: Record<string, string> = { low: 'Baixo', moderate: 'Moderado', high: 'Alto', critical: 'Crítico' }
  return <span className={`${styles.badge} ${styles[`risk-${level}`] ?? ''}`}>{labels[level] ?? level}{score == null ? '' : ` · ${new Intl.NumberFormat('pt-BR').format(score)}`}</span>
}

export function FactorList({ factors }: { factors: Array<{id:string;category:string;label:string;points:number;severity:string;confidence:number;evidence:Record<string,unknown>}> }) {
  return factors.length ? <div>{[...factors].sort((a,b)=>Math.abs(b.points)-Math.abs(a.points)).map(f=><details key={f.id}><summary>{f.label} · {f.points > 0 ? '+' : ''}{f.points} pontos</summary><p>{f.category} · {f.severity} · confiança {Math.round(f.confidence*100)}%</p><pre>{JSON.stringify(f.evidence,null,2)}</pre></details>)}</div> : <p className="muted">Nenhum fator informado pela análise.</p>
}

export function StateMessage({ children }: { children: ReactNode }) { return <div className={styles.empty}>{children}</div> }
