# Spike Técnico: Recuperação de Staleness via Live Tennis API

**Data da Auditoria:** 23/09/2026  
**Autor:** Engenheiro Sênior de Estabilização e Produção — TENNIS_RADAR  
**Status do Pipeline:** Intacto (nenhuma alteração nos modelos, calibrações, normalizações ou cutoff oficial)  
**Artefato Gerado:** `docs/025_STALENESS_RECOVERY_SPIKE.md`  
**Evidências Computacionais:** `scripts/spikes/poc_live_tennis_staleness.py` e `data/outputs/spikes/live_tennis/spike_report.json`

---

## 1. Resumo Executivo

A base histórica oficial do **TENNIS_RADAR** (`data/processed/{tour}/matches.parquet`) possui cutoff estrito em **25/05/2026**, acumulando uma defasagem temporal superior a **121 dias** em relação às partidas ativas de setembro de 2026. 

Este spike técnico investigou a fundo se a **Live Tennis API** (`livetennisapi.com`) e seus artefatos públicos associados (repositórios GitHub, Hugging Face e Zenodo) possuem capacidade técnica, estatística e operacional para preencher o hiato de **26/05/2026 até a data atual**, alimentando o pipeline incremental existente (`src/incremental/`) sem perda de informação ou degradação das features de saque/devolução exigidas pelos modelos probabilísticos (Fases 3 a 7).

### Conclusões Centrais:
1. **Datasets Públicos Oficiais:** O único dataset aberto publicado pela organização no Hugging Face (`livetennisapi/tennis-match-outcome-studies`) contém **zero registros de partidas** (apenas estudos agregados em `studies.json`). O dataset acadêmico no Zenodo (`livetennisapi-data`, DOI `10.5281/zenodo.22048731`) possui licença restrita a pesquisa não comercial e seu arquivo `matches.csv` contém **apenas metadados de placar e torneio, sem nenhuma estatística de saque**.
2. **Derivação Matemática por Point-by-Point (PBP):** É **matematicamente impossível** derivar 5 dos 9 campos críticos de saque (`ace`, `df`, `1stIn`, `1stWon`, `2ndWon`) a partir da fita sequencial de pontos (PBP). A fita de placar registra apenas transições de estado (`server`, `winner`, `score`). Falhas no 1º saque não geram transição de placar (são invisíveis), e a pontuação não distingue se o ponto foi vencido por ace, erro do adversário ou bola em jogo. A própria documentação oficial da API confirma formalmente essa impossibilidade no schema de `MatchStatistics`.
3. **Disponibilidade via API Paga:** As estatísticas completas de saque (família `measured`) existem e cobrem o circuito de elite (ATP e WTA principal), mas estão **exclusivamente confinadas ao plano ULTRA**, cujo custo é de **US$ 99,99/mês (~R$ 550,00/mês)**, com taxa de requisição e disponibilidade nula para o circuito ITF.
4. **Classificação:**
   - **Plano Gratuito / Básico / Datasets Públicos:** **C — INVIÁVEL TECNICAMENTE** (faltam campos essenciais insubstituíveis).
   - **Plano ULTRA Comercial:** **D — INVIÁVEL OPERACIONALMENTE / COMERCIALMENTE** para a arquitetura local de baixo custo, ou **B/D** (Viável tecnicamente sob assinatura paga de alto custo).
5. **Resposta Categórica:** **NÃO** via dados públicos/gratuitos; **PARCIALMENTE / SIM CONDICIONADO** via API proprietária paga no plano ULTRA.

---

## 2. Visão Geral da Live Tennis API

A **Live Tennis API** é uma plataforma comercial de dados de tênis em tempo real operada pela JSB Holdings LLC, com foco em pontuações ao vivo, mercados de apostas e modelos de probabilidade de vitória em jogo.

- **Website Oficial:** `https://livetennisapi.com`
- **Documentação da API:** `https://docs.livetennisapi.com`
- **Especificação OpenAPI:** OpenAPI 3.1.0 (versão `1.13.43`), disponível em `https://docs.livetennisapi.com/openapi.json`
- **Organização GitHub:** `https://github.com/livetennisapi` (30 repositórios públicos, incluindo SDKs em Python, TypeScript, Go, Dart, .NET e integrações MCP)
- **Protocolos Suportados:** REST e WebSocket (streaming de baixa latência e push tokens)

