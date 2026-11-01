import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, setUnauthorizedHandler } from './client'

afterEach(() => { vi.restoreAllMocks(); setUnauthorizedHandler(() => undefined) })
describe('cliente da API', () => {
  it('inclui credenciais e traduz erros do contrato', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ error: { code: 'invalid_credentials', message: 'Usuário ou senha inválidos', details: null } }), { status: 401 }))
    await expect(api('/auth/login')).rejects.toMatchObject({ code: 'invalid_credentials', status: 401 })
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ credentials: 'include' })
  })
  it('chama o handler em sessão expirada', async () => {
    const handler = vi.fn(); setUnauthorizedHandler(handler)
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ error: { code: 'unauthenticated', message: 'Sessão expirada' } }), { status: 401 }))
    await expect(api('/auth/me')).rejects.toBeInstanceOf(ApiError)
    expect(handler).toHaveBeenCalledOnce()
  })
})
