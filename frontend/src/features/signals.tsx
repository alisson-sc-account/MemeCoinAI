import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, apiClient } from '../api/client'
import type { Advice, Alert, HorizonEstimate, Position, Signal } from '../api/types'
import { price, relativeTime, shortAddress, usd } from '../lib/format'
import { ageText } from '../lib/format'
import { readCenterAlerts, wantsSignal, writeCenterAlerts, type CenterAlerts } from './alertPrefs'
import styles from './signals.module.css'
import { playAlertSound, setSoundEnabled, soundEnabled } from './sound'

export const REFRESH_MS = 30_000
export const ALERT_POLL_MS = 3_000  // alerta chega em ~3 s depois de detectado

const ACTION_LABEL: Record<string, string> = { buy: 'COMPRAR', sell: 'VENDER', avoid: 'EVITAR', hold: 'AGUARDAR', burst: 'DISPARO AGORA' }
const HORIZON_LABEL: Record<string, string> = { '15m': 'Em 15 min', '1h': 'Em 1 hora', '6h': 'Em 6 horas' }

const pct = (v: number | null | undefined, signed = true) =>
  v == null ? '—' : `${signed && v > 0 ? '+' : ''}${new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1 }).format(v * 100)}%`

export function ActionBadge({ action, strength }: { action: string; strength?: string }) {
  return <span className={`${styles.action} ${styles[action] ?? ''}`}>{ACTION_LABEL[action] ?? action}{strength === 'strong' ? ' · FORTE' : ''}</span>
}

function EstimateBox({ e }: { e: HorizonEstimate }) {
  if (e.basis === 'insufficient') {
    return <div className={styles.estimate}><small>{HORIZON_LABEL[e.horizon]}</small><b>—</b><small>Coletando histórico: {e.n} de {e.needed ?? 30} casos necessários</small></div>
  }
  const tone = (e.end_median ?? 0) > 0 ? styles.up : (e.end_median ?? 0) < 0 ? styles.down : ''
  return <div className={styles.estimate}>
    <small>{HORIZON_LABEL[e.horizon]}</small>
    <b className={tone}>{pct(e.end_median)}</b>
    <small>faixa típica {pct(e.end_p25)} a {pct(e.end_p75)}</small>
    <small>chance de subir ≥ 20%: <b>{pct(e.p_up_20, false)}</b> · ≥ 50%: {pct(e.p_up_50, false)}</small>
    <small>chance de cair ≥ 20%: {pct(e.p_down_20, false)}</small>
    <small>{e.basis === 'similar' ? `${e.n} casos parecidos` : `${e.n} casos (todos os tokens)`}</small>
  </div>
}

export function Estimates({ estimates }: { estimates: HorizonEstimate[] }) {
  if (!estimates.length) return null
  return <><div className={styles.estimates}>{estimates.map(e => <EstimateBox key={e.horizon} e={e} />)}</div>
    <small className={styles.meta}>Estimativas baseadas no que aconteceu depois de análises parecidas já medidas por este sistema (não é garantia). Retornos sem taxas e sem slippage.</small></>
}

export function SignalHero({ signal, estimates }: { signal: Signal | null | undefined; estimates: HorizonEstimate[] }) {
  if (!signal) return <div className={styles.hero}><p className={styles.headline}>Ainda sem sinal para este token</p><small className={styles.meta}>O sinal aparece após a primeira análise com dados de mercado.</small></div>
  return <section className={`${styles.hero} ${styles[signal.action] ?? ''}`} aria-label="Sinal atual">
    <div className={styles.heroTop}><ActionBadge action={signal.action} strength={signal.strength} /><h2 className={styles.headline}>{signal.headline}</h2></div>
    {signal.reasons.length > 0 && <ul className={styles.reasons}>{signal.reasons.map(r => <li key={r}>{r}</li>)}</ul>}
    <details><summary className={styles.meta}>Ver o que aconteceu com moedas parecidas</summary><Estimates estimates={estimates} /></details>
    <small className={styles.meta}>Risco {signal.risk_score.toFixed(0)}/100 · oportunidade {signal.opportunity_score.toFixed(0)}/100 · sinal desde {relativeTime(signal.created_at)}, confirmado {relativeTime(signal.last_confirmed_at)} · regras {signal.rules_version}</small>
  </section>
}