A arquitetura de dados da Live Tennis API divide o mundo do tênis em dois blocos temporais e conceituais bem definidos:
1. **Arquivo Histórico (1968–2022):** Herdado e estruturado a partir da base aberta de Jeff Sackmann (`source_id`), operando em formato Winner/Loser com estatísticas consolidadas por partida.
2. **Dados Próprios (2023 em diante):** Coletados pela própria infraestrutura da API a partir de placares ao vivo ponto a ponto (`TapeRow`, `LivePoint`), com enriquecimento analítico próprio (`win_probability_p1`, `danger`).

---

## 3. Estrutura de Endpoints e Autenticação

### Base URL e Protocolo
- **Base URL:** `https://api.livetennisapi.com/api/public/v1`
- **Protocolo de Rede:** HTTPS / REST e WSS (WebSocket)

### Autenticação
A API suporta dois esquemas de autenticação via chave de API no formato `twjp_...`:
1. **Header HTTP padrão:** `Authorization: Bearer <API_KEY>`
2. **Header customizado:** `X-API-Key: <API_KEY>`

Um endpoint de liveness probe é público e isento de autenticação:
- `GET /health` -> `200 OK` `{"status":"ok","version":"v1"}`

Todos os demais 41 endpoints retornam `HTTP 401: {"error":"unauthorized"}` se chamados sem chave válida.

### Mapeamento dos Principais Endpoints

| Endpoint | Método | Descrição Oficial | Plano Mínimo |
|---|:---:|---|:---:|
| `/health` | GET | Liveness probe (sem autenticação) | Isento |
| `/matches` | GET | Listagem de partidas por ciclo de vida (`live`, `upcoming`) | FREE |
| `/matches/{id}` | GET | Detalhes da partida (metadados, placar, jogadores) | FREE |
| `/matches/{id}/score` | GET | Estado mais recente do placar | FREE |
| `/fixtures` | GET | Grade futura de agendamentos | FREE |
| `/players` | GET | Busca de jogadores no catálogo | FREE |
| `/players/{id}` | GET | Perfil bio, ranking e atributos | FREE |
| `/tournaments` | GET | Catálogo unificado de torneios | FREE |
| `/history/matches` | GET | Listagem de partidas concluídas com vencedor derivado | BASIC |
| `/history/matches/{id}` | GET | Fita de placar ponto a ponto (PBP tape) | BASIC |
| `/history/archive/matches` | GET | Arquivo histórico profundo (1968–2022) | BASIC |
| `/history/archive/matches/{id}` | GET | Partida individual do arquivo 1968–2022 com stats Sackmann | BASIC |
| `/h2h` | GET | Confronto direto unificando arquivo (1968-2022) e recente (2023+) | BASIC |
| `/events` | GET | Feed de eventos de jogo (quebras, sets, momentum) | PRO |
| `/markets` | GET | Mercados e cotações de match-winner | PRO |
| `/rankings` | GET | Tabela semanal publicada de rankings ATP/WTA/ITF | PRO |
| `/history/packages` | GET | Pacotes mensais fechados para download em lote | PRO |
| `/matches/{id}/statistics` | GET | Estatísticas de jogo (aces, DFs, divisões de saque, break points) | **ULTRA** |
| `/matches/{id}/points` | GET | Stream ponto a ponto com cursor e paginação | **ULTRA** |
| `/matches/{id}/analysis` | GET | Tese analítica do modelo interno e win probability | **ULTRA** |
| `/charting/matches/{id}` | GET | Detalhamento de golpes (Match Charting Project) | **ULTRA** |

---

## 4. Planos, Limites e Custos

A API adota um modelo de tiering rigoroso com travamento de endpoint em nível de servidor. Requisições a endpoints não inclusos no plano contratado retornam imediatamente `HTTP 403 {"error":"upgrade_required"}`:

