# 006 — RELATÓRIO DE NORMALIZAÇÃO — FASE 2

Status: concluída. Aguardando aprovação para Fase 3 (features Serve × Return).
Data: 2026-09-22.
Escopo: leitura exclusiva de `data/raw/` (ATP + WTA, 2022–2026, gerado na Fase 1); nenhum
download novo; nenhuma feature, média histórica, rolling window, Elo, modelo ou backtest.

---

## 1. Processo

### 1.1 Entrada e saída

- **Entrada:** somente `data/raw/sackmann_atp/` e `data/raw/sackmann_wta/` (Fase 1). Nenhum
  arquivo em `data/raw/` foi lido de outra forma além de leitura; nenhum foi alterado —
  confirmado pelo teste `test_raw_files_untouched_marker` (o manifesto da Fase 1 continua com
  `n_issues == 0` e os hashes SHA-256 batem, conferidos por `tests/test_ingestion.py`, que
  também foi reexecutado nesta fase).
- **Saída:** `data/processed/`, em Parquet (CSV usado só para amostras de inspeção, conforme
  pedido).

### 1.2 Dependências

Diferente da Fase 1 (que evitou dependências deliberadamente), a Fase 2 precisou de `pandas` e
`pyarrow` para produzir Parquet — ambos já estavam declarados em `requirements.txt` desde o
início do projeto. Instalamos só esses dois pacotes (não o `requirements.txt` inteiro), mantendo
o princípio de não adicionar dependência além do necessário (CLAUDE.md §20).

### 1.3 Pipeline implementado

Código em `src/normalization/` (reutiliza `src/ingestion/config.py` para não duplicar a lista de
arquivos/fontes):

| Arquivo | Responsabilidade |
|---|---|
| `config.py` | Diretórios de entrada/saída, reaproveitando `SOURCES` da Fase 1 |
| `players.py` | Tabela dimensão de jogadores com `player_id` canônico por tour |
| `rankings.py` | Unifica histórico de ranking ATP/WTA, tratando a coluna `tours` |
| `matches.py` | Núcleo: transforma partidas brutas em formato longo (jogador-partida) |
| `reports.py` | Relatório de nulls e de partidas utilizáveis por mercado |
| `validate.py` | Validações estruturais (2 linhas/partida, espelhamento, IDs) |
| `run.py` | Orquestra tudo e grava `data/processed/` |

CLI: `scripts/normalize_phase2.py`. Testes: `tests/test_normalization.py`.

### 1.4 Decisão central: como vieram as estatísticas de devolução

Cada partida bruta do Sackmann já traz, na mesma linha, as estatísticas de saque **dos dois
jogadores** (prefixo `w_` para o vencedor, `l_` para o perdedor). Isso significa que as
"estatísticas de devolução" pedidas (`opponent_aces`, `return_points`,
`break_points_created`, `break_points_converted`) não exigem nenhum cruzamento entre partidas —
são exatamente as estatísticas de saque do adversário **naquela mesma partida**, espelhadas para
a perspectiva de quem devolveu. Isso simplifica a implementação e elimina uma classe inteira de
bug (join incorreto entre partidas).

- `opponent_aces = df[oponente]` &nbsp;·&nbsp; `return_points = svpt[oponente]`
- `break_points_created = bpFaced[oponente]`
- `break_points_converted = bpFaced[oponente] - bpSaved[oponente]`

### 1.5 `match_id`

Formato: `{TOUR}:{tourney_id}:{match_num}` (ex.: `ATP:2022-8888:247`). É determinístico e
reproduzível (depende só de campos imutáveis do arquivo bruto), e é **escopado por tour** porque
descobrimos que o mesmo `tourney_id` pode aparecer nos dois arquivos brutos ao mesmo tempo (ex.:
eventos mistos como o United Cup, que gera partidas ATP e WTA sob o mesmo `tourney_id`
`2023-9900`). Sem o prefixo de tour, haveria colisão de `match_id` entre ATP e WTA.

### 1.6 `player_id`

