import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SecurityPanel } from './security'

function wrap(ui: React.ReactNode) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>)
}
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const report = {
  verdict: 'danger', label: 'Perigo', checked_at: new Date().toISOString(), rugged_at: null, rug_reason: null, total_holders: 400, service_running: true, rules_version: 'sec-1',
  limitations: ['Nenhuma verificação garante que a moeda é segura: golpes novos passam despercebidos.'],
  checks: [{ key: 'lp', label: 'Liquidez travada', status: 'danger', detail: '0% travada (raydium).' }, { key: 'fresh', label: 'Carteiras novas', status: 'unknown', detail: 'Ainda não analisadas nesta moeda.' }],
  holders: [{ owner: 'Aaaa1111111111111111111111111111', pct: 12.5, insider: true }, { owner: 'Bbbb1111111111111111111111111111', pct: 4, fresh: true, age_hours: 5 }, { owner: 'Cccc1111111111111111111111111111', pct: 1, fresh: null }],
}

describe('painel de segurança', () => {
  it('mostra o veredito e só os alertas em destaque; o resto fica guardado', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json(report)))
    wrap(<SecurityPanel chainId="solana" address="X" />)
    expect(await screen.findByText('Perigo')).toBeInTheDocument()
    expect(screen.getByText('Não compre: há sinais de golpe.')).toBeInTheDocument()
    expect(screen.getByText('Ver todas as verificações e carteiras')).toBeInTheDocument()
    expect(screen.getByText('insider')).toBeInTheDocument()
    expect(screen.getByText('nova, 5 h')).toBeInTheDocument()
    expect(screen.getByText('idade desconhecida')).toBeInTheDocument()
    expect(screen.queryByRole('img')).toBeNull()  // sem mapa de bolhas
    expect(screen.getByText(/golpes novos passam despercebidos/)).toBeInTheDocument()
  })

  it('nunca diz que é seguro', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ ...report, verdict: 'clear', label: 'Sem alertas', checks: [], holders: [] })))
    wrap(<SecurityPanel chainId="solana" address="X" />)
    expect(await screen.findByText(/Não garante que é segura/)).toBeInTheDocument()
  })

  it('golpe aparece com o motivo', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ ...report, rugged_at: new Date().toISOString(), rug_reason: 'preço caiu 98%' })))
    wrap(<SecurityPanel chainId="solana" address="X" />)
    expect(await screen.findByText('Golpe detectado: preço caiu 98%.')).toBeInTheDocument()
  })

  it('avisa quando a verificação está parada', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ ...report, verdict: 'unknown', label: 'Sem dados', checked_at: null, service_running: false, checks: [], holders: [] })))
    wrap(<SecurityPanel chainId="solana" address="X" />)
    expect(await screen.findByText('Verificação parada')).toBeInTheDocument()
  })
})
