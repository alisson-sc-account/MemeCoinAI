/** Link da moeda na Axiom (onde as compras são feitas). Formato num lugar só, para trocar fácil. */
export const axiomUrl = (address: string) => `https://axiom.trade/t/${encodeURIComponent(address)}`

export function openAxiom(address: string) {
  window.open(axiomUrl(address), '_blank', 'noopener,noreferrer')
}
