import { readCenterAlerts, wantsSignal } from './alertPrefs'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SignalWatcher } from './signals'
import { playAlertSound } from './sound'

vi.mock('./sound', () => ({ playAlertSound: vi.fn(() => true), soundEnabled: () => true, setSoundEnabled: vi.fn() }))

function LocationProbe() { const l = useLocation(); return <output data-testid="route">{l.pathname}</output> }
const token = { chain_id: 'solana', address: 'AddressExample01234567890123456789', symbol: 'TEST', name: 'Teste', image_url: null }
const empty = { items: [], total: 0, page: 1, page_size: 20 }
/** Responde vazio à consulta de disparos e devolve o payload de sinais ao resto. */
const routed = (signalsPayload: unknown) => vi.fn(async (input: RequestInfo | URL) =>
  String(input).includes('pump_burst') ? Response.json(empty) : Response.json(signalsPayload))
const onlyBurst = (payload: unknown) => vi.fn(async (input: RequestInfo | URL) =>
  String(input).includes('pump_burst') ? Response.json(payload) : Response.json(empty))

const signal = (id: number, action: string, strength: string) => ({
  id, token, action, strength, status: 'active', headline: `${action} ${strength}`, reasons: ['Motivo'], risk_score: 30,
  risk_level: 'moderate', opportunity_score: 60, reference_price_usd: 1, created_at: '2026-10-28T12:00:00Z',
  last_confirmed_at: '2026-10-28T12:00:00Z', rules_version: 'sig-1', link: `/tokens/solana/${token.address}`,
  estimates: [{ horizon: '1h', horizon_seconds: 3600, basis: 'general', n: 40, end_median: 0.12, end_p25: 0.02, end_p75: 0.3, p_up_20: 0.35, method_version: 'out-1' }],
})
const burstAlert = (id: number, stats: unknown = { n: 50, p_up_10: 0.4, p_up_20: 0.2, median_max_return: 0.08 }) => ({
  id, alert_type: 'pump_burst', category: 'opportunity', severity: 'high', status: 'open',
  title: 'Disparo agora: volume e compras acelerando', reason: 'Volume 6x o ritmo; 18 compras contra 3 vendas',
  evidence: { pattern_stats: stats }, confidence: 0.5, rule_id: 'pump_burst', rule_version: 'alerts-1',
  event_at: null, detected_at: '2026-10-28T12:00:00Z', last_occurrence_at: '2026-10-28T12:00:00Z', occurrences: 1,
  status_changed_at: null, token, pair_address: null, link: `/tokens/solana/${token.address}`,
})

function renderWatcher() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><MemoryRouter><SignalWatcher username="alisson" /><LocationProbe /></MemoryRouter></QueryClientProvider>)
}
afterEach(() => { cleanup(); vi.mocked(playAlertSound).mockClear(); localStorage.clear() })

