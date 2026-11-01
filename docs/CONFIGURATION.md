# Configuração

Variáveis lidas de `backend/.env` (modelo em `backend/.env.example`, sem segredos). Gerado de `backend/app/config.py`. Reinicie (stop.bat / start.bat) para aplicar.

| Variável | Padrão | Observação |
|---|---|---|
| `ENV` | `development` |  |
| `DATABASE_URL` | `sqlite:///backend/data/memecoinai.db` | SQLite local por padrão (`backend/data/memecoinai.db`). |
| `SESSION_COOKIE_NAME` | `mcai_session` |  |
| `SESSION_TTL_HOURS` | `72` |  |
| `SESSION_COOKIE_SECURE` | `False` | Use true somente com HTTPS. |
| `SEED_USERNAMES` | `natan,alisson` |  |
| `SEED_INITIAL_PASSWORD` | `None` | Senha inicial dos usuários; só usada por `seed-users`. Nunca versionar. |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Só para o Vite em desenvolvimento; o build é servido na mesma origem. |
| `FRONTEND_DIST_DIR` | `frontend/dist` |  |
| `CHAINS` | `solana` |  |
| `MAX_TRACKED_TOKENS` | `600` | Teto do universo monitorado (20 requisições por ciclo com 600). |
| `REFRESH_INTERVAL_SECONDS` | `30` | Intervalo do ciclo de mercado; com muitos tokens o ciclo pode demorar mais que isso. |
| `DISCOVERY_INTERVAL_SECONDS` | `300` |  |
| `RISK_CHECK_INTERVAL_SECONDS` | `30` |  |
| `RISK_CHECKS_PER_CYCLE` | `6` |  |
| `EVALUATION_INTERVAL_SECONDS` | `120` |  |
| `DISCOVERY_QUERIES` | `30 termos (ver config.py)` |  |
| `DISCOVERY_QUERIES_PER_CYCLE` | `8` |  |
| `PRUNE_AFTER_HOURS` | `3` |  |
| `PRUNE_MIN_LIQUIDITY_USD` | `1500.0` |  |
| `PRUNE_MIN_VOLUME_H24_USD` | `1000.0` |  |
| `DEXSCREENER_BASE_URL` | `https://api.dexscreener.com` |  |
| `SOLANA_RPC_URL` | `https://api.mainnet-beta.solana.com` | RPC público por padrão; um RPC próprio é opcional. |
| `HTTP_TIMEOUT_SECONDS` | `15.0` |  |
| `FRESH_MAX_AGE_SECONDS` | `180` |  |
| `DELAYED_MAX_AGE_SECONDS` | `900` |  |
| `RAW_PAYLOAD_RETENTION_DAYS` | `3` |  |
| `SNAPSHOT_RETENTION_DAYS` | `90` |  |
| `SOURCE_FAILURE_THRESHOLD` | `3` |  |
| `LOG_LEVEL` | `INFO` |  |

Preferências por usuário (saldo para simulação, moeda, teto por operação) ficam no banco e são editadas na aba **Configurações**. Som dos alertas é preferência do navegador.
