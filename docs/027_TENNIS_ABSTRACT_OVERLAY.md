# LOTE J — TENNIS ABSTRACT INCREMENTAL OVERLAY

## 1. Arquitetura

O **Lote J** implementa uma camada operacional de atualização recente sob demanda (**Incremental Overlay**) para os jogadores ativos no Radar do Dia, reduzindo o intervalo de defasagem (*staleness*) pós-cutoff oficial (`25/05/2026`) sem tocar ou corromper a base histórica congelada de Jeff Sackmann.

```
       [ BASE OFICIAL CONGELADA ]
       (data/processed/{tour}/matches.parquet)
       (Cutoff: 25/05/2026 — Intocada)
                    │
                    │  (Leitura isolada em memória)
                    ▼
     [ OVERLAY TENNIS ABSTRACT ]
     (data/processed/incremental_overlays/tennis_abstract/)
                    │
                    ├──> Normalização existente (Fase 2)
                    ├──> Validação estrita dos 9 campos críticos
                    ├──> Deduplicação e resolução canônica
                    │
                    ▼
       [ HISTÓRICO EFETIVO EM MEMÓRIA ]
       (get_effective_matches: Base + Overlay - Dupes)
                    │
                    ├──> Point-in-time anti-leakage
                    ├──> Cálculo de features operacionais
                    ▼
         [ RADAR DO DIA / PWA ]
         (TENNIS_RADAR_TA_OVERLAY_ENABLED)
```

### Princípios Arquiteturais Centrais
1. **Preservação Absoluta da Base Oficial:** Nenhuma linha de `data/processed/{atp,wta}/matches.parquet` é sobrescrita ou alterada.
2. **Armazenamento Isolado:** Os dados do overlay residem estritamente em `data/processed/incremental_overlays/tennis_abstract/{atp,wta}/matches.parquet`.
3. **Mesclagem Exclusivamente Operacional em Memória:** A combinação ocorre via função `get_effective_matches(tour)`, concatenando base histórica e overlay recente apenas para fins analíticos e de radar.
4. **Governança por Feature Toggle:** Controlado pela variável de ambiente `TENNIS_RADAR_TA_OVERLAY_ENABLED` (padrão `false`).

---

## 2. Tennis Abstract Source

Implementado na classe `TennisAbstractSource` (`src/incremental/tennis_abstract_source.py`):
- **Rotas Públicas Utilizadas:**
  - ATP: `http://www.tennisabstract.com/cgi-bin/player-classic.cgi?p={slug}`
  - WTA: `http://www.tennisabstract.com/cgi-bin/wplayer-classic.cgi?p={slug}`
  - Script complementar WTA: `https://www.tennisabstract.com/jsmatches/{slug}.js`
- **Extração Segura:** Parsing da matriz JS `matchmx` utilizando leitor CSV neutro com suporte a aspas e vírgulas aninhadas, mapeando as 47 colunas do contrato `matchhead`.

---

## 3. Cache Local

Armazenamento estruturado em `data/raw/tennis_abstract_cache/{ATP,WTA}/{slug}.json`:
- **Metadados Gravados:**
  - `player`: `{name, slug, tour}`
  - `fetched_at`: timestamp ISO 8601 UTC
  - `source_url`: URL consultada
  - `hash`: SHA-256 do payload JS bruto
  - `parser_version`: `1.0.0`
  - `total_matches`: contagem de partidas
  - `matches`: array estruturado
- **TTL Operacional:** 24 horas (`TA_CACHE_TTL_HOURS = 24.0`). Se o cache estiver dentro da validade, nenhuma chamada de rede é disparada (`cache_hit = true`).

---

## 4. Rate Limiting e Gestão de Erros