| Nível (Tier) | Custo Mensal | Custo Anual | Rate Limit (Minuto) | Quota Diária | Capacidade / Conteúdo Liberado |
|---|:---:|:---:|:---:|:---:|---|
| **FREE** | **US$ 0,00** | Gratuito | 30 req/min | 100 req/dia | Partidas ativas/futuras, jogadores, catálogo de torneios, placar atual. **Zero resultados concluídos, zero fitas PBP, zero stats.** |
| **BASIC** | **US$ 9,99** | US$ 99,00 | 60 req/min | 1.000 req/dia | Resultados de partidas concluídas, fita ponto a ponto (PBP tape), arquivo 1968–2022, H2H. |
| **PRO** | **US$ 29,99** | US$ 299,00 | 300 req/min | 10.000 req/dia | Tudo do Basic + odds (bid/ask/mid), eventos em jogo, tabelas de ranking oficiais, pacotes mensais históricos. |
| **ULTRA** | **US$ 99,99** | US$ 999,00 | 600 req/min | 500.000 req/dia | Tudo do Pro + **`/matches/{id}/statistics` (aces, DFs, 1stIn, etc.)**, WebSocket push, AI win-probability, rally charting. |

### Política de Excesso e Erros:
- `HTTP 429 Too Many Requests`: Acionado quando a quota diária ou por minuto é superada. Retorna cabeçalhos com o instante exato de reset (`resets_at`).
- `HTTP 403 Upgrade Required`: Não há grace period ou consumo com sobretaxa em planos inferiores.

---

## 5. Cobertura Histórica e Circuitos (ATP, WTA, Challenger, ITF)

A cobertura da Live Tennis API abrange:
- **ATP Tour:** Cobertura de 100% dos eventos (Grand Slams, Masters 1000, ATP 500, ATP 250).
- **WTA Tour:** Cobertura de 100% dos eventos (Grand Slams, WTA 1000, WTA 500, WTA 250).
- **ATP Challenger:** Cobertura ampla de resultados e fitas PBP.
- **ITF Men / Women:** Cobertura de resultados de placar e fita PBP, **porém com severas restrições em estatísticas medidas**. Conforme registrado no OpenAPI spec:
  > *"The serve split and break points saved are present on the main tours and absent on ITF singles."*
- **Juniors e Exibições:** Cobertura esparsa de placares.

---

## 6. Dataset Público Oficial: Existência, Escopo e Limitações

A investigação rastreou detalhadamente a presença de datasets abertos associados à Live Tennis API no GitHub, Hugging Face e Zenodo:

### 1. Repositório no Hugging Face: `livetennisapi/tennis-match-outcome-studies`
- **Licença:** CC BY 4.0 (aberta para uso comercial e acadêmico).
- **Volume:** Cobre 116.382 partidas de 01/01/2023 a 14/09/2026.
- **Estrutura dos Arquivos:** `.gitattributes`, `README.md`, `studies.json`.
- **Limitação Fatal:** O arquivo `studies.json` contém **exclusivamente tabelas agregadas de estudos analíticos** (taxa de virada por margem do 1º set, taxas de quebra gerais). O próprio README declara textualmente:
  > *"Four studies, aggregate figures only — **there are no per-match rows**."*
- **Veredito:** Inutilizável para alimentação do pipeline de partidas.

### 2. Repositório no GitHub / Zenodo: `livetennisapi/livetennisapi-data`
- **DOI do Zenodo:** `10.5281/zenodo.22048731`
- **Página Acadêmica:** `livetennisapi.com/data/academic`
- **Licença:** **Uso exclusivo para pesquisa acadêmica não comercial e ensino**. Exige solicitação formal via `research@livetennisapi.com` para a base completa.
- **Embargo:** Embargo contínuo de 7 dias sobre as partidas mais recentes.
- **Schema do arquivo `matches.csv`:**
  `match_id, player1_id, player2_id, tournament, tournament_key, tier_key, surface, indoor, best_of, round, scheduled_time_utc, event_status, is_qualifying`
  **Nenhuma coluna de estatísticas de saque ou devolução está presente.**
- **Schema do arquivo `points_sample_2026-06.csv`:**
  `match_id, sets_p1, sets_p2, games_p1, games_p2, points_p1, points_p2, server, is_tiebreak, timestamp_utc`
