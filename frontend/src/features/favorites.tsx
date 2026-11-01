import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Star } from 'lucide-react'
import { apiClient } from '../api/client'
import type { Favorite, FavoritePage } from '../api/types'
import { dateTime, price, shortAddress, usd } from '../lib/format'
import styles from './favorites.module.css'
import { REFRESH_MS } from './signals'

const gainText = (v: number | null | undefined) => v == null ? 'sem dado' : `${v > 0 ? '+' : ''}${new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 2 }).format(v * 100)}%`
const gainClass = (v: number | null | undefined) => v == null ? '' : v > 0 ? styles.up : v < 0 ? styles.down : ''

function Gain({ label, value, hint }: { label: string; value?: number | null; hint?: string }) {
  return <div className={styles.gain}><small>{label}</small><b className={gainClass(value)}>{gainText(value)}</b>{hint && <small>{hint}</small>}</div>
}

function useFavorites() {
  return useQuery<FavoritePage>({ queryKey: ['favorites'], queryFn: apiClient.favorites, refetchInterval: REFRESH_MS, refetchIntervalInBackground: false })
}

/** Estrela de uma previsão. Fica dentro de cards que são links: não pode navegar ao clicar. */
export function FavoriteStar({ chainId, address, signalId, symbol }: { chainId: string; address: string; signalId: number | null | undefined; symbol?: string | null }) {
  const qc = useQueryClient()
  const q = useFavorites()
  const found = q.data?.items.find(f => f.token.chain_id === chainId && f.token.address === address && (f.signal_id ?? null) === (signalId ?? null))
  const done = () => void qc.invalidateQueries({ queryKey: ['favorites'] })
  const add = useMutation({ mutationFn: () => apiClient.addFavorite(chainId, address, signalId ?? null), onSuccess: done })
  const remove = useMutation({ mutationFn: (id: number) => apiClient.removeFavorite(id), onSuccess: done })
  const name = symbol || shortAddress(address)
  const busy = add.isPending || remove.isPending
  return <button type="button" className={`${styles.star} ${found ? styles.starOn : ''}`} disabled={busy} aria-pressed={Boolean(found)}
    aria-label={found ? `Remover ${name} dos favoritados` : `Favoritar previsão de ${name}`} title={found ? 'Remover dos favoritados' : 'Favoritar: registra o ganho até agora'}
    onClick={e => {
      e.preventDefault(); e.stopPropagation()
      if (!found) add.mutate()
      else if (window.confirm(`Remover ${name} dos favoritados? O ganho registrado será apagado.`)) remove.mutate(found.id)
    }}>
    <Star size={18} fill={found ? 'currentColor' : 'none'} />
  </button>
}

function FavoriteCard({ f }: { f: Favorite }) {
  const qc = useQueryClient()
  const remove = useMutation({ mutationFn: () => apiClient.removeFavorite(f.id), onSuccess: () => void qc.invalidateQueries({ queryKey: ['favorites'] }) })
  return <article className={styles.card}>
    <header className={styles.head}>
      <div>
        <Link to={f.link} className={styles.symbol}>{f.token.symbol || f.token.name || shortAddress(f.token.address)}</Link>
        <div className={styles.muted}>{f.tier_label} · {f.prediction}</div>
      </div>
      <div className={styles.now}><small>Ganho no clique</small><b className={gainClass(f.gain_at_favorite)}>{gainText(f.gain_at_favorite)}</b></div>
    </header>
    <div className={styles.gains}>
      <Gain label="Melhor até o clique" value={f.max_gain_until_favorite} />
      <Gain label="Pior até o clique" value={f.min_gain_until_favorite} />
      <div className={styles.gain}><small>Preço no sinal</small><b>{price(f.reference_price_usd)}</b></div>
      <div className={styles.gain}><small>Preço no clique</small><b>{price(f.price_at_favorite)}</b></div>
    </div>
    <p className={styles.muted}>
      Sinal em {dateTime(f.signal_at)} · favoritado em {dateTime(f.favorited_at)}
      {f.value_of_100_usd_at_favorite != null && <> · US$ 100 no sinal valiam {usd(f.value_of_100_usd_at_favorite)}</>}
      {f.liquidity_at_favorite != null && <> · liquidez {usd(f.liquidity_at_favorite)}</>}
    </p>
    <div className={styles.foot}>
      <button type="button" className={styles.link} disabled={remove.isPending}
        onClick={() => { if (window.confirm('Remover dos favoritados? O ganho registrado será apagado.')) remove.mutate() }}>Remover</button>
    </div>
  </article>
}

export function FavoritesPage() {
  const q = useFavorites()
  const [copied, setCopied] = useState<'idle' | 'loading' | 'done'>('idle')
  const [manual, setManual] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const copy = async () => {
    setCopied('loading'); setError(null); setManual(null)
    let text: string
    try { text = (await apiClient.favoritesReport()).text }
    catch (e) { setCopied('idle'); setError(e instanceof Error ? e.message : 'Não foi possível gerar o relatório.'); return }
    try {
      await navigator.clipboard.writeText(text)
      setCopied('done'); window.setTimeout(() => setCopied('idle'), 2500)
    } catch { setCopied('idle'); setManual(text) }  // navegador bloqueou: mostra o texto para copiar à mão
  }
  const s = q.data?.summary
  return <>
    <header className={styles.top}>
      <div>
        <h1>Favoritados</h1>
        <p className={styles.muted}>Previsões que você marcou com a estrela. O ganho fica congelado no instante do clique. Bruto, sem taxas.</p>
      </div>
      <button type="button" className={styles.copy} disabled={copied === 'loading' || !q.data?.items.length} onClick={() => void copy()}>
        <Copy size={16} />{copied === 'loading' ? 'Gerando…' : copied === 'done' ? 'Copiado!' : 'Copiar resultados e especificações'}
      </button>
    </header>
    {error && <p role="alert" className={styles.down}>{error}</p>}
    {manual != null && <label className={styles.manual}>O navegador bloqueou a cópia automática. Selecione o texto e copie:
      <textarea readOnly rows={10} value={manual} onFocus={e => e.currentTarget.select()} /></label>}
    {q.isPending ? <p className={styles.muted}>Carregando…</p>
      : q.isError ? <p role="alert" className={styles.down}>{(q.error as Error).message}</p>
      : q.data.items.length === 0 ? <div className={styles.empty}><Star size={22} /><p>Nenhuma previsão favoritada ainda. Clique na estrela de um card em <Link to="/compre-agora">Compre agora</Link>.</p></div>
      : <>
        {s && <div className={styles.summary}>
          <Gain label="Ganho médio no clique" value={s.avg_gain_at_favorite} />
          <div className={styles.gain}><small>Com ganho / com perda</small><b>{s.positive} / {s.negative}</b><small>de {s.count} favoritos</small></div>
          <Gain label="Melhor" value={s.best_gain} hint={s.best_symbol ?? undefined} />
          <Gain label="Pior" value={s.worst_gain} hint={s.worst_symbol ?? undefined} />
        </div>}
        <div className={styles.list}>{q.data.items.map(f => <FavoriteCard key={f.id} f={f} />)}</div>
        <p className={styles.muted}>{q.data.disclaimer}</p>
      </>}
  </>
}