Formato: `{TOUR}-{player_id_bruto_do_Sackmann}` (ex.: `ATP-100001`). **Achado importante:** os
IDs numéricos brutos do Sackmann **não são globalmente únicos entre ATP e WTA** — as faixas se
sobrepõem (ex.: o ID `200000` existe nos dois arquivos de players, representando pessoas
diferentes — nos dois casos, inclusive, como placeholder de jogador desconhecido). Sem o prefixo
de tour, o pipeline teria fundido silenciosamente jogadores ATP e WTA diferentes sob o mesmo ID —
exatamente o tipo de erro de identidade que CLAUDE.md §10 pede para evitar. Confirmado por teste:
a interseção entre os `player_id` canônicos de ATP e WTA é vazia (`test_atp_and_wta_player_ids_never_collide`).

### 1.7 Coluna `tours` (rankings ATP × WTA)

A Fase 1 já havia identificado que `wta_rankings_*.csv` tem uma coluna `tours` que não existe no
lado ATP. Na normalização, essa coluna foi **mantida no schema unificado** e preenchida com
`<NA>` (nulo real, não zero) para todas as linhas ATP — nenhuma informação foi descartada e
nenhum dado foi inventado. Confirmado por teste
(`test_atp_rankings_tours_all_null_wta_has_values`).

### 1.8 Regra de não preencher com zero

Todas as colunas numéricas de estatística usam o dtype anulável `Int64` do pandas. Um campo vazio
no CSV bruto vira `<NA>`, nunca `0`. Subtrações (`break_points_converted`) propagam `<NA>`
automaticamente quando qualquer operando é nulo — testado tanto no exemplo sintético
(`test_missing_stats_are_null_not_zero`) quanto na base real
(`test_stat_columns_are_nullable_not_zero_filled`).

### 1.9 Separação ATP/WTA

Em vez de uma tabela única com todas as partidas, o pipeline grava arquivos físicos separados por
tour, no mesmo padrão de pasta já usado em `data/raw/`:

```
data/processed/
├── atp/{matches,players,rankings}.parquet
├── wta/{matches,players,rankings}.parquet
├── reports/{null_report.csv, usable_matches_report.csv, phase2_diagnostics.json}
└── samples/{matches_sample_atp.csv, matches_sample_wta.csv}
```

Isso torna explícita e literal a exigência de manter as duas competições separadas, sem impedir
que análises futuras leiam os dois arquivos e usem a coluna `tour` para filtrar/combinar quando
fizer sentido.

---

## 2. Partidas e linhas normalizadas

| Tour | Partidas brutas | Partidas usadas | Linhas jogador-partida | Linhas = 2×partidas? |
|---|---:|---:|---:|:---:|
| ATP | 13.372 | 13.372 | 26.744 | sim |
| WTA | 12.183 | 12.183 | 24.366 | sim |
| **Total** | **25.555** | **25.555** | **51.110** | sim |

Nenhuma partida foi descartada por `player_id`/`opponent_id` ausente (0 casos nos dois tours) —
todas as 25.555 partidas brutas 2022–2026 geraram exatamente 2 linhas cada.

---

## 3. Exemplos de partidas transformadas

**Exemplo 1 — ATP, ATP Cup 2022 (`ATP:2022-8888:247`):**

| player_name | opponent_name | result | player_rank | aces | opponent_aces | return_points | break_points_created | break_points_converted |
|---|---|---|---:|---:|---:|---:|---:|---:|
| Federico Delbonis | Aleksandre Metreveli | W | 44 | 4 | 1 | 58 | 9 | 6 |
| Aleksandre Metreveli | Federico Delbonis | L | 570 | 1 | 4 | 34 | 1 | 1 |

Confere: `aces` do vencedor (4) = `opponent_aces` da linha do perdedor (4); o espelhamento completo
dos 8 pares de campos é checado automaticamente para as 25.555 partidas (seção 4, item 2).

**Exemplo 2 — WTA, Adelaide 1 2022 (`WTA:2022-2014:271`):**

| player_name | opponent_name | result | player_rank | opponent_rank | aces | opponent_aces | break_points_converted |
|---|---|---|---:|---:|---:|---:|---:|
| Kaja Juvan | Chloe Paquet | W | 100 | 119 | 5 | 2 | 5 |

**Exemplo 3 — WTA, Melbourne 1 2022 (`WTA:2022-2058:291`), do lado da perdedora:**