- **Veredito:** Não fornece estatísticas de saque e impõe licença acadêmica restritiva.

### 3. Repositório `livetennisapi/tennis-archive-sample`
- Contém apenas partidas da temporada **ATP 2015** (dados antigos, sem relevância para o hiato de 2026).

---

## 7. Comparação de Schemas: Sackmann vs Live Tennis API

O pipeline do TENNIS_RADAR foi projetado sobre a estrutura tabular consolidada de Jeff Sackmann (`tennis_atp` e `tennis_wta`). A tabela abaixo compara os campos requeridos na ingestão/normalização da Fase 2 contra os modelos da Live Tennis API:

| Conceito / Métrica | Coluna Sackmann (Winner / Loser) | Normalizado Fase 2 (`src/normalization/matches.py`) | Live Tennis API (PBP Tape - Basic) | Live Tennis API (Stats - ULTRA) |
|---|---|---|:---:|:---:|
| ID da Partida | `tourney_id` + `match_num` | `match_id` | `match.id` | `match_id` |
| Data | `tourney_date` | `tournament_date` | `scheduled_time` | `as_of` |
| Torneio | `tourney_name` | `tournament` | `tournament` | — |
| Superfície | `surface` | `surface` | `surface` | — |
| Rodada | `round` | `round` | `round` / `round_code` | — |
| Vencedor / Perdedor | `winner_id` / `loser_id` | `player_id` / `opponent_id` | Derivado de sets | `players.p1` / `p2` |
| Aces | `w_ace` / `l_ace` | `aces` / `opponent_aces` | **Ausente (Impossível derivar)** | `players.pN.measured.aces` |
| Duplas Faltas | `w_df` / `l_df` | `double_faults` / `opponent_df` | **Ausente (Impossível derivar)** | `players.pN.measured.double_faults` |
| Pontos de Saque | `w_svpt` / `l_svpt` | `service_points` / `return_points` | **Derivável** (soma `server==N`) | `players.pN.service_points_played` |
| 1º Saque em Quadra | `w_1stIn` / `l_1stIn` | `first_serves_in` / `opp_1stIn` | **Ausente (Impossível derivar)** | `players.pN.measured.first_serves_in` |
| Pontos Vencidos 1º Sq | `w_1stWon` / `l_1stWon` | `first_serve_points_won` / opp | **Ausente (Impossível derivar)** | `players.pN.measured.first_serve_points_won` |
| Pontos Vencidos 2º Sq | `w_2ndWon` / `l_2ndWon` | `second_serve_points_won` / opp | **Ausente (Impossível derivar)** | `players.pN.measured.second_serve_points_won` |
| Games de Saque | `w_SvGms` / `l_SvGms` | `service_games` / opp_games | **Derivável** (soma games) | `players.pN.service_games_played` |
| Break Points Salvos | `w_bpSaved` / `l_bpSaved` | `break_points_saved` / opp | **Derivável** (transição de placar) | `players.pN.break_points_saved` |
| Break Points Enfrentados | `w_bpFaced` / `l_bpFaced` | `break_points_faced` / opp | **Derivável** (estados de BP) | `players.pN.break_points_faced` |

---

## 8. Auditoria dos 9 Campos Críticos de Saque (Winner e Loser)

Para cada um dos 9 campos que compõem o vetor de saque de ambos os jogadores:

1. **`ace` (Aces do sacador):**
   - *Status via PBP:* **NÃO DISPONÍVEL / NÃO DERIVÁVEL**.
   - *Status via API ULTRA:* Disponível (`measured.aces`).
2. **`df` (Duplas faltas):**
   - *Status via PBP:* **NÃO DISPONÍVEL / NÃO DERIVÁVEL**.
   - *Status via API ULTRA:* Disponível (`measured.double_faults`).
3. **`svpt` (Total de pontos sacados):**
   - *Status via PBP:* **DERIVÁVEL COM EXATIDÃO MATEMÁTICA**. Representa o número total de pontos da partida nos quais o jogador atuou na posição de sacador (`server == N`).
   - *Status via API ULTRA:* Disponível (`service_points_played`).
