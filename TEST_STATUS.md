# Status dos testes

## 2026-10-28 — sessão 1 (continuação: custo zero)

| Comando | Resultado |
|---|---|
| `cd backend; .\.venv\Scripts\python.exe -m pytest` | **49 passed** (47 anteriores + 2 de `test_frontend_serving.py`: SPA, fallback de rotas do cliente, assets, proteção contra path traversal, 404 de API no formato padrão, ausência de build) |

## 2026-10-28 — sessão 1

| Comando | Resultado |
|---|---|
| `cd backend; .\.venv\Scripts\python.exe -m pytest` | **47 passed** (~20 s), 0 falhas |
| `python -m app.cli migrate` (SQLite real) | migração `0001` aplicada |
| `python -m app.cli seed-users` | 2 usuários criados (hash Argon2id verificado em teste) |
| `python -m app.cli track solana DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263` | **dados reais**: BONK, risco 30, oportunidade 12,5 (antes das verificações técnicas) |
| `python -m app.cli discover` | **dados reais**: 39 tokens adicionados (limite local 40) |
| `python -m app.cli refresh` | **dados reais**: 35 tokens com dados novos, 35 análises; 4 tokens sem par retornado pela fonte |
| `python -m app.cli checks 3` | **dados reais**: 3 mints `ok` (2 spl-token, 1 token-2022); `getTokenLargestAccounts` → **429** nos 3 |
| API via HTTP (uvicorn local) | health 200; 401 sem sessão; login OK; dashboard, filtros, detalhe, alertas OK com dados reais |

### Cobertura (resumo)
- Unitários: normalização (strings numéricas, ausentes = None, identidade, EVM/Solana), features sem vazamento temporal, scores (dados ausentes ≠ risco baixo, rede não suportada, autoridade de mint, queda de liquidez, teto de oportunidade), slippage x*y=k e mapeamento de 8 tipos de pool, HTTP (429→retry, 5xx com limite, 404 sem retry, erro de rede), parse de mint real e Token-2022, concentração.
- Integração: hash de senha, 401 em rotas protegidas, login/logout/limite/troca de senha, deduplicação de snapshots em cache, pares em que o token é quote ignorados, fonte fora → alerta de sistema → resolução, queda de liquidez → alerta crítico deduplicado, escalonamento de severidade, alteração de permissão, auto-resolução de alertas de condição, ciclo de vida da previsão (pendente → avaliada; inavaliável), API ponta a ponta, 404/502 ao adicionar, dados `stale` e agregados, limitação de persistência de análises.
- As migrações Alembic são aplicadas em todo teste (banco temporário).

### Não executado / ausente
- Suíte contra **PostgreSQL** (não instalado).
- **Worker contínuo** por horas; avaliação de previsões reais (requer ≥ 6 h de coleta).
- Testes de interface (frontend não existe).
- Testes de carga.
- Avisos conhecidos: `StarletteDeprecationWarning` (TestClient com httpx), sem impacto.
