import { describe, expect, it } from 'vitest'
import { fraction, percent, price, usd } from './format'

describe('formatadores pt-BR', () => {
  it('usa traço para valores indisponíveis', () => { expect(usd(null)).toBe('—'); expect(percent(undefined)).toBe('—'); expect(price(null)).toBe('—') })
  it('formata USD compacto e percentuais assinados', () => { expect(usd(1_180_000)).toContain('mi'); expect(percent(4.23)).toBe('+4,23%'); expect(percent(-4.23)).toBe('-4,23%') })
  it('formata frações como porcentagem', () => { expect(fraction(0.65)).toBe('65%') })
  it('usa zeros subscritos sem vírgula na mantissa', () => { expect(price(0.000003175)).toBe('US$ 0,0₅3175'); expect(price(0.00006814)).toBe('US$ 0,0₄6814'); expect(price(0.00005)).toBe('US$ 0,0₄5') })
})