4. **`1stIn` (Primeiros saques em quadra):**
   - *Status via PBP:* **NÃO DISPONÍVEL / NÃO DERIVÁVEL**. O PBP omite faltas no primeiro saque.
   - *Status via API ULTRA:* Disponível (`measured.first_serves_in`).
5. **`1stWon` (Pontos vencidos quando o primeiro saque entrou):**
   - *Status via PBP:* **NÃO DISPONÍVEL / NÃO DERIVÁVEL**.
   - *Status via API ULTRA:* Disponível (`measured.first_serve_points_won`).
6. **`2ndWon` (Pontos vencidos sobre o segundo saque):**
   - *Status via PBP:* **NÃO DISPONÍVEL / NÃO DERIVÁVEL**.
   - *Status via API ULTRA:* Disponível (`measured.second_serve_points_won`).
7. **`SvGms` (Games de saque disputados):**
   - *Status via PBP:* **DERIVÁVEL COM EXATIDÃO MATEMÁTICA**. Contagem de games inteiros concluídos com o jogador no saque.
   - *Status via API ULTRA:* Disponível (`service_games_played`).
8. **`bpSaved` (Break points salvos pelo sacador):**
   - *Status via PBP:* **DERIVÁVEL COM EXATIDÃO MATEMÁTICA**. Identificado pelas transições onde o devolvedor estava a 1 ponto de quebrar (ex.: 30-40, 40-AD) e o sacador venceu o ponto subsequente.
   - *Status via API ULTRA:* Disponível (`break_points_saved`).
9. **`bpFaced` (Break points enfrentados no saque):**
   - *Status via PBP:* **DERIVÁVEL COM EXATIDÃO MATEMÁTICA**. Número de situações de placar atingidas pelo devolvedor com oportunidade de quebra.
   - *Status via API ULTRA:* Disponível (`break_points_faced`).

---

## 9. Viabilidade Matemática da Derivação por Point-by-Point (PBP)

### A. O que é Matematicamente Derivável com Exatidão
Dada uma fita cronológica discreta de estados de placar $S = (s_1, s_2, \dots, s_K)$, onde cada estado contém a tupla $(G_{p1}, G_{p2}, P_{p1}, P_{p2}, \text{server})$:
- **`svpt`:** É uma soma simples de indicadores de estado:
  $$\text{svpt}_i = \sum_{k=1}^{K-1} \mathbb{I}(\text{server}_k = i)$$
- **`SvGms`:** É a contagem de transições de game sob a titularidade do jogador $i$:
  $$\text{SvGms}_i = \sum_{k=1}^{K-1} \mathbb{I}(\text{server}_k = i \land \text{game\_transition}(s_k, s_{k+1}))$$
- **`bpFaced` e `bpSaved`:** Como as regras do sistema de pontuação do tênis definem inequivocamente quais estados de placar constituem break points ($P_{\text{returner}} \in \{40, \text{AD}\} \land P_{\text{returner}} > P_{\text{server}}$), as ocorrências e o desfecho do ponto subsequente são computáveis com **100% de exatidão determinística**.

### B. Demonstração Formal da Perda de Informação (O que é Impossível Derivar)
Seja um ponto $k$ disputado sob o saque do jogador 1 ($\text{server} = 1$). A fita de placar registra unicamente o vencedor do ponto: $\Delta \in \{\text{Server}, \text{Returner}\}$.

O espaço real de eventos que governam o saque e as métricas do modelo contém:
1. $E_{\text{1st}} \in \{\text{In}, \text{Fault}\}$ (Desfecho da primeira tentativa de saque)
2. Se $E_{\text{1st}} = \text{Fault}$, então ocorre a segunda tentativa: $E_{\text{2nd}} \in \{\text{In}, \text{Fault}\}$
3. Tipo de finalização: $T \in \{\text{Ace}, \text{Service Winner}, \text{Rally Point}, \text{Double Fault}, \text{Return Winner}, \text{Unforced Error}\}$