| player_name | opponent_name | result | player_rank | opponent_rank | aces | opponent_aces | break_points_converted |
|---|---|---|---:|---:|---:|---:|---:|
| Anna Bondar | Anastasia Potapova | L | 92 | 69 | 6 | 10 | 2 |

Ou seja: Anna Bondar (perdedora, devolvendo) converteu 2 dos 3 break points que teve contra o
saque de Potapova. Confirmado na linha da própria Potapova nesta mesma partida:
`break_points_faced = 3`, `break_points_saved = 1` → `3 - 1 = 2`.

---

## 4. Validações executadas (pedidas explicitamente)

Todas rodam dentro de `scripts/normalize_phase2.py` e são reforçadas por
`tests/test_normalization.py` (18 testes, unidade + integração sobre a base real):

1. **Cada partida gera exatamente 2 linhas** — confirmado para as 25.555 partidas (ATP e WTA),
   0 exceções.
2. **Estatísticas do adversário espelhadas corretamente** — 8 pares de campos comparados
   (`aces↔opponent_aces`, `double_faults↔opponent_double_faults`, `service_points↔return_points`,
   `first_serves_in↔opponent_first_serves_in`, `first_serve_points_won↔opponent_first_serve_points_won`,
   `second_serve_points_won↔opponent_second_serve_points_won`, `service_games↔opponent_service_games`,
   `break_points_faced↔break_points_created`) em todas as 25.555 partidas — **0 divergências**.
3. **IDs ausentes ou duplicados** — 0 `player_id`/`opponent_id`/`match_id` ausentes; 0
   `player_id` duplicado nas tabelas de jogadores (66.912 ATP, 70.571 WTA); 0 `match_id`
   duplicado; 0 partidas com mais de uma linha "W".

Resultado completo em `data/processed/reports/phase2_diagnostics.json`.

---

## 5. Relatório de nulls (por coluna, ano, tour, superfície)

Gerado em `data/processed/reports/null_report.csv` (726 linhas: 2 tours × 5 anos × superfícies ×
21 colunas de estatística/ranking). Resumo dos padrões observados:

- `player_rank`/`opponent_rank`: tipicamente <2% de nulos (jogadores sem ranking ATP/WTA no
  momento — comum em wild cards e qualifiers de baixo nível).
- Colunas de saque (`aces`, `break_points_converted` etc.): nulas quando o `MatchStats` da
  partida não foi reportado pela fonte — já sinalizado agregadamente na Fase 1
  (`docs/005`, seção 5); aqui o mesmo problema aparece quebrado por superfície, confirmando que
  não há concentração anormal em nenhuma superfície específica.
- **Achado novo desta fase:** existe uma categoria `(sem surface)` — partidas sem superfície
  registrada — concentrada quase inteiramente em **confrontos de Davis Cup World Group 1/2
  Play-off** (ex. `Davis Cup WG2 PO: BOL vs GEO`). Nessas partidas, **100% das linhas também não
  têm estatísticas de saque**. São torneios de nível de seleção nacional com cobertura de dados
  mais fraca na fonte original — não é um problema do pipeline, mas deve ser levado em conta na
  Fase 3 (excluir ou tratar à parte esses eventos ao modelar por superfície, já que CLAUDE.md §8
  exige separação obrigatória hard/clay/grass).

---

## 6. Partidas utilizáveis por mercado

Gerado em `data/processed/reports/usable_matches_report.csv`. Uma partida é "utilizável" quando
os campos brutos necessários para calcular o mercado na Fase 3 estão presentes **para os dois
jogadores** (não calcula o valor do mercado, só mede disponibilidade de dado):

