export type Circle = { x: number; y: number; r: number }

/** Posiciona as bolhas em espiral, da maior para a menor, sem sobrepor. Área proporcional ao valor. */
export function packBubbles(values: number[], width = 420, height = 300): { width: number; height: number; circles: Circle[] } {
  const scale = values.length ? 62 / Math.sqrt(Math.max(...values, 0.0001)) : 1
  const order = values.map((v, i) => ({ v, i })).sort((a, b) => b.v - a.v)
  const placed: Circle[] = []
  const circles: Circle[] = values.map(() => ({ x: 0, y: 0, r: 0 }))
  for (const { v, i } of order) {
    const r = Math.max(5, Math.sqrt(Math.max(v, 0)) * scale)
    let angle = 0
    let x = width / 2
    let y = height / 2
    // Passo pequeno e limite alto: sempre encontra lugar; a bolha pode sair do quadro só com dezenas de carteiras.
    for (let step = 0; step < 4000; step++) {
      const distance = 1.6 * angle
      x = width / 2 + distance * Math.cos(angle) * 1.3
      y = height / 2 + distance * Math.sin(angle) * 0.85
      if (placed.every(p => Math.hypot(p.x - x, p.y - y) >= p.r + r + 2)) break
      angle += 0.12
    }
    const circle = { x, y, r }
    placed.push(circle)
    circles[i] = circle
  }
  return { width, height, circles }
}
