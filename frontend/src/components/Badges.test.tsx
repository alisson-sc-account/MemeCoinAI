import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { FreshnessBadge, RiskBadge } from '../ui'

describe('badges semânticos', () => {
  it('explica os quatro estados de frescor', () => {
    for (const [status, expected] of [['fresh','Atualizado'],['delayed','Atrasado'],['stale','Desatualizado'],['no_data','Sem dados']] as const) {
      const { unmount } = render(<FreshnessBadge data={{ status, observed_at: null, age_seconds: null, source: 'dexscreener', source_status: 'ok' }} />)
      expect(screen.getByText(new RegExp(expected))).toBeInTheDocument(); unmount()
    }
  })
  it('exibe o nível de risco em texto', () => { render(<RiskBadge level="critical" score={92}/>) ; expect(screen.getByText('Crítico · 92')).toBeInTheDocument() })
})