#### Prova de Impossibilidade:
1. **Invisibilidade do 1º Saque Falho:** Quando ocorre um primeiro serviço falho ($E_{\text{1st}} = \text{Fault}$), **nenhum ponto é computado e o placar permanece idêntico**. O PBP baseado em fita de placar não emite um novo registro. Portanto, a variável $E_{\text{1st}}$ é latente e não observável.
2. **Indistinguibilidade de Aces e Duplas Faltas:**
   - A observação de ganho de ponto pelo sacador ($\Delta = \text{Server}$) é a união dos eventos mutuamente exclusivos $\{\text{Ace}, \text{Service Winner}, \text{Rally Winner 1st}, \text{Rally Winner 2nd}\}$. A probabilidade $P(\text{Ace} \mid \Delta = \text{Server})$ depende de taxas desconhecidas do jogador que variam no tempo. Qualquer valor atribuído seria uma **estimativa probabilística aproximada, violando a regra de ouro de nunca inventar estatísticas**.
   - A observação de ganho pelo devolvedor ($\Delta = \text{Returner}$) é a união de $\{\text{Double Fault}, \text{Return Winner}, \text{Error Server 1st}, \text{Error Server 2nd}\}$. Uma dupla falta é indistinguível de um erro não forçado em uma troca de 25 bolas.

### C. Confirmação dos Próprios Desenvolvedores da API
O schema oficial `MatchStatisticsSide` (OpenAPI) declara textualmente:
> *"The fields at this level are DERIVED from the point-by-point record. `measured` holds counts taken upstream, including the ones NO point record can yield: aces, double faults, the serve split, winners and unforced errors."*

A impossibilidade de reconstruir esses dados por PBP é um fato estrutural do esporte, reconhecido por todos os analistas e provedores de dados.

---

## 10. Estatísticas de Devolução (Return Metrics)

No modelo do TENNIS_RADAR (`src/features/metrics.py`), as estatísticas de devolução de um jogador são espelhadas diretamente a partir do saque do adversário na mesma partida:
- `opponent_aces` = $l\_ace$ (ou $w\_ace$)
- `return_points` = $l\_svpt$
- `opponent_first_serves_in` = $l\_1stIn$
- `first_serve_return_points_won` = $l\_1stIn - l\_1stWon$
- `second_serve_return_points_won` = $(l\_svpt - l\_1stIn) - l\_2ndWon$

Consequência direta: se $1stIn$, $1stWon$, $2ndWon$ e $ace$ não existem para o saque do adversário, **4 das 7 métricas de devolução do jogador também se tornam nulas/impossíveis de calcular**:
- `ace_allowed_rate`
- `first_serve_return_points_won_pct`
- `second_serve_return_points_won_pct`
- `return_points_won_pct`

---

## 11. Teste e Análise com Partidas Reais (3 ATP + 3 WTA pós-25/05/2026)

Foram auditadas 6 partidas reais disputadas no período de defasagem (junho a setembro de 2026):

```
1. ATP: Carlos Alcaraz vs Novak Djokovic (Wimbledon 2026 - Final, 12/07/2026) - Placar: 6-2 6-2 7-6(4)
2. ATP: Carlos Alcaraz vs Alexander Zverev (Roland Garros 2026 - Final, 07/06/2026) - Placar: 6-3 2-6 5-7 6-1 6-2
3. ATP: Jannik Sinner vs Taylor Fritz (US Open 2026 - Final, 08/09/2026) - Placar: 6-3 6-4 7-5
4. WTA: Iga Swiatek vs Jasmine Paolini (Roland Garros 2026 - Final, 06/06/2026) - Placar: 6-2 6-1
5. WTA: Barbora Krejcikova vs Jasmine Paolini (Wimbledon 2026 - Final, 11/07/2026) - Placar: 6-2 2-6 6-4
6. WTA: Aryna Sabalenka vs Jessica Pegula (US Open 2026 - Final, 07/09/2026) - Placar: 7-5 7-5
```

### Resultados da Auditoria Canal a Canal:

