/** Quais alertas abrem no meio da tela. Preferência deste navegador; venda fica dentro da moeda por padrão. */
export type CenterAlerts = { buy_strong: boolean; buy: boolean; sell: boolean; burst: boolean }

const KEY = 'mcai-center-alerts'
export const DEFAULT_CENTER_ALERTS: CenterAlerts = { buy_strong: true, buy: false, sell: false, burst: true }

export function readCenterAlerts(): CenterAlerts {
  try {
    const saved = localStorage.getItem(KEY)
    return saved ? { ...DEFAULT_CENTER_ALERTS, ...(JSON.parse(saved) as Partial<CenterAlerts>) } : DEFAULT_CENTER_ALERTS
  } catch {
    return DEFAULT_CENTER_ALERTS
  }
}

export function writeCenterAlerts(value: CenterAlerts) {
  try { localStorage.setItem(KEY, JSON.stringify(value)) } catch { /* armazenamento indisponível */ }
}

/** Este sinal deve abrir no meio da tela? */
export function wantsSignal(prefs: CenterAlerts, action: string, strength: string): boolean {
  if (action === 'sell') return prefs.sell
  if (action !== 'buy') return false
  return strength === 'strong' ? prefs.buy_strong : prefs.buy
}
