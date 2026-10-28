# Design system — MemeCoinAI

Tema único **escuro**. Sem degradês, sem neon, sem sombras decorativas, sem animações além de transições de 120 ms em hover/foco. A cor serve para semântica (risco, oportunidade, estado dos dados), nunca para decoração.

## Tokens de cor (CSS custom properties em `src/styles/tokens.css`)

| Token | Valor | Uso |
|---|---|---|
| `--bg` | `#0A0A0A` | fundo da aplicação |
| `--surface-1` | `#111111` | cards, sidebar, tabelas |
| `--surface-2` | `#171717` | hover de linha, inputs, cabeçalho de tabela |
| `--surface-3` | `#1F1F1F` | elementos selecionados, popovers |
| `--border` | `#262626` | bordas padrão (1 px) |
| `--border-strong` | `#3A3A3A` | bordas de inputs e divisores |
| `--text` | `#EDEDED` | texto principal |
| `--text-muted` | `#A3A3A3` | rótulos, texto secundário |
| `--text-subtle` | `#8A8A8A` | metadados (mín. 4,5:1 sobre `--surface-1`) |
| `--focus` | `#7AA2F7` | anel de foco (2 px, offset 2 px) |
| `--risk-critical` | `#F04438` | risco crítico, erro |
| `--risk-high` | `#F97316` | risco alto |
| `--risk-moderate` | `#EAB308` | risco moderado, aviso |
| `--risk-low` | `#22C55E` | risco baixo, sucesso |
| `--opportunity` | `#38BDF8` | score/alertas de oportunidade |
| `--info` | `#93A4C3` | severidade info, alertas de sistema |
| `--stale` | `#B4A7D6` | dados `delayed`/`stale`/`no_data` |
| `--positive` / `--negative` | `#22C55E` / `#F04438` | variação de preço |

Cores semânticas aparecem como **texto, borda esquerda de 3 px ou ponto de 8 px**, nunca como fundo cheio. Badges: fundo `color-mix(in srgb, <cor> 14%, transparent)` com texto na cor. A cor nunca é o único indicador: sempre acompanha texto ("Crítico", "Desatualizado") ou ícone.

## Tipografia

- Família: `Inter` (pacote `@fontsource/inter`, auto-hospedado; pesos 400/500/600), fallback `system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`.
- Monoespaçada (endereços, hashes): `"JetBrains Mono"` (`@fontsource/jetbrains-mono` 400), fallback `ui-monospace, Consolas, monospace`.
- Números: `font-variant-numeric: tabular-nums` em tabelas, KPIs e preços.

| Estilo | Tamanho / altura de linha / peso |
|---|---|
| `display` (KPI) | 28 / 34 / 600 |
| `h1` (título da página) | 22 / 28 / 600 |
| `h2` (título de seção/card) | 16 / 22 / 600 |
| `body` | 14 / 20 / 400 |
| `small` | 13 / 18 / 400 |
| `caption` (metadados, eixos) | 12 / 16 / 500 |

## Espaçamento, bordas, elevação

- Escala (px): 4, 8, 12, 16, 24, 32, 48. Padding de card: 16 (≥ 768 px: 20). Gap do grid: 16.
- Raio: 6 px (cards, modais), 4 px (botões, inputs, badges).
- Borda: 1 px `--border`. Sombra **somente** em modal/drawer: `0 8px 24px rgba(0,0,0,.5)`.

## Breakpoints

| Nome | Largura | Layout |
|---|---|---|
| `xs` | < 640 | 1 coluna; top bar com botão de menu; sidebar como drawer |
| `sm` | 640–767 | 1–2 colunas de cards |
| `md` | 768–1023 | sidebar como trilho de ícones (64 px) com tooltip e `aria-label` |
| `lg` | 1024–1279 | sidebar completa (232 px); grid de 12 colunas |
| `xl` | ≥ 1280 | conteúdo com largura máxima de 1440 px, centralizado |

## Componentes

| Componente | Especificação |
|---|---|
| `Button` | variantes `primary` (fundo `#EDEDED`, texto `#0A0A0A`), `secondary` (borda `--border-strong`, fundo transparente), `ghost`, `danger` (texto `--risk-critical`, borda). Altura 36 px (toque ≥ 44 px em `xs`: padding vertical extra). Estados: hover (`--surface-2`), foco (anel `--focus`), desabilitado (opacidade 0,5 + `title`/texto com o motivo), carregando (spinner de 14 px + texto mantido, `aria-busy`). |
| `Input`/`Select` | altura 36, fundo `--surface-2`, borda `--border-strong`, foco com anel; label sempre visível acima; erro em `--risk-critical` abaixo do campo. |
| `Card` | `--surface-1`, borda, raio 6. Cabeçalho: título `h2` + metadado à direita (ex.: "atualizado há 2 min"). |
| `KpiCard` | rótulo `caption` muted, valor `display`, rodapé `small` (contexto/frescor). Valor `null` → "—" e texto "sem dados". |
| `Badge` | `RiskBadge` (low/moderate/high/critical, rótulos PT: Baixo/Moderado/Alto/Crítico), `SeverityBadge` (Info/Baixa/Média/Alta/Crítica), `FreshnessBadge` (Atualizado/Atrasado/Desatualizado/Sem dados), `StatusBadge` de alerta (Aberto/Reconhecido/Resolvido), `CalibrationBadge` ("Não calibrado"). |
| `ScoreMeter` | barra horizontal de 0–100 (altura 6 px, trilho `--surface-3`) + número; cor pelo nível; mostra a confiança como texto ("confiança 65%"). Nunca em formato circular. |
| `Address` | monoespaçada, abreviada `Dez…B263` (6+4); botão copiar (`aria-label="Copiar endereço"`) com confirmação "Copiado"; endereço completo no `title`. |
| `Timestamp` | relativo ("há 3 min") + absoluto local no `title` e no `<time dateTime>`. |
| `DataTable` | ver FRONTEND_SPEC §Tabelas. |
| `EmptyState`, `ErrorState`, `Skeleton` | ver FRONTEND_SPEC §Estados. |
| `Modal`/`Drawer` | máx. `min(560px, 100vw − 32px)`; `max-height: 100dvh − 32px` com rolagem interna; focus trap; `Esc` fecha; foco volta ao gatilho. Em `xs`, o drawer ocupa a tela inteira. |
| `Toast` | canto inferior direito (em `xs`: inferior, largura total − 16 px); some em 5 s; erros persistem até fechar; `role="status"` (erro: `role="alert"`). |

## Gráficos (lightweight-charts)

- Fundo transparente; grade `#1A1A1A`; eixos em `--text-subtle` 12 px; crosshair `#3A3A3A`.
- Preço: linha 2 px `#EDEDED`. Liquidez: linha 1,5 px `--opportunity`. Volume 1h (janela móvel): histograma `#3A3A3A`.
- Sem área preenchida com degradê (permitido apenas `lineSeries`/`histogramSeries`).
- Formatação de preço com dígitos significativos (ver FRONTEND_SPEC §Formatação).
- Altura: 280 px (≥ 768), 220 px (< 768). Redimensiona com `ResizeObserver`.

## Ícones

`lucide-react`, tamanho 16 (navegação 18), `stroke-width` 1.75, cor herdada.