export function PositionPanel({ chainId, address, position, advice }: { chainId: string; address: string; position: Position | null | undefined; advice: Advice }) {
  const qc = useQueryClient()
  const [qty, setQty] = useState(position ? String(position.quantity) : '')
  const [entry, setEntry] = useState(position?.entry_price_usd ? String(position.entry_price_usd) : '')
  useEffect(() => { setQty(position ? String(position.quantity) : ''); setEntry(position?.entry_price_usd ? String(position.entry_price_usd) : '') }, [position])
  const refresh = () => qc.invalidateQueries({ queryKey: ['token', chainId, address] })
  const save = useMutation({ mutationFn: () => apiClient.savePosition(chainId, address, Number(qty.replace(',', '.')), entry ? Number(entry.replace(',', '.')) : null), onSuccess: refresh })
  const remove = useMutation({ mutationFn: () => apiClient.deletePosition(chainId, address), onSuccess: refresh })
  const qtyValid = Number(qty.replace(',', '.')) > 0
  const err = (save.error ?? remove.error) as ApiError | null
  return <section className={styles.hero} aria-label="Minha posição">
    <p className={styles.advice}>{advice.summary}</p>
    {advice.reasons.length > 0 && <ul className={styles.reasons}>{advice.reasons.map(r => <li key={r}>{r}</li>)}</ul>}
    {advice.slippage_note && <p className={styles.error}>{advice.slippage_note}</p>}
    {position && <div className={styles.row}><span>Valor atual: <b>{usd(position.value_usd)}</b></span>{position.pnl != null && <span className={position.pnl >= 0 ? styles.up : styles.down}>Resultado: {pct(position.pnl)}</span>}<span className={styles.meta}>preço atual {price(position.current_price_usd)}</span></div>}
    <form className={styles.form} onSubmit={e => { e.preventDefault(); if (qtyValid) save.mutate() }}>
      <label>Quantidade de tokens que você tem<input inputMode="decimal" value={qty} onChange={e => setQty(e.target.value)} placeholder="ex.: 150000" /></label>
      <label>Preço médio de compra (US$, opcional)<input inputMode="decimal" value={entry} onChange={e => setEntry(e.target.value)} placeholder="ex.: 0.00012" /></label>
      <div className={styles.row}>
        <button className={styles.btnPrimary} disabled={!qtyValid || save.isPending}>{save.isPending ? 'Salvando…' : position ? 'Atualizar' : 'Registrar posição'}</button>
        {position && <button type="button" className={styles.btn} disabled={remove.isPending} onClick={() => remove.mutate()}>Remover</button>}
      </div>
    </form>
    {err && <p className={styles.error} role="alert">{err.message}</p>}
    <small className={styles.meta}>{advice.disclaimer} A posição é só informada por você; o sistema não lê sua carteira.</small>
  </section>
}

/** Estatística do padrão de disparo guardada na evidência do alerta. */
type PatternStats = { n: number; p_up_10?: number; p_up_20?: number; median_max_return?: number }
function patternStats(alert: Alert): PatternStats | null {
  const raw = (alert.evidence as Record<string, unknown> | undefined)?.pattern_stats
  return raw && typeof raw === 'object' ? raw as PatternStats : null
}
function statsLine(s: PatternStats | null): string {
  if (!s || !s.n) return 'Ainda sem histórico medido para este padrão.'
  return `Em ${s.n} disparos iguais já medidos: ${pct(s.p_up_20, false)} chegaram a +20% e ${pct(s.p_up_10, false)} a +10% em 15 min (pico típico ${pct(s.median_max_return)}).`
}

