import { useState } from 'react'

export const THEMES = [
  { id: 'memecoinai', label: 'MemeCoinAI', hint: 'Preto, verde e vermelho da marca' },
  { id: 'classic', label: 'Clássico', hint: 'O tema cinza original' },
] as const
export type ThemeId = (typeof THEMES)[number]['id']
const KEY = 'mcai-theme'

export function readTheme(): ThemeId {
  try { const t = localStorage.getItem(KEY); return THEMES.some(x => x.id === t) ? (t as ThemeId) : 'memecoinai' } catch { return 'memecoinai' }
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
