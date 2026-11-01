import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { App } from '../App'
import { BuyNowPage, signalTime } from './buynow'

vi.mock('./sound', () => ({ playAlertSound: vi.fn(() => true), soundEnabled: () => true, setSoundEnabled: vi.fn(), unlockAudioOnFirstInteraction: vi.fn() }))

function LocationProbe() { const l = useLocation(); return <output data-testid="route">{l.pathname + l.search}</output> }
const freshness = { observed_at: '2026-10-29T12:00:00Z', age_seconds: 10, status: 'fresh', source: 'dexscreener', source_status: 'ok' }
const opp = (address: string, symbol: string, tier: string, extra: Record<string, unknown> = {}) => ({
  token: { chain_id: 'solana', address, symbol, name: symbol, image_url: null }, link: `/tokens/solana/${address}`,
  tier, tier_label: { priority_buy: 'Compra prioritária', possible_buy: 'Compra possível', watch: 'Observar', avoid: 'Evitar' }[tier],
  decision_quality: 'partial', decision_quality_reason: 'Análise parcial', score: 62, score_previous: 55, score_change: 7,
  confidence: 0.6, coverage: 0.75, risk_score: 20, risk_level: 'low', critical_blocks: [], reasons_for: ['Volume acelerando'],
  reasons_against: ['Liquidez moderada'], missing_data: ['Sinais sociais'], price_usd: 0.001, price_change_h1: 5, price_change_h24: 12,
  liquidity_usd: 80000, volume_h24: 120000, pair_age_hours: 30, dex_id: 'raydium', freshness, signal_headline: null,
  signal_since: null, allocation: null, computed_at: '2026-10-29T12:00:00Z', ranking_version: 'rank-1', ...extra,
})
const page = {
  items: [opp('Aaaa1111111111111111111111111111111111111111', 'AAA', 'priority_buy'),
          opp('Bbbb1111111111111111111111111111111111111111', 'BBB', 'possible_buy'),
          opp('Cccc1111111111111111111111111111111111111111', 'CCC', 'watch', { decision_quality: 'no_reliable_signal' })],
  total: 3, page: 1, page_size: 60, counts: { priority_buy: 1, possible_buy: 1, watch: 1, avoid: 2 },
  generated_at: '2026-10-29T12:00:00Z', ranking_version: 'rank-1', disclaimer: 'Classificação informativa.',
}
function wrap(ui: React.ReactNode, route = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[route]}>{ui}<LocationProbe /></MemoryRouter></QueryClientProvider>)
}
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('Compre agora', () => {
  it('mostra vários tokens com nível, score, confiança e cobertura separados', async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL) => Promise<Response>>(async () => Response.json(page))
    vi.stubGlobal('fetch', fetchMock)
    wrap(<BuyNowPage />, '/compre-agora')
    const cards = await screen.findAllByRole('link', { name: /Compra|Observar|Evitar/ })
    expect(cards).toHaveLength(3)
    const first = within(cards[0])
    expect(first.getByText('Compra prioritária')).toBeInTheDocument()
    expect(cards[0]).toHaveTextContent('Score 62')
    expect(cards[0]).toHaveTextContent('Confiança 60%')
    expect(cards[0]).toHaveTextContent('Cobertura 75%')
    expect(cards[2]).toHaveTextContent('Sem sinal confiável')
    expect(String(fetchMock.mock.calls[0][0])).toContain('tier=priority_buy&tier=possible_buy&tier=watch')
  })

  it('filtro de nível vai para a URL e para a consulta', async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL) => Promise<Response>>(async () => Response.json(page))
    vi.stubGlobal('fetch', fetchMock)
    wrap(<BuyNowPage />, '/compre-agora')
    fireEvent.click(await screen.findByRole('button', { name: /Evitar/ }))
    await waitFor(() => expect(screen.getByTestId('route').textContent).toContain('tier=avoid'))
    await waitFor(() => expect(fetchMock.mock.calls.some(c => String(c[0]).includes('tier=avoid'))).toBe(true))
  })

  it('mostra bloqueio crítico e erro da API', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ ...page, items: [opp('Dddd1111111111111111111111111111111111111111', 'DDD', 'avoid', { critical_blocks: ['Autoridade de mint ativa'] })] })))
    wrap(<BuyNowPage />, '/compre-agora')
    expect(await screen.findByText(/Bloqueio: Autoridade de mint ativa/)).toBeInTheDocument()
    cleanup()
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ error: { code: 'x', message: 'Falhou' } }, { status: 500 })))
    wrap(<BuyNowPage />, '/compre-agora')
    expect(await screen.findByRole('alert')).toHaveTextContent('Falhou')
  })
})

describe('navegação principal', () => {
  it('tem exatamente quatro abas', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/auth/me')) return Response.json({ id: 1, username: 'alisson', must_change_password: false })
      if (url.includes('/opportunities')) return Response.json(page)
      return Response.json({ items: [], total: 0, page: 1, page_size: 10, sources: [] })
    }))
    wrap(<App />, '/compre-agora')
    const nav = (await screen.findAllByRole('navigation', { name: 'Navegação principal' }))[0]
    const tabs = within(nav).getAllByRole('link').map(a => a.getAttribute('aria-label'))
    expect(tabs).toEqual(['Dashboard', 'Compre agora', 'Alertas', 'Acertos', 'Favoritados', 'Configurações'])
  })
})

describe('hora do sinal', () => {
  it('mostra hora, minuto e segundo, com a data se não for hoje', () => {
    const d = new Date(2026, 9, 30, 14, 32, 7)
    expect(signalTime(d.toISOString(), new Date(2026, 9, 30, 20, 0, 0))).toBe('14:32:07')
    expect(signalTime(d.toISOString(), new Date(2026, 9, 31, 8, 0, 0))).toBe('30/10 às 14:32:07')
    expect(signalTime(null)).toBeNull()
  })
})
