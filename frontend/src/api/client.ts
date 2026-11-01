import type { ApiErrorBody, User, Token, TokenDetail, Alert, Prediction, Meta, Dashboard, Page, History, ExitEstimate, SystemSources, Health, PredictionMetrics, Signal, SignalPerformance, Position, AccountSettings, OpportunityPage, SourceRegistryEntry, AccuracyPage, ExitPlan, Favorite, FavoritePage, FavoriteReport, Security, AgentStatus } from './types'

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details: unknown = null) { super(message); this.name = 'ApiError' }
}

let unauthorizedHandler: (() => void) | undefined
export function setUnauthorizedHandler(handler: () => void) { unauthorizedHandler = handler }

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api/v1${path}`, { ...init, credentials: 'include', headers: { ...(init.body ? { 'Content-Type': 'application/json' } : {}), ...init.headers } })
  } catch { throw new ApiError(0, 'network_error', 'Não foi possível conectar à API.') }
  if (response.status === 204) return undefined as T
  const body: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const payload = body as ApiErrorBody | null
    const error = payload?.error
    if (response.status === 401 && error?.code === 'unauthenticated') unauthorizedHandler?.()
    throw new ApiError(response.status, error?.code ?? 'request_failed', error?.message ?? `Falha na requisição (${response.status}).`, error?.details)
  }
  return body as T
}

export const apiClient = {
  me: () => api<User>('/auth/me'),
  login: (username: string, password: string) => api<{user: User; expires_at: string}>('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) }),
  logout: () => api<void>('/auth/logout', { method: 'POST' }),
  changePassword: (current_password: string, new_password: string) => api<void>('/auth/change-password', { method: 'POST', body: JSON.stringify({ current_password, new_password }) }),
  meta: () => api<Meta>('/meta'),
  dashboard: () => api<Dashboard>('/dashboard/summary'),
  tokens: (query: string) => api<Page<Token>>(`/tokens${query ? `?${query}` : ''}`),
  token: (chain: string, address: string) => api<TokenDetail>(`/tokens/${encodeURIComponent(chain)}/${encodeURIComponent(address)}`),
  history: (chain: string, address: string, range: string) => api<History>(`/tokens/${encodeURIComponent(chain)}/${encodeURIComponent(address)}/history?range=${range}`),
  exitEstimate: (chain: string, address: string, positions?: string) => api<ExitEstimate>(`/tokens/${encodeURIComponent(chain)}/${encodeURIComponent(address)}/exit-estimate${positions ? `?positions=${encodeURIComponent(positions)}` : ''}`),
  track: (chain_id: string, address: string) => api<Token>('/tokens/track', { method: 'POST', body: JSON.stringify({ chain_id, address }) }),
  untrack: (chain: string, address: string) => api<void>(`/tokens/${encodeURIComponent(chain)}/${encodeURIComponent(address)}/track`, { method: 'DELETE' }),
  alerts: (query: string) => api<Page<Alert>>(`/alerts${query ? `?${query}` : ''}`),
  alert: (id: string) => api<Alert>(`/alerts/${encodeURIComponent(id)}`),
  updateAlert: (id: number, status: string) => api<Alert>(`/alerts/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) }),
  predictions: (query: string) => api<Page<Prediction>>(`/predictions${query ? `?${query}` : ''}`),
  metrics: (target?: string) => api<PredictionMetrics[]>(`/predictions/metrics${target ? `?target=${encodeURIComponent(target)}` : ''}`),
  sources: () => api<SystemSources>('/system/sources'),
  security: (chain: string, address: string) => api<Security>(`/tokens/${encodeURIComponent(chain)}/${encodeURIComponent(address)}/security`),
  agents: () => api<AgentStatus[]>('/system/agents'),
  favorites: () => api<FavoritePage>('/favorites'),
  favoritesReport: () => api<FavoriteReport>('/favorites/report'),
  addFavorite: (chain_id: string, address: string, signal_id: number | null) => api<Favorite>('/favorites', { method: 'POST', body: JSON.stringify({ chain_id, address, signal_id }) }),
  removeFavorite: (id: number) => api<void>(`/favorites/${id}`, { method: 'DELETE' }),
  accuracy: (query: string) => api<AccuracyPage>(`/accuracy${query ? `?${query}` : ''}`),
  exitPlan: (chain: string, address: string) => api<ExitPlan>(`/tokens/${encodeURIComponent(chain)}/${encodeURIComponent(address)}/exit-plan`),
  opportunities: (query: string) => api<OpportunityPage>(`/opportunities${query ? `?${query}` : ''}`),
  registry: () => api<SourceRegistryEntry[]>('/system/registry'),
  settings: () => api<AccountSettings>('/auth/settings'),
  saveSettings: (body: AccountSettings) => api<AccountSettings>('/auth/settings', { method: 'PUT', body: JSON.stringify(body) }),
  signals: (query: string) => api<Page<Signal>>(`/signals${query ? `?${query}` : ''}`),
  signalPerformance: () => api<SignalPerformance[]>('/signals/performance'),
  positions: () => api<Position[]>('/positions'),
  savePosition: (chain: string, address: string, quantity: number, entry_price_usd: number | null) => api<Position>(`/positions/${encodeURIComponent(chain)}/${encodeURIComponent(address)}`, { method: 'PUT', body: JSON.stringify({ quantity, entry_price_usd }) }),
  deletePosition: (chain: string, address: string) => api<void>(`/positions/${encodeURIComponent(chain)}/${encodeURIComponent(address)}`, { method: 'DELETE' }),
  health: () => api<Health>('/health'),
}
