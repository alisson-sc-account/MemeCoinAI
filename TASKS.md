# Tarefas

Estados: não iniciado · em andamento · implementado, não verificado · validado com testes · bloqueado · parcialmente implementado.

| ID | Pri | Descrição | Critério de conclusão | Depende de | Estado |
|---|---|---|---|---|---|
| T-001 | P1 | Fundação do backend (config, DB, migração, logs, health) | testes passam; `migrate` funciona | — | validado com testes |
| T-002 | P1 | Autenticação (2 usuários, Argon2id, sessão, troca de senha, limite de login) | testes de login/logout/401/429 | T-001 | validado com testes |
| T-003 | P1 | Coletor DEX Screener (descoberta, watchlist, refresh, dedup, execuções) | testes + execução real | T-001 | validado com testes |
| T-004 | P1 | Verificações Solana mint/freeze/Token-2022 | testes + execução real | T-003 | validado com testes |
| T-005 | P1 | Scores de risco/oportunidade explicáveis | testes | T-003 | validado com testes |
| T-006 | P1 | Alertas + deduplicação + alertas de fonte | testes | T-005 | validado com testes |
| T-007 | P1 | API de tokens/alertas/previsões/dashboard/sistema | testes de integração | T-002..T-006 | validado com testes |
| T-008 | P1 | Previsões baseline + avaliação + métricas | testes | T-005 | validado com testes (modelo não calibrado) |
| T-009 | P1 | Especificação do frontend para o Codex | 6 documentos revisados | T-007 | validado (revisão documental) |
| T-010 | P1 | Frontend (Codex) | critérios de `FRONTEND_SPEC.md` §23 | T-009 + autorização do usuário | parcialmente implementado (integrado; e2e e refinamentos do CODEX_LOG pendentes) |
| T-025 | P1 | Sinais de compra/venda em destaque (modal global), estimativa por horizonte e sugestão de % com posição registrada | regras + estimativas + posição + modal, testados e verificados no navegador | — | validado com testes (regras não calibradas historicamente) |
| T-026 | P1 | Calibrar limiares dos sinais com o desempenho real (`/signals/performance`) | ≥ 100 sinais avaliados por tipo; limiares revistos com divisão temporal | coletor rodando por dias | não iniciado |
| T-027 | P2 | Página "Desempenho dos sinais" na interface (acerto por tipo/horizonte) | tela consumindo `/signals/performance` | T-026 parcial | não iniciado |
| T-011 | P1 | Worker: execução prolongada (≥ 6 h) com dados reais; conferir que previsões são avaliadas | logs + métricas com `evaluated > 0` | — | implementado, não verificado |
| T-012 | P3 | Rodar a suíte contra PostgreSQL (opcional após D-013) | testes passam em PG | PostgreSQL disponível | não iniciado |
| T-013 | P1 | Integração frontend ↔ backend + revisão do Claude | e2e login→alerta→token correto, mobile e desktop | T-010 | não iniciado |
| T-014 | P1 | Servir o build do frontend pela mesma origem em produção | `/` serve a SPA; `/api` serve a API | — | validado com testes (backend); falta o build real do Codex |
| T-015 | P2 | Concentração de holders confiável | `getTokenLargestAccounts` sem 429 + classificação de contas pool/queima | chave **gratuita** de provedor RPC criada pelo proprietário (`SOLANA_RPC_URL`) | bloqueado (aguarda conta gratuita) |
| T-016 | P2 | Retorno líquido hipotético nas métricas (slippage + custo fixo) | campo nas métricas + teste | T-008 | não iniciado |
| T-017 | P2 | Calibração do modelo / comparação com baseline | ≥ 100 avaliadas por alvo; Brier vs. baseline documentado | T-011 | não iniciado |
| T-018 | P2 | Inteligência de carteiras (compradores únicos, financiamento comum) | modelo temporal + fonte com cota | indexador/RPC (decisão) | não iniciado |
| T-019 | P2 | Registro de posição do usuário + cenários personalizados de saída | tabela, endpoints, testes | T-013 | não iniciado |
| T-020 | P1 | Escolher a VM do nível gratuito (D-013) e preparar o deploy (systemd para API + worker, backup do SQLite, proxy HTTPS gratuito) | provedor registrado em DECISIONS; health check respondendo na VM | conta gratuita criada pelo proprietário | bloqueado (aguarda conta) |
| T-024 | P2 | Script de deploy/instalação para a VM gratuita (systemd units, backup diário do SQLite com retenção) | script testado numa VM real | T-020 | não iniciado |
| T-021 | P2 | Limite de login persistente/compartilhado | limite no banco | múltiplas instâncias | não iniciado |
| T-022 | P3 | Segunda rede (EVM) com verificações próprias | método EVM documentado + testes | — | não iniciado |
| T-023 | P3 | Fonte social com acesso legítimo | fonte avaliada e documentada | — | não iniciado |