| Tour | Partidas | Aces | Double Faults | Total Games* | Total Sets* | Hold/Break |
|---|---:|---:|---:|---:|---:|---:|
| ATP 2022 | 2.917 | 2.745 (94,1%) | 2.745 (94,1%) | 2.900 (99,4%) | 2.900 (99,4%) | 2.745 (94,1%) |
| ATP 2023 | 2.986 | 2.815 (94,3%) | 2.815 (94,3%) | 2.966 (99,3%) | 2.966 (99,3%) | 2.815 (94,3%) |
| ATP 2024 | 3.158 | 3.098 (98,1%) | 3.098 (98,1%) | 3.138 (99,4%) | 3.138 (99,4%) | 3.097 (98,1%) |
| ATP 2025 | 2.862 | 2.603 (91,0%) | 2.603 (91,0%) | 2.840 (99,2%) | 2.840 (99,2%) | 2.603 (91,0%) |
| ATP 2026 (parcial) | 1.449 | 1.191 (82,2%) | 1.191 (82,2%) | 1.438 (99,2%) | 1.438 (99,2%) | 1.191 (82,2%) |
| WTA 2022 | 2.594 | 2.488 (95,9%) | 2.486 (95,8%) | 2.567 (99,0%) | 2.567 (99,0%) | 2.488 (95,9%) |
| WTA 2023 | 2.810 | 2.572 (91,5%) | 2.572 (91,5%) | 2.788 (99,2%) | 2.788 (99,2%) | 2.572 (91,5%) |
| WTA 2024 | 2.792 | 2.716 (97,3%) | 2.716 (97,3%) | 2.774 (99,4%) | 2.774 (99,4%) | 2.716 (97,3%) |
| WTA 2025 | 2.692 | 2.621 (97,4%) | 2.621 (97,4%) | 2.674 (99,3%) | 2.674 (99,3%) | 2.621 (97,4%) |
| WTA 2026 (parcial) | 1.295 | 1.112 (85,9%) | 1.112 (85,9%) | 1.286 (99,3%) | 1.286 (99,3%) | 1.112 (85,9%) |
| **Total** | **25.555** | **23.961 (93,8%)** | **23.959 (93,8%)** | **25.371 (99,3%)** | **25.371 (99,3%)** | **23.960 (93,8%)** |

\* *Total games/Total sets* dependem só do campo `score` estar presente e não ser um walkover
(`W/O`) — o parsing do placar em número de games/sets em si é trabalho da Fase 3, não desta fase.

**Nota sobre o ano "2024" e "2025" (achado de qualidade de dado):** ao agrupar por ano da
`tournament_date` (data real da partida) em vez de pelo arquivo de origem, 82 partidas do arquivo
`atp_matches_2025.csv` (United Cup, Brisbane, Hong Kong — eventos de início de temporada mas
datados em dezembro de 2024) caem no ano-calendário 2024, não 2025. Isso é uma característica
real do dataset Sackmann (arquivo é por "temporada", `tourney_date` é por semana civil) e deve ser
considerado na Fase 3 se janelas de tempo forem construídas por ano-calendário em vez de por
temporada.

---

## 7. Mercados com dado suficiente para seguir

Com base nas tabelas acima (CLAUDE.md §19 — decidir por dado, não por suposição):

- **Aces por jogador / Total de aces / Double faults:** ~92–98% das partidas por ano/tour têm os
  dois lados com estatística completa. **Suficiente para a Fase 3**, mantendo o tratamento de
  nulo explícito (não interpolar, não assumir zero) já embutido no schema.
- **Total de games / Total de sets:** ~99% das partidas têm placar utilizável. **Suficiente para
  a Fase 3** — mas a Fase 3 ainda precisa implementar o parser de `score` (não feito aqui) e
  decidir como tratar partidas com `RET` (abandono, placar parcial) separadamente de partidas
  completas.
- **Hold% / Break% / break points:** mesma cobertura que aces (~92–98%), pois dependem dos mesmos
  campos de `MatchStats`. **Suficiente para a Fase 3.**
- **Handicap de games:** deriva da mesma distribuição de placares que Total de games — mesma
  cobertura, mesma ressalva sobre o parser de `score`.
- **Tie-break:** ainda não avaliado nesta fase — exigiria parsing do placar para detectar sets com
  tie-break (`6-7(6)` etc.), o que é trabalho de parsing/feature, não de normalização. Os dados
  brutos (`score`) contêm essa informação; só não foi extraída aqui. **Recomendação:** tratar como
  parte do parser de placar da Fase 3, junto com total de games/sets.

Nenhum mercado do escopo do projeto (CLAUDE.md §1) ficou sem dado suficiente — a limitação em
todos os casos é de cobertura parcial (~2–18% conforme o ano/mercado), não de ausência estrutural.