- **Intervalo de Cortesia:** Delay obrigatório de **2.5 segundos** entre requisições HTTP reais consecutivas (`TA_REQUEST_DELAY_SECONDS = 2.5`).
- **Política HTTP 429 (Rate Limit):** Interrupção imediata, registro no log e lançamento de `RateLimitError`. Não há tentativas em rajada nem retentativas agressivas.
- **Política HTTP 403 (Acesso Negado):** Fail-fast via `AccessForbiddenError`. Sem evasão, sem proxies rotativos e sem simulação de fingerprint.
- **Fallback Automático:** Quando a fonte está indisponível, o sistema recorre com segurança à base congelada com status `SOURCE_UNAVAILABLE`.

---

## 5. Mapeamento dos 9 Campos Críticos

Mapeamento exato comprovado no spike e homologado:

| Campo Estatístico | Sackmann (Winner / Loser) | Tennis Abstract (`matchhead`) |
|---|---|---|
| Aces | `w_ace` / `l_ace` | `aces` / `oaces` |
| Double Faults | `w_df` / `l_df` | `dfs` / `odfs` |
| Service Points | `w_svpt` / `l_svpt` | `pts` / `opts` |
| 1st Serve In | `w_1stIn` / `l_1stIn` | `firsts` / `ofirsts` |
| 1st Serve Won | `w_1stWon` / `l_1stWon` | `fwon` / `ofwon` |
| 2nd Serve Won | `w_2ndWon` / `l_2ndWon` | `swon` / `oswon` |
| Service Games | `w_SvGms` / `l_SvGms` | `games` / `ogames` |
| Break Points Saved | `w_bpSaved` / `l_bpSaved` | `saved` / `osaved` |
| Break Points Faced | `w_bpFaced` / `l_bpFaced` | `chances` / `ochances` |

> [!CRITICAL]
> **Regra de Exclusão por Incompletude:**
> Se qualquer um dos 9 campos estiver ausente, vazio (`""`) ou nulo para o vencedor ou perdedor, a partida é **rejeitada imediatamente** (`validation_status = "INCOMPLETE_STATS"`). NUNCA há preenchimento artificial com zero ou aproximações.

---

## 6. Identidade de Jogadores

Reutiliza o resolvedor canônico `src.incremental.identity_new.resolve_incremental_players`:
- Métodos confiáveis aceitos: `exact` e `alias`.
- Ambiguidade / sem correspondência: recebe ID sintético `NEW-<SLUG>` e é marcada para revisão, garantindo que nenhum jogador novo sobrescreva acidentalmente o ID de outro jogador.

---

## 7. Deduplicação de Partidas

Reutiliza a lógica de deduplicação por chave de contexto estável:
`tour:date:tourn:sorted(player_a, player_b):score`
- Trata duplicidades cruzadas (partidas coletadas tanto na página de A quanto de B).
- Garante unicidade absoluta antes da incorporação ao overlay.

---

## 8. Persistência e Auditoria

- Armazenamento em `data/processed/incremental_overlays/tennis_abstract/{atp,wta}/matches.parquet`.
- Trilha de auditoria persistida em `update_audit_log.jsonl` com contagens de partidas recebidas, validadas, descartadas e motivos detalhados.

---

## 9. Mesclagem Operacional (`get_effective_matches`)

A função `get_effective_matches` carrega a base oficial Sackmann e, se a flag `TENNIS_RADAR_TA_OVERLAY_ENABLED` estiver ativa, concatena o overlay em memória, deduplica e reordena cronologicamente por `[tournament_date, tourney_id, match_id, result]`.

---

## 10. Freshness por Jogador

Classificação operacional de recência em 4 estados:
- **`UPDATED`**: Jogador possui partidas válidas no overlay pós-cutoff sem pendências.
- **`PARTIAL`**: Jogador possui partidas no overlay, mas houve registros parciais ou descartados.
- **`BASE_ONLY`**: Jogador não possui partidas recentes no Tennis Abstract; base oficial Sackmann é utilizada.
- **`SOURCE_UNAVAILABLE`**: Falha de rede, timeout, HTTP 429 ou 403; fallback seguro para base Sackmann sem interrupção do sistema.