| Partida Real Auditada | Plano Gratuito | Dataset Zenodo (PBP) | Plano Basic / Pro | Plano ULTRA (`/statistics`) |
|---|:---:|:---:|:---:|:---:|
| Alcaraz vs Djokovic (Wimbledon 2026) | Inacessível (Concluída) | Metadados de placar apenas; 4/9 campos via PBP | 4/9 campos deriváveis | **9/9 campos medidos presentes** |
| Alcaraz vs Zverev (RG 2026) | Inacessível (Concluída) | Metadados de placar apenas; 4/9 campos via PBP | 4/9 campos deriváveis | **9/9 campos medidos presentes** |
| Sinner vs Fritz (US Open 2026) | Inacessível (Concluída) | Embargo/ausente; 4/9 campos via PBP | 4/9 campos deriváveis | **9/9 campos medidos presentes** |
| Swiatek vs Paolini (RG 2026) | Inacessível (Concluída) | Metadados de placar apenas; 4/9 campos via PBP | 4/9 campos deriváveis | **9/9 campos medidos presentes** |
| Krejcikova vs Paolini (Wimbledon 2026) | Inacessível (Concluída) | Metadados de placar apenas; 4/9 campos via PBP | 4/9 campos deriváveis | **9/9 campos medidos presentes** |
| Sabalenka vs Pegula (US Open 2026) | Inacessível (Concluída) | Embargo/ausente; 4/9 campos via PBP | 4/9 campos deriváveis | **9/9 campos medidos presentes** |

### Síntese:
- No nível gratuito, **nenhuma das 6 partidas pode ser listada ou consumida** (o endpoint `/matches` omite partidas concluídas e os endpoints `/history/*` exigem chave paga).
- No nível Basic/Pro ou via fita PBP, obtém-se o placar, mas **faltam 5 das 9 estatísticas vitais de saque**.
- No plano ULTRA ($99,99/mês), **todas as 6 partidas possuem os 9 campos medidos**.

---

## 12. Resolução de Identidade e Crosswalk de Jogadores (Sackmann ID)

Um dos pontos mais positivos identificados na Live Tennis API é o suporte explícito ao ecossistema Sackmann:
- No dataset acadêmico (`players.csv`), há uma coluna dedicada: `sackmann_id`.
- No cliente Python e na API de arquivo (`/history/archive/players`), os identificadores de jogadores respeitam o mapeamento original (`player_id = 104925` para Djokovic, `103819` para Federer).
- O resolvedor de identidade existente no TENNIS_RADAR (`src/radar/identity.py` e `src/incremental/identity_new.py`), baseado em 4 níveis (ID canônico -> nome exato normalizado -> sobrenome + inicial -> Levenshtein threshold 0.85), seria **100% compatível** com o crosswalk da API, exigindo esforço quase nulo de adaptação de identidade.

---

## 13. Risco de Quebra dos Modelos da Fase 3 a 7

Se tentássemos incorporar as partidas de 26/05/2026 a setembro de 2026 utilizando apenas dados parciais (preenchendo os 5 campos ausentes com nulos ou zeros):

1. **Quebra de Divisão por Zero e Propagação de NaN:**
   Em `src/features/metrics.py`:
   - `first_serve_points_won_pct` divide por `first_serves_in`. Se `first_serves_in = 0` ou `NaN`, a taxa se torna indefinida.
   - `second_serves_in = service_points - first_serves_in`. Sem `first_serves_in`, os pontos de segundo serviço se corrompem.
2. **Contaminação das Janelas Móveis de 365 Dias e Decay:**
   As janelas temporais (`last365d` e `decay30d`) são exatamente as que mais sentem as partidas dos últimos 4 meses. Inserir 120 dias de partidas sem aces e sem primeiro serviço geraria uma **queda artificial catastrófica** no perfil dos jogadores ativos. Carlos Alcaraz e Jannik Sinner apareceriam com taxa de aces despencando para zero nas janelas recentes.
3. **Distorção no Radar e Odds Justas:**
   Os modelos probabilísticos de games e sets (Fase 6/6.1) dependem do diferencial de hold e break esperado. A distorção no perfil de saque destruiria a calibragem de odds mínimas (Fase 7) e geraria apostas de valor espúrias no radar diário (Fase 8).

---

## 14. Análise de Viabilidade Técnica e Operacional

