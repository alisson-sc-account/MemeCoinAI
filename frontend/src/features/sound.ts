// Som de alerta gerado pelo próprio navegador (Web Audio): sem arquivo de áudio e sem serviço externo.
// Navegadores só liberam áudio depois de uma interação do usuário na página; por isso o
// contexto é criado/retomado no primeiro clique ou tecla (o login já conta como interação).

const PREF_KEY = 'mcai-sound'
let ctx: AudioContext | null = null

function context(): AudioContext | null {
  if (typeof window === 'undefined' || !('AudioContext' in window)) return null
  if (!ctx) ctx = new AudioContext()
  return ctx
}

export function unlockAudioOnFirstInteraction() {
  const unlock = () => { void context()?.resume().catch(() => undefined) }
  window.addEventListener('pointerdown', unlock, { once: true, capture: true })
  window.addEventListener('keydown', unlock, { once: true, capture: true })
}

export function soundEnabled(): boolean {
  try { return localStorage.getItem(PREF_KEY) !== 'off' } catch { return true }
}

export function setSoundEnabled(on: boolean) {
  try { localStorage.setItem(PREF_KEY, on ? 'on' : 'off') } catch { /* armazenamento indisponível */ }
}

const TONES: Record<string, number[]> = {
  buy: [880, 1320],
  sell: [660, 440],
  // Disparo: sequência rápida e subindo, repetida, para chamar atenção na hora.
  burst: [988, 1319, 1760, 988, 1319, 1760],
}

/** Compra: dois bipes subindo. Venda: descendo (graves). Disparo: rajada subindo. */
export function playAlertSound(kind: 'buy' | 'sell' | 'burst' = 'buy'): boolean {
  if (!soundEnabled()) return false
  const ac = context()
  if (!ac || ac.state !== 'running') return false
  const tones = TONES[kind] ?? TONES.buy
  const gap = kind === 'burst' ? 0.13 : 0.22
  const start = ac.currentTime + 0.02
  tones.forEach((freq, i) => {
    const t = start + i * gap
    const osc = ac.createOscillator()
    const gain = ac.createGain()
    osc.type = 'sine'
    osc.frequency.value = freq
    gain.gain.setValueAtTime(0.0001, t)
    gain.gain.exponentialRampToValueAtTime(0.25, t + 0.02)
    gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.2)
    osc.connect(gain).connect(ac.destination)
    osc.start(t)
    osc.stop(t + 0.21)
  })
  return true
}
