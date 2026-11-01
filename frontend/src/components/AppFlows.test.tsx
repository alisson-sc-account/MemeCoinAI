import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { BellMenu, FactorList, TokenExplorer } from '../App'

function LocationProbe() { const location=useLocation(); return <output data-testid="route">{location.pathname+location.search}</output> }
function wrapper(children: React.ReactNode, route = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}><MemoryRouter initialEntries={[route]}>{children}<LocationProbe/></MemoryRouter></QueryClientProvider>
}
const page = { items: [], total: 0, page: 1, page_size: 25 }
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('explorador e alertas', () => {
  it('leva filtros de busca para a query da API', async () => {
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input); calls.push(url)
      if (url.endsWith('/meta')) return Response.json({ chains: ['solana'], alert_types: {}, severities: [], risk_levels: [], token_sort_fields: ['opportunity_score'], prediction_targets: {}, engine_version: 'test', freshness_thresholds_seconds: {} })
      return Response.json(page)
    }))
    render(wrapper(<Routes><Route path="/tokens" element={<TokenExplorer/>}/></Routes>, '/tokens'))
    const input = await screen.findByRole('textbox', { name: 'Buscar token' })
    fireEvent.change(input, { target: { value: 'BONK' } })
    await waitFor(() => expect(screen.getByTestId('route').textContent).toContain('q=BONK'))
    await waitFor(() => expect(calls.some(url => url.includes('q=BONK'))).toBe(true))
  })

  it('exibe os fatores e evidencia ao expandir', () => {
    render(wrapper(<FactorList factors={[{ id:'risk-1',category:'liquidity',label:'Liquidez baixa',points:12,severity:'high',confidence:.8,evidence:{liquidity_usd:1200} }]} />))
    fireEvent.click(screen.getByText('Liquidez baixa'))
    expect(screen.getByText(/liquidity_usd/)).toBeInTheDocument()
  })

  it('abre notificação pelo link do alerta', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ items: [{ id:7,alert_type:'risk_high',category:'risk',severity:'high',status:'open',title:'Risco alto',reason:'Evidência recebida',evidence:{},confidence:.8,rule_id:'risk',rule_version:'1',event_at:null,detected_at:'2026-10-28T12:00:00Z',last_occurrence_at:'2026-10-28T12:00:00Z',occurrences:1,status_changed_at:null,token:{chain_id:'solana',address:'AddressExample01234567890123456789',symbol:'TEST',name:'Teste',image_url:null},pair_address:null,link:'/tokens/solana/AddressExample01234567890123456789' }],total:1,page:1,page_size:10 })))
    render(wrapper(<BellMenu/>))
    fireEvent.click(screen.getByRole('button', { name: /Alertas prioritários/ }))
    expect(await screen.findByText('Risco alto')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Risco alto'))
    await waitFor(() => expect(screen.getByTestId('route')).toHaveTextContent('/tokens/solana/AddressExample01234567890123456789'))
  })
})