export function ActiveSignals({ limit = 8 }: { limit?: number }) {
  const q = useQuery({ queryKey: ['signals', 'active', limit], queryFn: () => apiClient.signals(`action=buy&page_size=${limit}`), refetchInterval: REFRESH_MS, refetchIntervalInBackground: false })
  const bursts = useQuery({ queryKey: ['alerts', 'burst'], queryFn: () => apiClient.alerts('alert_type=pump_burst&status=open&page_size=5'), refetchInterval: REFRESH_MS, refetchIntervalInBackground: false })
  if (q.isPending) return <p className={styles.meta}>Carregando sinais…</p>
  if (q.isError) return <p className={styles.error}>{(q.error as Error).message}</p>
  const items = [...q.data.items].sort((a, b) => (b.strength === 'strong' ? 1 : 0) - (a.strength === 'strong' ? 1 : 0))
  const burstItems = bursts.data?.items ?? []
  if (!items.length && !burstItems.length) return <p className={styles.meta}>Nenhum sinal de compra ou venda agora. O sistema avisa assim que aparecer um.</p>
  return <div className={styles.list}>
    {burstItems.map(a => <Link key={`b${a.id}`} to={a.link ?? '/alerts'} className={styles.signalRow}>
      <ActionBadge action="burst" />
      <span><b>{a.token?.symbol || (a.token ? shortAddress(a.token.address) : 'Token')}</b> · {a.title}</span>
      <span className={styles.meta}>{relativeTime(a.detected_at)}</span>
    </Link>)}
    {items.map(s => {
      const e1 = s.estimates.find(e => e.horizon === '1h')
      return <Link key={s.id} to={s.link} className={styles.signalRow}>
        <ActionBadge action={s.action} strength={s.strength} />
        <span><b>{s.token.symbol || shortAddress(s.token.address)}</b> · {buyLine(s) ?? s.headline}</span>
        <span className={styles.meta}>{e1 && e1.basis !== 'insufficient' ? `1 h: ${pct(e1.end_median)} típico` : relativeTime(s.created_at)}</span>
      </Link>
    })}
  </div>
}

/** "Compre agora com 10% do seu saldo (R$ 5,00)" quando há saldo configurado. */
function buyLine(s: Signal): string | null {
  if (s.action !== 'buy' || !s.allocation) return null
  const verb = s.strength === 'strong' ? 'Compre agora' : 'Possível entrada'
  return `${verb} com ${new Intl.NumberFormat('pt-BR').format(s.allocation.percent_of_balance)}% do seu saldo (${money(s.allocation.amount, s.allocation.currency)})`
}

/** Alerta próprio de disparo: aparece sobre qualquer página, com som próprio. */
function useBurstWatch(username: string, navigate: (to: string) => void, enabled: boolean) {
  const read = useCallback(() => readSeen(`mcai-last-burst-${username}`), [username])
  const write = useCallback((id: number) => writeSeen(`mcai-last-burst-${username}`, id), [username])
  const [lastSeen, setLastSeen] = useState<number | null>(read)
  const q = useQuery({ queryKey: ['alerts', 'burst', 'watch'], queryFn: () => apiClient.alerts('alert_type=pump_burst&status=open&page_size=10'), refetchInterval: ALERT_POLL_MS, refetchIntervalInBackground: true })
  const items = useMemo(() => (q.data?.items ?? []).filter(a => a.alert_type === 'pump_burst'), [q.data])
  const maxId = items.reduce((m, a) => Math.max(m, a.id), 0)
  useEffect(() => { if (q.data && lastSeen == null) { setLastSeen(maxId); write(maxId) } }, [q.data, lastSeen, maxId, write])
  const fresh = lastSeen == null ? [] : items.filter(a => a.id > lastSeen).sort((a, b) => b.id - a.id)
  const top = enabled ? fresh[0] : undefined
  const topId = top?.id
  useEffect(() => { if (topId != null) playAlertSound('burst') }, [topId])
  useEffect(() => {
    if (!top || typeof Notification === 'undefined' || Notification.permission !== 'granted' || !document.hidden) return
    try { new Notification(`DISPARO: ${top.token?.symbol ?? 'token'}`, { body: top.title, tag: `burst-${top.id}` }) } catch { /* sem suporte */ }
  }, [top])
  if (!top) return null
  const dismiss = () => { setLastSeen(maxId); write(maxId) }
  const stats = patternStats(top)
  return <div className={styles.shade} role="presentation" onClick={dismiss}>
    <CloseOnEscape onClose={dismiss} />
    <div className={`${styles.modal} ${styles.burst}`} role="alertdialog" aria-modal="true" aria-labelledby="burst-title" onClick={e => e.stopPropagation()}>
      <ActionBadge action="burst" />
      <p id="burst-title" className={styles.big}>{top.title}</p>
      <p className={styles.meta}>Detectado {ageText(top.detected_at, Date.now())}</p>
      <p><b>{top.token?.symbol || top.token?.name || 'Token'}</b> {top.token && <span className={styles.meta}>{shortAddress(top.token.address)}</span>}</p>
      <ul className={styles.reasons}>{top.reason.split('; ').map(r => <li key={r}>{r}</li>)}</ul>
      <div className={styles.stats}><small>Histórico deste padrão</small><span>{statsLine(stats)}</span></div>
      <p className={styles.meta}>Detecção de movimento em andamento, não previsão: muitos disparos se desfazem em minutos.</p>
      <div className={styles.row}>
        <button className={styles.btnPrimary} autoFocus onClick={() => { dismiss(); navigate(top.link ?? '/alerts') }}>Ver token</button>
        <button className={styles.btn} onClick={dismiss}>Fechar</button>
      </div>
    </div>
  </div>
}

