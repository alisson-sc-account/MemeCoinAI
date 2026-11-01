import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { packBubbles } from './bubbles'
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
  it('mostra veredito, itens, mapa e limitações', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json(report)))
    wrap(<SecurityPanel chainId="solana" address="X" />)
    expect(await screen.findByText('Perigo')).toBeInTheDocument()
    expect(screen.getByText('Não compre: há sinais de golpe.')).toBeInTheDocument()
    expect(screen.getByText(/0% travada/)).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Mapa das 3 maiores carteiras' })).toBeInTheDocument()
    expect(screen.getByText(/golpes novos passam despercebidos/)).toBeInTheDocument()
  })

  it('nunca diz que é seguro', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ ...report, verdict: 'clear', label: 'Sem alertas', checks: [], holders: [] })))
    wrap(<SecurityPanel chainId="solana" address="X" />)
    expect(await screen.findByText(/Isso não garante que é segura/)).toBeInTheDocument()
  })

  it('golpe aparece com o motivo', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ ...report, rugged_at: new Date().toISOString(), rug_reason: 'preço caiu 98%' })))
    wrap(<SecurityPanel chainId="solana" address="X" />)
    expect(await screen.findByText('Golpe detectado: preço caiu 98%.')).toBeInTheDocument()
  })

  it('avisa quando o processo de segurança está parado', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ ...report, verdict: 'unknown', label: 'Sem dados', checked_at: null, service_running: false, checks: [], holders: [] })))
    wrap(<SecurityPanel chainId="solana" address="X" />)
    expect(await screen.findByText(/Verificação de segurança parada/)).toBeInTheDocument()
  })
})

describe('mapa de bolhas', () => {
  it('não sobrepõe bolhas e a maior fica maior', () => {
    const { circles } = packBubbles([20, 5, 5, 3, 2, 1, 1, 1, 0.5, 0.5])
    expect(circles[0].r).toBeGreaterThan(circles[1].r)
    for (let a = 0; a < circles.length; a++) for (let b = a + 1; b < circles.length; b++) {
      expect(Math.hypot(circles[a].x - circles[b].x, circles[a].y - circles[b].y)).toBeGreaterThanOrEqual(circles[a].r + circles[b].r)
    }
  })

  it('aceita lista vazia', () => {
    expect(packBubbles([]).circles).toEqual([])
  })
})
