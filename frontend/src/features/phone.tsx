import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../api/client'
import type { PhoneKind, PhonePrefs, PhonePriority, PhoneRule, PhoneSeverity } from '../api/types'
import app from '../App.module.css'
import styles from './phone.module.css'

const KINDS: { key: PhoneKind; label: string; hint: string }[] = [
  { key: 'burst', label: 'Disparo', hint: 'Moeda subindo de repente' },
  { key: 'buy_strong', label: 'Compra forte', hint: 'Sinal prioritário' },
  { key: 'buy', label: 'Compra possível', hint: 'Sinal moderado: vem mais vezes' },
  { key: 'sell', label: 'Venda', hint: 'Sinal de saída' },
  { key: 'risk', label: 'Risco', hint: 'Alertas de risco (golpe, liquidez saindo…)' },
]
const PRIORITIES: { v: PhonePriority; label: string }[] = [
  { v: 'min', label: 'Mínima (sem som)' }, { v: 'low', label: 'Baixa' }, { v: 'default', label: 'Normal' },
  { v: 'high', label: 'Alta' }, { v: 'urgent', label: 'Urgente (toca alto)' },
]
const SEVERITIES: PhoneSeverity[] = ['info', 'low', 'medium', 'high', 'critical']
const FIELDS = '{symbol} {name} {kind} {reason} {score} {risk} {liquidity} {chain} {address}'