function readSeen(key: string): number | null { try { const v = localStorage.getItem(key); return v == null ? null : Number(v) } catch { return null } }
function writeSeen(key: string, id: number) { try { localStorage.setItem(key, String(id)) } catch { /* armazenamento indisponível */ } }
function readLastSeen(user: string): number | null { return readSeen(`mcai-last-signal-${user}`) }
function writeLastSeen(user: string, id: number) { writeSeen(`mcai-last-signal-${user}`, id) }

function money(amount: number | null | undefined, currency: string | null | undefined) {
  if (amount == null) return '—'
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: currency === 'USD' ? 'USD' : 'BRL' }).format(amount)
}

export function BalanceSettings() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['settings'], queryFn: apiClient.settings })
  const [balance, setBalance] = useState('')
  const [currency, setCurrency] = useState<'BRL' | 'USD'>('BRL')
  const [maxPct, setMaxPct] = useState('10')
  const [saved, setSaved] = useState(false)
  useEffect(() => {
    if (!q.data) return
    setBalance(q.data.balance_amount == null ? '' : String(q.data.balance_amount).replace('.', ','))
    setCurrency(q.data.balance_currency ?? 'BRL')
    setMaxPct(String(q.data.max_trade_percent ?? 10).replace('.', ','))
  }, [q.data])
  const num = (v: string) => Number(v.replace(/\./g, '').replace(',', '.'))
  const valid = (balance === '' || num(balance) >= 0) && num(maxPct) > 0 && num(maxPct) <= 100
  const save = useMutation({
    mutationFn: () => apiClient.saveSettings({ balance_amount: balance === '' ? null : num(balance), balance_currency: currency, max_trade_percent: num(maxPct) }),
    onSuccess: () => { setSaved(true); void qc.invalidateQueries({ queryKey: ['settings'] }); void qc.invalidateQueries({ queryKey: ['signals'] }); void qc.invalidateQueries({ queryKey: ['token'] }) },
  })
  const example = balance && num(balance) > 0 ? money(num(balance) * num(maxPct) / 100, currency) : null
  if (q.isPending) return <p className={styles.meta}>Carregando…</p>
  return <form className={styles.form} onSubmit={e => { e.preventDefault(); setSaved(false); if (valid) save.mutate() }}>
    <label>Saldo disponível<input inputMode="decimal" value={balance} onChange={e => { setBalance(e.target.value); setSaved(false) }} placeholder="ex.: 50" /></label>
    <label>Moeda<select value={currency} onChange={e => { setCurrency(e.target.value as 'BRL' | 'USD'); setSaved(false) }} className={styles.select}><option value="BRL">Real (R$)</option><option value="USD">Dólar (US$)</option></select></label>
    <label>Máximo por operação (% do saldo)<input inputMode="decimal" value={maxPct} onChange={e => { setMaxPct(e.target.value); setSaved(false) }} /></label>
    <div className={styles.row}><button className={styles.btnPrimary} disabled={!valid || save.isPending}>{save.isPending ? 'Salvando…' : 'Salvar saldo'}</button>{saved && <span role="status">Salvo.</span>}</div>
    {save.isError && <p className={styles.error} role="alert">{(save.error as Error).message}</p>}
    <small className={styles.meta} style={{ gridColumn: '1 / -1' }}>
      {example ? `Com esse saldo, um sinal de compra forte de baixo risco sugere até ${example} (${maxPct}%). Sinais moderados usam metade, e tokens com risco moderado ou maior, metade de novo.` : 'Informe o saldo para os avisos de compra dizerem quanto usar.'}
      {' '}Valor apenas para simulação: o sistema não acessa corretora nem carteira e não executa ordens.
    </small>
  </form>
}