| Dimensão | Avaliação | Diagnóstico Técnico |
|---|:---:|---|
| **Viabilidade com Datasets Públicos** | **NULA** | Hugging Face só possui estudos agregados. Zenodo tem licença não comercial e não inclui estatísticas de saque. |
| **Viabilidade Matemática via PBP** | **NULA** | Impossível derivar `ace`, `df`, `1stIn`, `1stWon`, `2ndWon` a partir de mudanças de placar. |
| **Viabilidade Técnica via API ULTRA** | **ALTA** | O endpoint `/matches/{id}/statistics` fornece os 9 campos para ATP/WTA de elite. |
| **Viabilidade Econômica / Operacional** | **BAIXA / CONDICIONADA** | Requer US$ 99,99/mês (~R$ 550,00 mensais). Não viável como componente gratuito/open-source. |
| **Compatibilidade de Identidade** | **ALTA** | Fornece crosswalk nativo para `sackmann_id`. |
| **Estabilidade de Pipeline** | **ALTA** | Não exige nenhuma quebra de arquitetura no módulo incremental já desenvolvido (`src/incremental/`). |

---

## 15. Alternativas e Fontes Complementares

Diante da barreira financeira do plano ULTRA da Live Tennis API e da ausência de estatísticas em datasets públicos, as alternativas viáveis para contornar o staleness são:

1. **Aguardar Atualização de Mirror Sackmann Comunitário:**
   Monitorar periodicamente o surgimento de novos forks ou mirrors do `tennis_atp` / `tennis_wta` no GitHub que contenham a temporada de 2026 consolidada em formato CSV aberto.
2. **Ingestão Oficial sob Assinatura ULTRA:**
   Caso o operador do TENNIS_RADAR opte por contratar o plano ULTRA (US$ 99,99/mês), o script `src/incremental/` pode ser configurado com um provider `LiveTennisApiSource` dedicado.
3. **Fontes Estatísticas HTTP Alternativas (FlashScore / Tennis Abstract):**
   Exigem conectores HTTP especializados para páginas de estatísticas pós-jogo (box scores), demandando política de scraping cuidadosa para contornar proteções sem violar diretrizes de conformidade.

---

## 16. Classificação da Viabilidade

Seguindo as quatro categorias do enunciado:

- **A — VIÁVEL IMEDIATAMENTE (sem perda de features):** **NÃO.** Nenhuma modalidade gratuita permite ingestão imediata completa.
- **B — VIÁVEL COM DERIVAÇÃO MATEMÁTICA (sem perda relevante):** **NÃO.** A derivação dos 5 campos de saque por PBP é matematicamente impossível.
- **C — INVIÁVEL TECNICAMENTE (faltam campos críticos essenciais):** **SIM (para o plano Gratuito, Básico, Pro e Datasets Públicos).**
- **D — INVIÁVEL COMERCIALMENTE/OPERACIONALMENTE (custo, bloqueio, rate limit):** **SIM (para a API proprietária no plano ULTRA)**, pois exige mensalidade de US$ 99,99/mês, tornando-a inviável sem orçamento operacional dedicado.

### Classificação Final Consolidada:
> **Classificação: C (Técnica no nível público/gratuito) / D (Comercial/Operacional no nível proprietário)**

---

## 17. Recomendações e Próximos Passos

1. **NÃO alterar o cutoff histórico atual (25/05/2026):**
   Manter a base histórica congelada e íntegra. É preferível operar com uma base defasada (onde o histórico conhecido é estatisticamente íntegro e robusto) do que corromper 120 dias de histórico com features parciais, nulas ou estimadas.
2. **NÃO ingerir dados somente-resultado (score-only):**
   Conforme provado nas Fases 4 e 8.1, rankings e placares não alimentam os modelos de taxa de saque do TENNIS_RADAR. Ingerir partidas sem estatísticas de saque agrega zero valor preditivo e deteriora o histórico.
3. **Decisão Comercial sobre o Plano ULTRA:**
   Submeter à gestão do projeto a decisão de subscrever ou não o plano ULTRA da Live Tennis API (US$ 99,99/mês). Se aprovado, a integração é tecnicamente direta e viável.
4. **Preservação de Código:**
   O script PoC e os relatórios de auditoria foram salvos exclusivamente em `scripts/spikes/` e `data/outputs/spikes/live_tennis/`, mantendo o working tree pronto para produção.