export function PhonePrefsEditor() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['phonePrefs'], queryFn: apiClient.phonePrefs })
  const [p, setP] = useState<PhonePrefs | null>(null)
  const [muted, setMuted] = useState('')
  const [msg, setMsg] = useState('')
  useEffect(() => { if (q.data) { setP(q.data); setMuted(q.data.muted.join('\n')) } }, [q.data])
  const done = (data: PhonePrefs, text: string) => { qc.setQueryData(['phonePrefs'], data); void qc.invalidateQueries({ queryKey: ['phone'] }); setMsg(text) }
  const save = useMutation({
    mutationFn: (body: PhonePrefs) => apiClient.savePhonePrefs(body),
    onSuccess: d => done(d, 'Salvo. Vale no próximo aviso, sem reiniciar.'),
    onError: e => setMsg(e instanceof Error ? e.message : 'Falha ao salvar.'),
  })
  const reset = useMutation({ mutationFn: apiClient.resetPhonePrefs, onSuccess: d => done(d, 'Tudo voltou ao padrão.') })
  const test = useMutation({
    mutationFn: (kind: PhoneKind) => apiClient.phoneTest(kind),
    onSuccess: r => setMsg(r.sent ? 'Teste enviado: confira o celular.' : 'O teste não saiu (servidor do ntfy fora ou canal errado).'),
    onError: e => setMsg(e instanceof Error ? e.message : 'Falha no teste.'),
  })
  if (q.isPending || !p) return <p className={styles.hint}>Carregando preferências…</p>
  if (q.isError) return <p className={styles.error}>Não deu para ler as preferências.</p>
  const set = <K extends keyof PhonePrefs>(k: K, v: PhonePrefs[K]) => setP({ ...p, [k]: v })
  const rule = (k: PhoneKind, patch: Partial<PhoneRule>) => setP({ ...p, rules: { ...p.rules, [k]: { ...p.rules[k], ...patch } } })
  const num = (v: string) => (v === '' ? 0 : Number(v))
  const submit = () => { setMsg(''); save.mutate({ ...p, muted: muted.split(/[\n,]/).map(x => x.trim()).filter(Boolean) }) }

  return <form className={styles.form} onSubmit={e => { e.preventDefault(); submit() }}>
    <label className={styles.check}><input type="checkbox" checked={p.enabled} onChange={e => set('enabled', e.target.checked)}/> <b>Mandar avisos no celular</b></label>

    <div className={styles.section}>
      <h3>O que avisar e como</h3>
      <p className={styles.hint}>No título e no texto, use os campos: {FIELDS}. A prioridade define o som no celular. Os ícones são nomes de emoji do ntfy separados por vírgula (ex.: rocket, fire, warning, moneybag).</p>
      {KINDS.map(k => {
        const r = p.rules[k.key]
        return <div className={styles.rule} key={k.key}>
          <label className={styles.check} title={k.hint}><input type="checkbox" checked={r.enabled} onChange={e => rule(k.key, { enabled: e.target.checked })}/> {k.label}</label>
          <label>Prioridade<select value={r.priority} onChange={e => rule(k.key, { priority: e.target.value as PhonePriority })}>{PRIORITIES.map(x => <option key={x.v} value={x.v}>{x.label}</option>)}</select></label>
          <label>Título<input value={r.title} maxLength={120} onChange={e => rule(k.key, { title: e.target.value })}/></label>
          <label>Ícones<input value={r.tags} maxLength={120} onChange={e => rule(k.key, { tags: e.target.value })}/></label>
          {(k.key === 'burst' || k.key === 'risk') && <label>Gravidade mínima<select value={r.min_severity} onChange={e => rule(k.key, { min_severity: e.target.value as PhoneSeverity })}>{SEVERITIES.map(s => <option key={s}>{s}</option>)}</select></label>}
          <button type="button" className={app.button} disabled={test.isPending} onClick={() => test.mutate(k.key)}>Testar</button>
        </div>
      })}
      <label>Texto do aviso<textarea value={p.body} maxLength={500} onChange={e => set('body', e.target.value)}/></label>
    </div>

    <div className={styles.section}>
      <h3>Filtros</h3>
      <div className={styles.grid}>
        <label>Score mínimo de oportunidade (0–100)<input type="number" min={0} max={100} value={p.min_opportunity_score} onChange={e => set('min_opportunity_score', num(e.target.value))}/></label>
        <label>Risco máximo (0–100)<input type="number" min={0} max={100} value={p.max_risk_score} onChange={e => set('max_risk_score', num(e.target.value))}/></label>
        <label>Liquidez mínima (US$)<input type="number" min={0} value={p.min_liquidity_usd} onChange={e => set('min_liquidity_usd', num(e.target.value))}/></label>
      </div>
      <p className={styles.hint}>Score e risco valem para sinais; disparo e risco usam a gravidade mínima acima.</p>
    </div>

    <div className={styles.section}>
      <h3>Favoritas e silenciadas</h3>
      <label className={styles.check}><input type="checkbox" checked={p.favorites_only} onChange={e => set('favorites_only', e.target.checked)}/> Só avisar moedas favoritadas</label>
      <label className={styles.check}><input type="checkbox" checked={p.favorites_bypass_filters} onChange={e => set('favorites_bypass_filters', e.target.checked)}/> Favoritas ignoram os filtros de score, risco e liquidez</label>
      <label>Moedas silenciadas (endereço ou símbolo, uma por linha)<textarea value={muted} onChange={e => setMuted(e.target.value)}/></label>
    </div>

    <div className={styles.section}>
      <h3>Horário silencioso</h3>
      <div className={styles.grid}>
        <label className={styles.check}><input type="checkbox" checked={p.quiet.enabled} onChange={e => set('quiet', { ...p.quiet, enabled: e.target.checked })}/> Ligado</label>
        <label>De<input type="time" value={p.quiet.start} onChange={e => set('quiet', { ...p.quiet, start: e.target.value })}/></label>
        <label>Até<input type="time" value={p.quiet.end} onChange={e => set('quiet', { ...p.quiet, end: e.target.value })}/></label>
        <label className={styles.check}><input type="checkbox" checked={p.quiet.allow_urgent} onChange={e => set('quiet', { ...p.quiet, allow_urgent: e.target.checked })}/> Urgentes tocam mesmo assim</label>
      </div>
    </div>

    <div className={styles.section}>
      <h3>Limites</h3>
      <div className={styles.grid}>
        <label>Espera entre avisos da mesma moeda (min)<input type="number" min={0} max={1440} value={p.token_cooldown_minutes} onChange={e => set('token_cooldown_minutes', num(e.target.value))}/></label>
        <label>Máximo por hora<input type="number" min={1} max={500} value={p.max_per_hour} onChange={e => set('max_per_hour', num(e.target.value))}/></label>
        <label>Máximo por dia<input type="number" min={1} max={200} value={p.daily_cap} onChange={e => set('daily_cap', num(e.target.value))}/></label>
      </div>
      <p className={styles.hint}>O ntfy.sh grátis aceita ~250 por dia; o sistema nunca passa de 200.</p>
    </div>

    <div className={styles.section}>
      <h3>Canal</h3>
      <div className={styles.grid}>
        <label>Servidor (vazio = ntfy.sh)<input placeholder="https://ntfy.sh" value={p.server} onChange={e => set('server', e.target.value)}/></label>
        <label>Canal próprio (vazio = canal secreto sorteado)<input placeholder="ex.: meu-canal-secreto-123" value={p.topic} onChange={e => set('topic', e.target.value)}/></label>
      </div>
      <p className={styles.hint}>Quem souber o nome do canal vê os avisos: use um nome longo e difícil. Trocando o canal, inscreva o novo link no app do ntfy.</p>
    </div>

    <div className={styles.actions}>
      <button className={app.primaryButton} disabled={save.isPending}>{save.isPending ? 'Salvando…' : 'Salvar'}</button>
      <button type="button" className={app.button} onClick={() => { setP(q.data); setMuted(q.data.muted.join('\n')); setMsg('') }}>Desfazer</button>
      <button type="button" className={app.dangerButton} disabled={reset.isPending} onClick={() => { if (confirm('Voltar todas as preferências de aviso ao padrão?')) reset.mutate() }}>Voltar ao padrão</button>
      {msg && <span role="status" className={styles.hint}>{msg}</span>}
    </div>
  </form>
}