describe('alerta de sinal no centro da tela', () => {
  it('ESC fecha o alerta', async () => {
    vi.stubGlobal('fetch', routed({ items: [signal(4, 'buy', 'strong')], total: 1, page: 1, page_size: 20 }))
    localStorage.setItem('mcai-last-signal-alisson', '1')
    renderWatcher()
    await screen.findByRole('alertdialog')
    fireEvent.keyDown(window, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull())
  })

  it('venda não abre no meio da tela por padrão', async () => {
    localStorage.removeItem('mcai-center-alerts')
    expect(wantsSignal(readCenterAlerts(), 'sell', 'strong')).toBe(false)
    expect(wantsSignal(readCenterAlerts(), 'buy', 'strong')).toBe(true)
    expect(wantsSignal(readCenterAlerts(), 'buy', 'moderate')).toBe(false)
  })

  it('na primeira visita nao abre sinais antigos', async () => {
    const fetchMock = routed({ items: [signal(5, 'buy', 'strong')], total: 1, page: 1, page_size: 20 })
    vi.stubGlobal('fetch', fetchMock)
    renderWatcher()
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    await waitFor(() => expect(localStorage.getItem('mcai-last-signal-alisson')).toBe('5'))
    expect(screen.queryByRole('alertdialog')).toBeNull()
  })

  it('abre para compra forte nova, ignora moderada e leva ao token', async () => {
    localStorage.setItem('mcai-last-signal-alisson', '1')
    vi.stubGlobal('fetch', routed({ items: [signal(3, 'buy', 'moderate'), signal(7, 'buy', 'strong')], total: 2, page: 1, page_size: 20 }))
    renderWatcher()
    const dialog = await screen.findByRole('alertdialog')
    expect(dialog).toHaveTextContent('buy strong')
    expect(dialog).toHaveTextContent('+12%')
    expect(dialog).not.toHaveTextContent('outro')
    fireEvent.click(screen.getByRole('button', { name: 'Ver token' }))
    await waitFor(() => expect(screen.getByTestId('route')).toHaveTextContent(`/tokens/solana/${token.address}`))
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(localStorage.getItem('mcai-last-signal-alisson')).toBe('7')
  })

  it('mostra quanto do saldo usar e toca o som', async () => {
    localStorage.setItem('mcai-last-signal-alisson', '1')
    const s = { ...signal(9, 'buy', 'strong'), allocation: { percent_of_balance: 10, amount: 5, currency: 'BRL', max_trade_percent: 10, rule: 'size-1' } }
    vi.stubGlobal('fetch', routed({ items: [s], total: 1, page: 1, page_size: 20 }))
    renderWatcher()
    const dialog = await screen.findByRole('alertdialog')
    // Intl usa espaco sem quebra depois de "R$": normaliza antes de comparar.
    expect(dialog.textContent?.replace(/\s/g, ' ')).toContain('Compre agora com 10% do seu saldo (R$ 5,00)')
    expect(playAlertSound).toHaveBeenCalledWith('buy')
  })

  it('nao toca som de novo para o mesmo sinal', async () => {
    localStorage.setItem('mcai-last-signal-alisson', '1')
    localStorage.setItem('mcai-center-alerts', JSON.stringify({ sell: true }))
    vi.stubGlobal('fetch', routed({ items: [signal(4, 'sell', 'strong')], total: 1, page: 1, page_size: 20 }))
    renderWatcher()
    await screen.findByRole('alertdialog')
    await new Promise(r => setTimeout(r, 50))
    expect(playAlertSound).toHaveBeenCalledTimes(1)
    expect(playAlertSound).toHaveBeenCalledWith('sell')
  })

  it('disparo abre alerta proprio, com som e historico do padrao', async () => {
    localStorage.setItem('mcai-last-burst-alisson', '1')
    localStorage.setItem('mcai-last-signal-alisson', '99')
    vi.stubGlobal('fetch', onlyBurst({ items: [burstAlert(8)], total: 1, page: 1, page_size: 10 }))
    renderWatcher()
    const dialog = await screen.findByRole('alertdialog')
    expect(dialog).toHaveTextContent('Disparo agora')
    expect(dialog).toHaveTextContent('50 disparos iguais')
    expect(dialog).toHaveTextContent('20% chegaram a +20%')
    expect(playAlertSound).toHaveBeenCalledWith('burst')
    fireEvent.click(screen.getByRole('button', { name: 'Ver token' }))
    await waitFor(() => expect(screen.getByTestId('route')).toHaveTextContent(`/tokens/solana/${token.address}`))
    expect(localStorage.getItem('mcai-last-burst-alisson')).toBe('8')
  })

  it('disparo sem historico avisa que ainda nao ha medicao', async () => {
    localStorage.setItem('mcai-last-burst-alisson', '1')
    vi.stubGlobal('fetch', onlyBurst({ items: [burstAlert(9, { n: 0 })], total: 1, page: 1, page_size: 10 }))
    renderWatcher()
    expect(await screen.findByRole('alertdialog')).toHaveTextContent('Ainda sem historico'.replace('historico', 'histórico'))
  })
})