export function SoundSettings() {
  const [on, setOn] = useState(soundEnabled)
  const [msg, setMsg] = useState('')
  return <div className={styles.row}>
    <label className={styles.row}><input type="checkbox" checked={on} onChange={e => { setOn(e.target.checked); setSoundEnabled(e.target.checked) }} /> Tocar som quando aparecer um sinal de compra ou venda</label>
    <button type="button" className={styles.btn} onClick={() => { setMsg(playAlertSound('buy') ? '' : on ? 'O navegador ainda não liberou o áudio; clique de novo.' : 'Som desativado.') }}>Testar som</button>
    {msg && <span className={styles.meta}>{msg}</span>}
  </div>
}

/** ESC fecha o alerta que está no meio da tela. */
function CloseOnEscape({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const handle = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handle)
    return () => window.removeEventListener('keydown', handle)
  }, [onClose])
  return null
}

const CENTER_OPTIONS: { key: keyof CenterAlerts; label: string; hint: string }[] = [
  { key: 'buy_strong', label: 'Compra forte', hint: 'Compra prioritária' },
  { key: 'buy', label: 'Compra possível', hint: 'Sinal moderado: aparece mais vezes' },
  { key: 'burst', label: 'Disparo', hint: 'Moeda subindo de repente, em minutos' },
  { key: 'sell', label: 'Venda', hint: 'Desligado: a venda aparece dentro da moeda' },
]

export function PhoneSettings() {
  const q = useQuery({ queryKey: ['phone'], queryFn: apiClient.phone })
  if (q.isPending) return <p className={styles.meta}>Carregando…</p>
  if (q.isError || !q.data.url) return <p className={styles.meta}>Aviso no celular desligado.</p>
  return <div className={styles.list}>
    <p>Abra este link no celular uma vez e toque em "Subscribe". Vão disparo extremo e compra forte, de graça e sem conta.</p>
    <a href={q.data.url} target="_blank" rel="noopener noreferrer" className={styles.phoneLink}>{q.data.url}</a>
    <p className={styles.meta}>Quem tiver este link vê os avisos. Não vai saldo nem posição. Limite de 200 avisos por dia.</p>
  </div>
}

export function CenterAlertSettings() {
  const [prefs, setPrefs] = useState(readCenterAlerts)
  const change = (key: keyof CenterAlerts, on: boolean) => { const next = { ...prefs, [key]: on }; setPrefs(next); writeCenterAlerts(next) }
  return <div className={styles.list}>
    {CENTER_OPTIONS.map(o => <label key={o.key} className={styles.row}>
      <input type="checkbox" checked={prefs[o.key]} onChange={e => change(o.key, e.target.checked)} /> <b>{o.label}</b> <span className={styles.meta}>{o.hint}</span>
    </label>)}
  </div>
}