---

## 8. Problemas encontrados

1. **Davis Cup World Group Play-offs sem superfície nem estatísticas** (seção 5) — recomendação:
   tratar como categoria à parte ou excluir na Fase 3, dado que CLAUDE.md §8 exige separação por
   superfície.
2. **Descompasso entre "arquivo por temporada" e "ano civil da partida"** (seção 6) — 82 partidas
   ATP com `tourney_date` em dezembro do ano anterior ao nome do arquivo. Não é erro de ingestão
   nem de normalização (confirmado contra o CSV bruto); é uma característica do dataset original.
   Recomendação: na Fase 3, decidir explicitamente se janelas temporais usam `tournament_date`
   (mais correto para point-in-time) ou o agrupamento por "temporada" do arquivo — e documentar a
   escolha.
3. **Cobertura de `MatchStats` cai bastante em 2026** (82,2%–85,9% utilizável, vs. 91–98% em anos
   completos) — já esperado, temporada em andamento (mesmo achado da Fase 1, agora confirmado
   também no nível de partidas utilizáveis por mercado).
4. **`score` como string livre ainda não interpretado** — necessário para Total de games/sets/
   tie-break; decisão deliberada de não fazer isso agora (pertence à Fase 3, é a fronteira exata
   entre "normalização" e "feature").
5. Nenhum problema de integridade estrutural (IDs ausentes/duplicados, linhas malformadas,
   espelhamento incorreto) foi encontrado — todas as validações do item 4 passaram com 0
   ocorrências.

---

## 9. Testes automatizados

`python -m unittest tests.test_normalization -v` → **18/18 testes passaram** (mais os 11 da Fase 1,
reexecutados sem quebrar: `python -m unittest tests.test_ingestion tests.test_normalization` →
**29/29 OK**).

Cobertura dos testes:
- Transformação pura (dados sintéticos, sem depender da base real): 2 linhas por partida,
  `match_id` estável e escopado por tour, espelhamento correto, aritmética de
  `break_points_converted`, ausência tratada como nulo (não zero), `player_id` escopado por tour,
  checagem de IDs.
- `canonical_player_id`: mesmo ID bruto em tours diferentes gera `player_id` diferentes.
- Coluna `tours`: nula para ATP, preservada para WTA (com CSVs sintéticos isolados via
  `unittest.mock.patch`, sem tocar nos dados reais).
- Integração sobre a base real gerada em `data/processed/`: 2 linhas/partida, espelhamento,
  IDs, não colisão de `player_id` entre ATP/WTA, `tours` nulo/preenchido corretamente, dtype
  anulável nas colunas de estatística, relatórios gerados, dados brutos da Fase 1 intocados.

---

## 10. Resumo executivo

- 25.555 partidas (13.372 ATP + 12.183 WTA, 2022–2026) normalizadas em 51.110 linhas
  jogador-partida, gravadas em Parquet em `data/processed/{atp,wta}/matches.parquet`.
- `match_id` estável (`TOUR:tourney_id:match_num`) e `player_id`/`opponent_id` canônicos
  (`TOUR-id_bruto`) — ambos escopados por tour depois de descobrir que os IDs brutos do Sackmann
  colidem entre ATP e WTA.
- Estatísticas de devolução construídas por espelhamento direto das estatísticas de saque do
  adversário na mesma partida (sem join entre partidas) — 0 divergências em 8 pares de campos
  verificados nas 25.555 partidas.
- Nenhum dado ausente foi preenchido com zero (dtype `Int64` anulável em toda coluna numérica de
  estatística).
- Diferença de schema `tours` (WTA-only) resolvida sem perda de informação: coluna mantida,
  `<NA>` no lado ATP.
- Cobertura suficiente para seguir para a Fase 3 em todos os 7 mercados do escopo do projeto,
  com ressalvas documentadas (Davis Cup sem superfície, descompasso temporada/ano civil, parser
  de placar ainda pendente para games/sets/tie-break).
- 29/29 testes automatizados passando (11 Fase 1 + 18 Fase 2); dados brutos da Fase 1 confirmados
  intocados.

**Parando aqui conforme instrução. Fase 3 (features Serve × Return) não foi iniciada.**
