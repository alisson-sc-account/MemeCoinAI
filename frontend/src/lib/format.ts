export const usd = (value: number | null | undefined) => {
  if (value == null || !Number.isFinite(value)) return '—'
  if (Math.abs(value) >= 1_000_000_000) return `US$ ${new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1 }).format(value / 1_000_000_000)} bi`
  if (Math.abs(value) >= 1_000_000) return `US$ ${new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 2 }).format(value / 1_000_000)} mi`
  return `US$ ${new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value)}`
}
export const price = (value: number | null | undefined) => {
  if (value == null || !Number.isFinite(value)) return '—'
  if (value === 0) return 'US$ 0,00'
  const abs = Math.abs(value)
  if (abs >= 1) return `US$ ${new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 4 }).format(value)}`
  if (abs >= 0.0001) return `US$ ${new Intl.NumberFormat('pt-BR', { maximumSignificantDigits: 4 }).format(value)}`
  const [mantissa, exponentText] = abs.toExponential(3).split('e')
  const zeros = Math.max(Number(exponentText) * -1 - 1, 0)
  const subscript = String(zeros).split('').map(d => '₀₁₂₃₄₅₆₇₈₉'[Number(d)]).join('')
  // Mantissa sem separador: 6.814e-5 → 0,0₄6814 (o subscrito conta os zeros após a vírgula).
  return `${value < 0 ? '−' : ''}US$ 0,0${subscript}${(mantissa ?? '').replace('.', '').replace(/0+$/, '')}`
}
export const percent = (value: number | null | undefined) => value == null || !Number.isFinite(value) ? '—' : `${value > 0 ? '+' : ''}${new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value)}%`
export const fraction = (value: number | null | undefined) => value == null ? '—' : `${new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1 }).format(value * 100)}%`
export const compact = (value: number | null | undefined) => value == null ? '—' : new Intl.NumberFormat('pt-BR', { notation: 'compact', maximumFractionDigits: 1 }).format(value)
export const dateTime = (value: string | null | undefined) => value ? new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'medium' }).format(new Date(value)) : '—'
export const relativeTime = (value: string | null | undefined) => {
  if (!value) return '—'
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000))
  if (seconds < 60) return `há ${seconds} s`
  if (seconds < 3600) return `há ${Math.floor(seconds / 60)} min`
  if (seconds < 86400) return `há ${Math.floor(seconds / 3600)} h`
  return `há ${Math.floor(seconds / 86400)} d`
}
export const shortAddress = (value: string) => value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value
/** "há 3 min 12 s" — idade em minutos e segundos, recalculada no cliente. */
export function ageText(iso: string | null | undefined, nowMs: number): string {
  if (!iso) return 'sem dados'
  const total = Math.max(0, Math.floor((nowMs - new Date(iso).getTime()) / 1000))
  const h = Math.floor(total / 3600), m = Math.floor((total % 3600) / 60), s = total % 60
  if (h) return `há ${h} h ${m} min`
  return m ? `há ${m} min ${s} s` : `há ${s} s`
}
