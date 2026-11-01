import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ageText } from '../lib/format'
import { AccuracyPage } from './accuracy'
import { SellPlanPanel, nextPollMs } from './sellplan'

function LocationProbe() { const l = useLocation(); return <output data-testid="route">{l.pathname + l.search}</output> }
function wrap(ui: React.ReactNode, route = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[route]}>{ui}<LocationProbe /></MemoryRouter></QueryClientProvider>)
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers() })

const counts = (hits: number, misses: number, pending = 0) => ({ hits, misses, evaluated: hits + misses, pending, unevaluable: 0, hit_rate: hits + misses ? hits / (hits + misses) : null })
const token = { chain_id: 'solana', address: 'Aaaa1111111111111111111111111111111111111111', symbol: 'AAA', name: 'AAA', image_url: null }
const result = (status: string, end: number | null) => ({ status, resolves_at: '2026-10-29T12:00:00Z', end_return: end, max_return: end, min_return: end, end_price_usd: null })
const accuracyPage = {
  horizon: '1h',
  summary: { '15m': { all: counts(1, 1), buy: counts(1, 0), sell: counts(0, 1) },
             '1h': { all: counts(3, 1, 2), buy: counts(2, 1), sell: counts(1, 0),
                     priority_buy: counts(2, 0), possible_buy: counts(0, 1), watch: counts(5, 5) },
             '6h': { all: counts(0, 0, 4), buy: counts(0, 0, 2), sell: counts(0, 0, 2) } },
  items: [
    { signal_id: 1, token, link: `/tokens/solana/${token.address}`, action: 'buy', tier: 'priority_buy', tier_label: 'Compra prioritária', prediction: 'Deve subir', strength: 'strong', headline: 'h', created_at: '2026-10-29T10:00:00Z', reference_price_usd: 0.001,
      results: { '15m': result('hit', 0.05), '1h': result('hit', 0.12), '6h': result('pending', null) } },
    { signal_id: 2, token, link: `/tokens/solana/${token.address}`, action: 'sell', tier: 'sell', tier_label: 'Venda (queda)', prediction: 'Deve descer', strength: 'moderate', headline: 'h', created_at: '2026-10-29T10:00:00Z', reference_price_usd: 0.001,
      results: { '15m': result('miss', 0.02), '1h': result('miss', 0.03), '6h': result('pending', null) } },
  ],
  total: 2, page: 1, page_size: 100, rules_version: 'acc-1', definition: 'Definição.',
}

describe('aba Acertos', () => {
  it('mostra quantas acertou, errou e quais', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json(accuracyPage)))
    wrap(<AccuracyPage />, '/acertos')
    expect(await screen.findByText('Previsões de subida (COMPRAR)')).toBeInTheDocument()
    const kpi = (label: string) => screen.getByText(label, { selector: 'small' }).parentElement!
    expect(kpi('Acertou')).toHaveTextContent('3')
    expect(kpi('Errou')).toHaveTextContent('1')
    expect(kpi('Taxa de acerto')).toHaveTextContent('75%')
    const rows = screen.getAllByRole('link')
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveTextContent('Acertou')
    expect(rows[0]).toHaveTextContent('Deve subir')
    expect(rows[0]).toHaveTextContent('Compra prioritária')
    expect(rows[0]).toHaveTextContent('+12%')
    expect(rows[1]).toHaveTextContent('Errou')
    expect(rows[1]).toHaveTextContent('Deve descer')
  })

  it('compara os níveis e filtra por nível', async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL) => Promise<Response>>(async () => Response.json(accuracyPage))
    vi.stubGlobal('fetch', fetchMock)
    wrap(<AccuracyPage />, '/acertos')
    const table = await screen.findByRole('table')
    const rows = within(table).getAllByRole('row')
    expect(rows[1]).toHaveTextContent('Compra prioritária')
    expect(rows[1]).toHaveTextContent('100%')
    expect(rows[2]).toHaveTextContent('0%')
    expect(rows[3]).toHaveTextContent('Observar')
    expect(rows[3]).toHaveTextContent('50%')
    fireEvent.click(within(screen.getByRole('group', { name: 'Nível' })).getByRole('button', { name: 'Compra possível' }))
    await waitFor(() => expect(screen.getByTestId('route').textContent).toContain('tier=possible_buy'))
    await waitFor(() => expect(fetchMock.mock.calls.some(c => String(c[0]).includes('tier=possible_buy'))).toBe(true))
  })

  it('troca o horizonte pela URL', async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL) => Promise<Response>>(async () => Response.json(accuracyPage))
    vi.stubGlobal('fetch', fetchMock)
    wrap(<AccuracyPage />, '/acertos')
    fireEvent.click(await screen.findByRole('button', { name: '15 min' }))
    await waitFor(() => expect(screen.getByTestId('route').textContent).toContain('horizon=15m'))
    await waitFor(() => expect(fetchMock.mock.calls.some(c => String(c[0]).includes('horizon=15m'))).toBe(true))
  })
})