---

## 11. Fallback

Em qualquer evento adverso com a fonte externa:
1. A base histórica oficial congelada permanece ativa.
2. O Radar do Dia continua gerando projeções normais.
3. O status de recência é sinalizado com transparência.
4. Nenhuma informação fictícia é injetada.

---

## 12. Garantia Anti-Leakage (Point-in-Time)

Para uma partida em data $D$:
- Nenhuma partida com data posterior a $D$ entra na construção das janelas móveis das features (`shift(1)` / soma-até-a-linha-anterior).
- Ordenação estritamente temporal preservada no histórico combinado.

---

## 13. Golden Dataset

Validação de 41 partidas pré-cutoff no arquivo `tests/fixtures/golden_ta_sackmann.json`:
- **Resultado:** **41/41 partidas com 100.0% de igualdade exata** entre Tennis Abstract e Sackmann em todos os 9 campos estatísticos.

---

## 14. Testes Automatizados

Implementados em `tests/test_tennis_abstract_overlay.py` (23 testes):
- Cobrem parsing ATP/WTA, mapeamento dos 9 campos, cache hit/miss/expiry, rate limit, HTTP 429/403, dados incompletos, deduplicação, anti-leakage e Golden Dataset.
- **Resultado:** 23/23 testes aprovados.

---

## HOMOLOGAÇÃO CONTROLADA

Executada pelo script `scripts/homologation_tennis_abstract_overlay.py` com evidências reais salvas em `data/outputs/spikes/tennis_abstract_homologation/homologation_report.json`.

### 1. Jogadores Testados (2 ATP + 2 WTA)

| Jogador | Tour | Canonical ID | Última Partida Sackmann | Última Partida TA | Partidas TA Pós-Cutoff | Superfícies | Rejeitadas | Effective Cutoff |
|---|---|---|---|---|---|---|---|---|
| **Carlos Alcaraz** | ATP | `ATP-207989` | 2026-04-13 | 2026-08-31 | 5 | Hard | 0 | **2026-08-31** |
| **Jannik Sinner** | ATP | `ATP-206173` | 2026-05-25 | 2026-06-29 | 7 | Grass | 0 | **2026-06-29** |
| **Iga Swiatek** | WTA | `WTA-216347` | 2026-05-25 | 2026-08-31 | 19 | Grass, Hard | 0 | **2026-08-31** |
| **Aryna Sabalenka** | WTA | `WTA-214544` | 2026-05-25 | 2026-08-31 | 20 | Grass, Hard | 0 | **2026-08-31** |

- **Ganho de Recência:** De 35 dias (Sinner) até 140 dias (Alcaraz) de dados adicionais homologados.

### 2. Validação de Freshness
- `UPDATED`: Comprovado (Alcaraz, Sinner, Swiatek, Sabalenka).
- `PARTIAL`: Comprovado via simulação de inconsistência pontual.
- `BASE_ONLY`: Comprovado para jogadores sem partidas pós-cutoff.
- `SOURCE_UNAVAILABLE`: Comprovado via simulação de HTTP 429/403/timeout.

### 3. Validação de Deduplicação
- **ATP:** 12 partidas disponíveis pós-cutoff $\rightarrow$ 12 partidas únicas normalizadas incorporadas (0 duplicatas espúrias).
- **WTA:** 39 partidas disponíveis pós-cutoff $\rightarrow$ 39 partidas únicas normalizadas incorporadas (0 duplicatas espúrias).

### 4. Validação Anti-Leakage (Point-in-Time)
- **ATP (Data de avaliação: 2026-06-29):** 26.758 partidas na visão histórica pontual. Partidas posteriores à data $D$: **0**. Leakage detectado: **Falso**.
- **WTA (Data de avaliação: 2026-08-02):** 24.406 partidas na visão histórica pontual. Partidas posteriores à data $D$: **0**. Leakage detectado: **Falso**.

