import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { App } from '../App'

function LocationProbe() { const location=useLocation(); return <output data-testid="route">{location.pathname+location.search}</output> }
function renderApp(route: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[route]}><App/><LocationProbe/></MemoryRouter></QueryClientProvider>)
}
const unauthenticated = () => Response.json({ error: { code: 'unauthenticated', message: 'Sessão ausente', details: null } }, { status: 401 })
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('sessão ausente', () => {
  it('mostra o login sem recarregar nem acumular next (regressão do loop)', async () => {
    // jsdom registra "Not implemented: navigation" quando o código tenta recarregar a página inteira.
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const fetchMock = vi.fn(async () => unauthenticated())
    vi.stubGlobal('fetch', fetchMock)
    renderApp('/login')
    expect(await screen.findByRole('heading', { name: 'Entrar' })).toBeInTheDocument()
    await new Promise(resolve => setTimeout(resolve, 50))
    expect(screen.getByTestId('route').textContent).toBe('/login')
    expect(consoleError.mock.calls.flat().map(String).some(m => m.includes('navigation'))).toBe(false)
    expect(fetchMock.mock.calls.length).toBeLessThanOrEqual(2)
  })

  it('após o login volta para a rota de next', async () => {
    let logged = false
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/auth/login')) { logged = true; return Response.json({ user: { id: 1, username: 'alisson', must_change_password: false }, expires_at: '2026-10-31T00:00:00Z' }) }
      if (url.endsWith('/auth/me')) return logged ? Response.json({ id: 1, username: 'alisson', must_change_password: false }) : unauthenticated()
      return Response.json({ items: [], total: 0, page: 1, page_size: 25 })
    }))
    renderApp('/login?next=%2Falerts%3Fstatus%3Dopen')
    fireEvent.change(await screen.findByLabelText('Usuário'), { target: { value: 'alisson' } })
    fireEvent.change(screen.getByLabelText('Senha'), { target: { value: 'x' } })
    fireEvent.click(screen.getByRole('button', { name: 'Entrar' }))
    await waitFor(() => expect(screen.getByTestId('route').textContent).toBe('/alerts?status=open'))
  })

  it('redireciona rota protegida para o login uma única vez', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => unauthenticated()))
    renderApp('/alerts?status=open')
    expect(await screen.findByRole('heading', { name: 'Entrar' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('route').textContent).toBe('/login?next=%2Falerts%3Fstatus%3Dopen'))
  })
})