const plan = {
  version: 'exit-1', urgency: 'reduce', headline: 'Reduzir: vender metade e proteger o restante', sell_percent_now: 50, keep_percent: 50,
  reference_price_usd: 1, reference_kind: 'preço quando o sinal atual foi emitido', current_price_usd: 1.05, change_from_reference: 0.05,
  take_profits: [
    { label: 'Alvo +20%', price_usd: 1.2, change_from_reference: 0.2, change_from_now: 0.14, sell_percent: 30, reached: false },
    { label: 'Alvo +50%', price_usd: 1.5, change_from_reference: 0.5, change_from_now: 0.43, sell_percent: 30, reached: false },
    { label: 'Alvo +100%', price_usd: 2, change_from_reference: 1, change_from_now: 0.9, sell_percent: 40, reached: false },
  ],
  stop: { price_usd: 0.85, change_from_reference: -0.15, change_from_now: -0.19, sell_percent: 100, reached: false },
  triggers: ['Vender tudo se o preço cair abaixo de US$ 0.85'], reasons: ['Risco alto para manter a posição inteira'], has_position: false,
  freshness: { observed_at: '2026-10-29T12:00:00Z', age_seconds: 192, status: 'delayed', source: 'dexscreener', source_status: 'ok' },
  live: { status: 'off', source: 'jupiter_price', interval_seconds: 10, observed_at: null, age_seconds: null, price_usd: null, liquidity_usd: null,
          note: 'Atualização rápida desligada: mostrando o preço do coletor (atualiza a cada ~30–60 s).', rules_version: 'live-1' },
  generated_at: '2026-10-29T12:03:12Z', disclaimer: 'Plano automático.',
}
const livePlan = (observed: string) => ({ ...plan, live: { ...plan.live, status: 'live', observed_at: observed, age_seconds: 1, price_usd: 1.05, liquidity_usd: 1000, note: 'Preço ao vivo.' } })

describe('painel Quando vender', () => {
  it('diz em uma frase o que fazer agora, e o passo a passo fica guardado', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json(plan)))
    wrap(<SellPlanPanel chainId="solana" address={token.address} />)
    expect(await screen.findByText('Venda 50% agora')).toBeInTheDocument()
    const panel = screen.getByRole('region', { name: 'Quando vender' })
    expect(panel).toHaveTextContent('Risco alto para manter a posição inteira')
    expect(panel).toHaveTextContent('Se o preço subir até')
    expect(panel).toHaveTextContent('venda 30% do que você tinha')
    expect(panel).toHaveTextContent('Se o preço cair até')
    expect(panel).toHaveTextContent('Atualizado há')
  })

  it('segure quando não há motivo para vender', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ ...plan, urgency: 'hold', sell_percent_now: 0, keep_percent: 100, reasons: [] })))
    wrap(<SellPlanPanel chainId="solana" address={token.address} />)
    expect(await screen.findByText('Segure')).toBeInTheDocument()
  })

  it('mostra AO VIVO com a idade do preço rápido', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json(livePlan(new Date().toISOString()))))
    wrap(<SellPlanPanel chainId="solana" address={token.address} />)
    expect(await screen.findByText('AO VIVO')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Quando vender' })).toHaveTextContent('preço a cada 10 s')
  })

  it('avisa quando o ao vivo está desligado', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json(plan)))
    wrap(<SellPlanPanel chainId="solana" address={token.address} />)
    expect(await screen.findByText('AO VIVO DESLIGADO')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Quando vender' })).toHaveTextContent('mostrando o preço do coletor')
  })

  it('golpe ao vivo vira "vender tudo" com o motivo claro', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ ...livePlan(new Date().toISOString()), urgency: 'sell_now', sell_percent_now: 100, keep_percent: 0,
      reasons: ['Liquidez retirada agora: caiu 90% em 2 min — padrão de golpe (rug pull)'] })))
    wrap(<SellPlanPanel chainId="solana" address={token.address} />)
    expect(await screen.findByText('Venda tudo agora')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Quando vender' })).toHaveTextContent('Golpe')
  })

  it('moeda aberta consulta a cada 1 s', () => {
    expect(nextPollMs()).toBe(1_000)
  })

  it('formata idade em minutos e segundos', () => {
    const base = Date.parse('2026-10-29T12:03:12Z')
    expect(ageText('2026-10-29T12:00:00Z', base)).toBe('há 3 min 12 s')
    expect(ageText('2026-10-29T12:03:00Z', base)).toBe('há 12 s')
    expect(ageText('2026-10-29T10:00:00Z', base)).toBe('há 2 h 3 min')
    expect(ageText(null, base)).toBe('sem dados')
  })
})