### 5 & 6. Comparação Base Congelada vs Overlay & Quantificação de Impacto

Comparação pareada de **1.972 linhas do Radar do Dia**:

| Métrica | Valor Obtido |
|---|---|
| Total de Linhas Comparadas | **1.972** |
| Média da Variação Absoluta de Probabilidade | **0.000889** (0.089 p.p.) |
| Mediana da Variação Absoluta | **0.000000** |
| Variação Máxima de Probabilidade | **0.040008** (4.0 p.p.) |
| Linhas que Mudaram de Classificação (`is_candidate`) | **3 linhas** (0.15%) |
| Linhas que Permaneceram Idênticas | **1.969 linhas** (99.85%) |
| Variação Média ATP | **0.000150** (0 mudanças de classificação) |
| Variação Média WTA | **0.001162** (3 mudanças de classificação) |

#### Impacto por Mercado:
- `total_aces_match`: Variação média de `0.001124`, 0 mudanças de classificação.
- `aces_player`: Variação média de `0.000889`, 1 mudança de classificação.
- `double_faults_player`: Variação média de `0.000640`, 2 mudanças de classificação.

**Conclusão Estatística:** O overlay produz ajustes marginais, contínuos e coerentes com a evolução recente dos jogadores, sem choques estruturais ou descalibração do modelo.

### 7. Teste de Fallback
- Simulação de HTTP 429: **Aprovada** (`SOURCE_UNAVAILABLE`).
- Simulação de HTTP 403: **Aprovada** (`SOURCE_UNAVAILABLE`).
- Simulação de Timeout: **Aprovada** (`SOURCE_UNAVAILABLE`).
- Simulação de Jogador Inexistente: **Aprovada** (`BASE_ONLY`).
- Integridade de Arquivos: **100% preservada**, nenhum arquivo oficial foi modificado.

### 8. Validação de Cache
- 1ª Chamada: `cache_hit = false` (busca HTTP real executada).
- 2ª Chamada (dentro de 24h): `cache_hit = true` (zero requisições de rede).
- Hash SHA-256 e `parser_version = "1.0.0"` preservados e validados.

### 9. Compliance Operacional
- Rotas 100% públicas documentadas.
- Intervalo obrigatório de 2.5s por chamada.
- Volume esperado: ~10 chamadas/dia em cache frio; 0 chamadas/dia em cache quente.
- Zero tentativas de bypass ou engenharia reversa evasiva.

### 10. Suítes de Testes
- **Testes novos do Overlay (`tests/test_tennis_abstract_overlay.py`):** 23/23 aprovados.
- **Frontend Vitest:** 76/76 aprovados.
- **Build de Produção:** Concluído com sucesso (670ms).
- **Suíte Completa Python (`pytest`):** 483 aprovados, 1 falha em teste pré-existente de contrato de API (`tests/test_radar_api.py::TestRadarTodayEndpoint::test_response_field_set_matches_schema`), decorrente da verificação de conjunto exato de campos ao adicionar `effective_data_cutoff` e `overlay_status` no schema JSON. Em cumprimento estrito à instrução (*"Se falhar algo antigo: pare e reporte antes de corrigir"*), a execução foi pausada para comunicação ao usuário.

---

## 11. Decisão Final

Classificação: **ATIVAR EXPERIMENTALMENTE**

### Justificativa:
1. **Golden Dataset:** 41/41 partidas com paridade absoluta de 100%.
2. **Base Oficial Intacta:** Zero mutações na base Sackmann.
3. **Anti-Leakage e Dedupe:** 100% validados matematicamente.
4. **Impacto Estatístico Controlado:** Apenas 0.15% de alteração de candidaturas no radar, mantendo calibração segura.
5. **Governança:** A flag `TENNIS_RADAR_TA_OVERLAY_ENABLED` permanece com default `false`, permitindo ativação seletiva para experimentos controlados.

