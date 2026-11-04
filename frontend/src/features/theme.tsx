import { useState } from 'react'

export const THEMES = [
  { id: 'pro', label: 'MemeCoinAI (padrão)', hint: 'Preto neutro, decisões em cartões coloridos, igual à janela de venda' },
  { id: 'memecoinai', label: 'Marca (antigo)', hint: 'Preto, verde e vermelho do primeiro logo' },
  { id: 'classic', label: 'Clássico', hint: 'O tema cinza original' },
] as const
export type ThemeId = (typeof THEMES)[number]['id']
const KEY = 'mcai-theme'

export function readTheme(): ThemeId {
  try { const t = localStorage.getItem(KEY); return THEMES.some(x => x.id === t) ? (t as ThemeId) : 'pro' } catch { return 'pro' }
}

export function applyTheme(t: ThemeId = readTheme()) {
  document.documentElement.dataset.theme = t
}

export function ThemeSettings() {
  const [theme, setTheme] = useState(readTheme)
  const pick = (t: ThemeId) => { setTheme(t); try { localStorage.setItem(KEY, t) } catch { /* sem armazenamento */ } applyTheme(t) }
  return <div style={{ display: 'grid', gap: 8 }}>
    {THEMES.map(t => <label key={t.id} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
      <input type="radio" name="theme" checked={theme === t.id} onChange={() => pick(t.id)}/> <b>{t.label}</b> <span className="muted">{t.hint}</span>
    </label>)}
  </div>
}