/** Alerta no centro da tela, em qualquer página, para os tipos escolhidos em Configurações. */
export function SignalWatcher({ username }: { username: string }) {
  const navigate = useNavigate()
  const prefs = readCenterAlerts()
  const burst = useBurstWatch(username, navigate, prefs.burst)
  const [lastSeen, setLastSeen] = useState<number | null>(() => readLastSeen(username))
  const q = useQuery({ queryKey: ['signals', 'watch'], queryFn: () => apiClient.signals('action=buy&action=sell&page_size=20'), refetchInterval: ALERT_POLL_MS, refetchIntervalInBackground: true })
  const relevant = (q.data?.items ?? []).filter(s => wantsSignal(prefs, s.action, s.strength))
  const maxId = relevant.reduce((m, s) => Math.max(m, s.id), 0)
  useEffect(() => {
    // Primeira visita: não abre alerta de sinais antigos, só passa a vigiar os novos.
    if (q.data && lastSeen == null) { setLastSeen(maxId); writeLastSeen(username, maxId) }
  }, [q.data, lastSeen, maxId, username])
  const fresh = lastSeen == null ? [] : relevant.filter(s => s.id > lastSeen).sort((a, b) => b.id - a.id)
  const top = fresh[0]
  const topId = top?.id
  const topAction = top?.action
  useEffect(() => {
    if (topId == null) return
    playAlertSound(topAction === 'sell' ? 'sell' : 'buy')
  }, [topId, topAction])
  useEffect(() => {
    if (!top || typeof Notification === 'undefined' || Notification.permission !== 'granted' || !document.hidden) return
    try { new Notification(`${ACTION_LABEL[top.action]} ${top.token.symbol ?? ''}`.trim(), { body: buyLine(top) ?? top.headline, tag: `signal-${top.id}` }) } catch { /* sem suporte */ }
  }, [top])
  if (burst) return burst            // disparo em andamento tem prioridade
  if (!top) return null
  const dismiss = () => { setLastSeen(maxId); writeLastSeen(username, maxId) }
  const e1 = top.estimates.find(e => e.horizon === '1h')
  const canAsk = typeof Notification !== 'undefined' && Notification.permission === 'default'
  return <div className={styles.shade} role="presentation" onClick={dismiss}>
    <CloseOnEscape onClose={dismiss} />
    <div className={`${styles.modal} ${styles[top.action] ?? ''}`} role="alertdialog" aria-modal="true" aria-labelledby="signal-title" onClick={e => e.stopPropagation()}>
      <ActionBadge action={top.action} strength={top.strength} />
      <p id="signal-title" className={styles.big}>{buyLine(top) ?? top.headline}</p>
      <p className={styles.meta}>Sinal emitido {ageText(top.created_at, Date.now())}</p>
      <p><b>{top.token.symbol || top.token.name || 'Token'}</b> <span className={styles.meta}>{shortAddress(top.token.address)}</span></p>
      {top.action === 'buy' && !top.allocation && <p className={styles.meta}>Informe seu saldo em Conta para ver quanto usar.</p>}
      {e1 && e1.basis !== 'insufficient' && <p>Em 1 hora, casos parecidos: típico <b>{pct(e1.end_median)}</b> (faixa {pct(e1.end_p25)} a {pct(e1.end_p75)}); chance de subir ≥ 20%: {pct(e1.p_up_20, false)}.</p>}
      {top.reasons.length > 0 && <ul className={styles.reasons}>{top.reasons.slice(0, 4).map(r => <li key={r}>{r}</li>)}</ul>}
      <p className={styles.meta}>Risco {top.risk_score.toFixed(0)}/100. Estimativa automática, não é garantia. {fresh.length > 1 ? `+${fresh.length - 1} outro(s) sinal(is) novo(s).` : ''}</p>
      <div className={styles.row}>
        <button className={styles.btnPrimary} autoFocus onClick={() => { dismiss(); navigate(top.link) }}>Ver token</button>
        <button className={styles.btn} onClick={dismiss}>Fechar</button>
        {canAsk && <button className={styles.btn} onClick={() => { void Notification.requestPermission() }}>Avisar também em outras abas</button>}
      </div>
    </div>
  </div>
}
