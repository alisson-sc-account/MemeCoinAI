import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { FavoritesPage, FavoriteStar } from './favorites'

function wrap(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>)
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

const address = 'Aaaa1111111111111111111111111111111111111111'
const fav = {
  id: 7, token: { chain_id: 'solana', address, symbol: 'AAA', name: 'AAA', image_url: null }, link: `/tokens/solana/${address}`, signal_id: 3,
  action: 'buy', strength: 'strong', tier_label: 'Compra prioritária', prediction: 'Deve subir', headline: 'h', reasons: [],
  signal_at: '2026-10-30T10:00:00Z', favorited_at: '2026-10-30T11:00:00Z', seconds_signal_to_favorite: 3600,
  reference_price_usd: 1, price_at_favorite: 1.5, gain_at_favorite: 0.5, max_gain_until_favorite: 0.6, min_gain_until_favorite: -0.1,
  value_of_100_usd_at_favorite: 150, liquidity_at_favorite: 1000, specs: {},
}
const page = (items: unknown[]) => ({ items, generated_at: '2026-10-30T12:00:00Z', rules_version: 'fav-1', disclaimer: 'Ganhos brutos.',
  summary: { count: items.length, with_gain: items.length, positive: items.length, negative: 0, avg_gain_at_favorite: items.length ? 0.5 : null, best_gain: items.length ? 0.5 : null, best_symbol: 'AAA', worst_gain: items.length ? 0.5 : null, worst_symbol: 'AAA' } })

describe('Favoritados', () => {
  it('mostra só o ganho congelado no clique', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json(page([fav]))))
    wrap(<FavoritesPage />)
    expect(await screen.findByText('Ganho no clique')).toBeInTheDocument()
    expect(screen.getAllByText('+50%').length).toBeGreaterThan(0)
    expect(screen.queryByText('Ganho agora')).toBeNull()
  })

  it('copia o relatório completo', async () => {
    const writeText = vi.fn(async () => undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    vi.stubGlobal('fetch', vi.fn(async (u: RequestInfo | URL) => Response.json(String(u).includes('/report') ? { text: 'RELATORIO', count: 1, generated_at: 'x' } : page([fav]))))
    wrap(<FavoritesPage />)
    await screen.findByText('Ganho no clique')
    fireEvent.click(screen.getByRole('button', { name: 'Copiar resultados e especificações' }))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('RELATORIO'))
    expect(await screen.findByText('Copiado!')).toBeInTheDocument()
  })

  it('mostra o texto quando o navegador bloqueia a cópia', async () => {
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn(async () => { throw new Error('bloqueado') }) } })
    vi.stubGlobal('fetch', vi.fn(async (u: RequestInfo | URL) => Response.json(String(u).includes('/report') ? { text: 'RELATORIO', count: 1, generated_at: 'x' } : page([fav]))))
    wrap(<FavoritesPage />)
    await screen.findByText('Ganho no clique')
    fireEvent.click(screen.getByRole('button', { name: 'Copiar resultados e especificações' }))
    expect(await screen.findByDisplayValue('RELATORIO')).toBeInTheDocument()
  })

  it('sem favoritos explica como usar e não deixa copiar', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json(page([]))))
    wrap(<FavoritesPage />)
    expect(await screen.findByText(/Nenhuma previsão favoritada/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Copiar resultados e especificações' })).toBeDisabled()
  })

  it('estrela favorita a previsão exibida', async () => {
    const fetchMock = vi.fn(async (_u: RequestInfo | URL, init?: RequestInit) => init?.method === 'POST' ? Response.json(fav, { status: 201 }) : Response.json(page([])))
    vi.stubGlobal('fetch', fetchMock)
    wrap(<FavoriteStar chainId="solana" address={address} signalId={3} symbol="AAA" />)
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    fireEvent.click(await screen.findByRole('button', { name: 'Favoritar previsão de AAA' }))
    await waitFor(() => {
      const post = fetchMock.mock.calls.find(c => c[1]?.method === 'POST')
      expect(JSON.parse(String(post?.[1]?.body))).toEqual({ chain_id: 'solana', address, signal_id: 3 })
    })
  })

  it('estrela acesa de outra previsão do mesmo token não conta', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json(page([fav]))))
    wrap(<FavoriteStar chainId="solana" address={address} signalId={99} symbol="AAA" />)
    await waitFor(() => expect(screen.getByRole('button')).toHaveAttribute('aria-pressed', 'false'))
    cleanup()
    wrap(<FavoriteStar chainId="solana" address={address} signalId={3} symbol="AAA" />)
    expect(await screen.findByRole('button', { name: 'Remover AAA dos favoritados' })).toHaveAttribute('aria-pressed', 'true')
  })
})
