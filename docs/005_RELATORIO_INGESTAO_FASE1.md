# 005 — RELATÓRIO DE INGESTÃO — FASE 1

Status: concluída. Aguardando aprovação para Fase 2 (normalização).
Data: 2026-09-22.
Escopo: ATP + WTA, temporadas 2022–2026, dados brutos apenas (sem normalização, sem features, sem modelo, sem backtest).

---

## 1. Processo

### 1.1 Mudança de fonte em relação à Fase 0 (achado importante)

A Fase 0 recomendou usar diretamente `JeffSackmann/tennis_atp` e `JeffSackmann/tennis_wta`
no GitHub. Ao iniciar a Fase 1, verificamos que **esses repositórios (e também
`tennis_slam_pointbypoint`) não existem mais publicamente** — a conta `JeffSackmann` no GitHub
hoje expõe apenas 1 repositório público (`tennis_MatchChartingProject`), e
`api.github.com/repos/JeffSackmann/tennis_atp` retorna HTTP 404.

Passos de verificação (todos via GitHub API, sem depender de cache de busca):
- `GET /repos/JeffSackmann/tennis_atp` → 404.
- `GET /users/JeffSackmann/repos` → lista só `tennis_MatchChartingProject` (`public_repos: 1`).
- Busca pública confirmou relatos de terceiros (ex. issues em outros projetos que consomem esses
  dados) de que os 4 repositórios foram removidos, constatado em 2026-09-20.

**Fonte usada na prática:** mirror `Aneeshers/tennis-sackmann-archive`
(https://github.com/Aneeshers/tennis-sackmann-archive), que se apresenta como cópia arquival dos
datasets originais do Jeff Sackmann (ATP, WTA, Slam point-by-point), sob a mesma licença
**CC BY-NC-SA 4.0**, com snapshot de um commit upstream de **2026-06-25** — ou seja, feito pouco
antes dos repositórios originais saírem do ar.

**Risco documentado (CLAUDE.md §13):**
- Esta é uma fonte terceirizada (não o autor original), sem garantia formal de fidelidade byte-a-byte
  aos dados originais, embora a estrutura, colunas e conteúdo amostral batam exatamente com o
  schema historicamente documentado do Sackmann (`matches_data_dictionary.txt` incluso no mirror).
- É um snapshot de um único ponto no tempo (2026-06-25); não recebe as atualizações que o Sackmann
  fazia periodicamente após essa data.
- Se este mirror também sair do ar, não há hoje um segundo fallback validado. Mitigação sugerida
  para o futuro: guardar uma cópia própria (já é o que `data/raw/` faz) e, se necessário, avaliar
  `Tennismylife/TML-Database` (somente ATP, atualização diária, também derivado do Sackmann) como
  fonte alternativa — não avaliado em detalhe nesta fase por estar fora do pedido original.
- **Não modificamos a recomendação de licença**: continua CC BY-NC-SA 4.0, uso não comercial.

Esta mudança foi registrada como adendo em `docs/002_FONTES_DE_DADOS.md`.

### 1.2 Pipeline implementado

Código em `src/ingestion/` (reutilizável, sem dependências externas — só biblioteca padrão do
Python):

| Arquivo | Responsabilidade |
|---|---|
| `config.py` | Fontes, diretórios locais, anos (2022–2026), lista de arquivos por categoria |
| `github_source.py` | Cliente mínimo da GitHub Contents API (metadados de arquivo, commit HEAD, download) |
| `download.py` | Baixa e grava com hash SHA-256; nunca sobrescreve silenciosamente |
| `validate.py` | Inspeciona CSV (linhas, colunas, nomes de coluna, linhas malformadas) sem transformar dados |
| `coverage_report.py` | Mede % de partidas com MatchStats de saque ausentes, por ano/tour |
| `manifest.py` | Gera `data/raw/ingestion_manifest.json` e `.md` |
| `run.py` | Orquestra tudo |

CLI: `scripts/ingest_phase1.py` (`python scripts/ingest_phase1.py`).

Testes: `tests/test_ingestion.py` (`python -m unittest tests.test_ingestion -v`).

### 1.3 Regra de não sobrescrita silenciosa

Implementada em `download.fetch_and_store`:
- Arquivo local inexistente → baixa e grava (`status=downloaded`).
- Arquivo local existente com o **mesmo conteúdo** (SHA-256 idêntico) → não regrava, é tratado como
  no-op idempotente (`status=skipped_identical`). Confirmado por reexecução real do script: a
  segunda rodada retornou 17/17 `skipped_identical`, nenhum arquivo novo.
- Arquivo local existente com **conteúdo diferente** → o arquivo original **nunca é tocado**; o
  conteúdo novo é gravado ao lado, com sufixo `.conflict-<timestamp>.csv`, e sinalizado no manifesto
  como `conflict_manual_review_required` para decisão manual. Testado com rede simulada em
  `tests/test_ingestion.py::TestNoSilentOverwrite`.

### 1.4 Registro de origem

Cada arquivo no manifesto (`data/raw/ingestion_manifest.json`) registra: `source_repo`,
`source_branch`, `source_repo_commit_sha` (commit HEAD do mirror no momento da coleta —
`83733587353df8a41f2fd4f516147d5aa83f5a8d`), `source_blob_sha` (hash do blob Git do arquivo
específico), `source_download_url`, `collected_at_utc` (timestamp UTC), `sha256` local e
`size_bytes`.

---

## 2. Arquivos obtidos

17 arquivos, 0 problemas, 0 conflitos, 0 arquivos ausentes.

| Tour | Categoria | Arquivo | Linhas | Colunas | Tamanho |
|---|---|---|---:|---:|---:|
| ATP | matches | atp_matches_2022.csv | 2.917 | 49 | 595 KB |
| ATP | matches | atp_matches_2023.csv | 2.986 | 49 | 611 KB |
| ATP | matches | atp_matches_2024.csv | 3.076 | 49 | 635 KB |
| ATP | matches | atp_matches_2025.csv | 2.944 | 49 | 603 KB |
| ATP | matches | atp_matches_2026.csv | 1.449 | 49 | 294 KB (temporada em andamento) |
| ATP | players | atp_players.csv | 66.912 | 8 | 2,4 MB |
| ATP | rankings | atp_rankings_20s.csv | 516.461 | 4 | 11,4 MB |
| ATP | rankings | atp_rankings_current.csv | 36.468 | 4 | 828 KB |
| ATP | docs | matches_data_dictionary.txt | — | — | 3,7 KB |
| WTA | matches | wta_matches_2022.csv | 2.594 | 49 | 519 KB |
| WTA | matches | wta_matches_2023.csv | 2.810 | 49 | 556 KB |
| WTA | matches | wta_matches_2024.csv | 2.689 | 49 | 530 KB |
| WTA | matches | wta_matches_2025.csv | 2.795 | 49 | 552 KB |
| WTA | matches | wta_matches_2026.csv | 1.295 | 49 | 250 KB (temporada em andamento) |
| WTA | players | wta_players.csv | 70.571 | 8 | 2,3 MB |
| WTA | rankings | wta_rankings_20s.csv | 412.744 | 5 | 10,2 MB |
| WTA | rankings | wta_rankings_current.csv | 35.145 | 5 | 887 KB |

Salvos em `data/raw/sackmann_atp/` e `data/raw/sackmann_wta/`, sem alteração de conteúdo
(arquivos gravados byte a byte como recebidos da fonte). Manifesto completo em
`data/raw/ingestion_manifest.json` / `.md`.

Observação: `atp_players.csv`/`wta_players.csv` e `atp_rankings_*`/`wta_rankings_*` não são
recortados por ano — são arquivos únicos que cobrem todo o histórico (players desde a era aberta;
rankings desde os anos 2020 no arquivo `_20s`, mais um arquivo `_current` com o ranking recente).
Isso é intencional: identidade de jogador e ranking point-in-time (CLAUDE.md §3/§10) exigem o
histórico completo, não só 2022–2026.

---

## 3. Comparação de schema ATP × WTA

**Matches:** schema **idêntico** entre ATP e WTA — as 49 colunas e a ordem são exatamente as
mesmas em `atp_matches_*.csv` e `wta_matches_*.csv` (confirmado programaticamente e coberto por
teste automatizado).

**Players:** schema **idêntico** — 8 colunas iguais em ambos:
`player_id, name_first, name_last, hand, dob, ioc, height, wikidata_id`.

**Rankings:** schema **diferente** — ATP tem 4 colunas, WTA tem 5:

| Coluna | ATP | WTA |
|---|---|---|
| ranking_date | sim | sim |
| rank | sim | sim |
| player | sim | sim |
| points | sim | sim |
| tours | não | **sim** |

`tours` (WTA) aparentemente indica o número de torneios contados no cálculo do ranking daquela
semana. Isso não bloqueia nada na fase atual (não normalizamos ainda), mas **a Fase 2 precisa
tratar essa assimetria explicitamente** ao unificar o schema de rankings entre os dois tours (ex.:
descartar `tours` ou mapear para `NULL` no lado ATP).

---

## 4. Campos relevantes para saque e devolução

Presentes em todos os arquivos `*_matches_*.csv` (idênticos ATP/WTA), por jogador
vencedor (`w_*`) e perdedor (`l_*`):

| Campo | Significado | Uso nos mercados (CLAUDE.md §18) |
|---|---|---|
| `ace` | número de aces | Aces por jogador, Total de aces |
| `df` | número de duplas faltas | Double faults |
| `svpt` | pontos de saque disputados | Denominador para taxas (Ace%, DF%) |
| `1stIn` | primeiros saques certos | First serve % |
| `1stWon` | pontos vencidos no 1º saque | First serve points won |
| `2ndWon` | pontos vencidos no 2º saque | Second serve points won |
| `SvGms` | games de saque disputados | Hold%, duração esperada da partida |
| `bpSaved` | break points salvos | Hold% sob pressão |
| `bpFaced` | break points enfrentados | Break% do adversário (devolução) |

Complementado por: `surface` (obrigatório por CLAUDE.md §8), `tourney_date`/`tourney_level`/`round`
(contexto temporal e nível de torneio), `winner_rank`/`loser_rank`/`*_rank_points` (força do
adversário point-in-time, CLAUDE.md §7), `best_of`/`minutes` (duração esperada), `winner_id`/
`loser_id` (identidade estável de jogador).

**Importante (regra do matchup, CLAUDE.md §2):** como o dataset é por partida e não por
jogador-oportunidade, para calcular `Serve A × Return B` a Fase 2/3 precisará reconstruir, por
jogador, tanto sua própria performance de saque (`w_*`/`l_*` quando ele é winner/loser) quanto o
que ele permitiu ao devolver — isto é, os `w_*`/`l_*` do **adversário** em cada partida em que ele
foi o devolvedor. Isso é factível com os campos disponíveis, mas é trabalho de modelagem da Fase 2/3,
não desta fase.

---

## 5. Problemas de cobertura sinalizados

Nenhum arquivo ausente, incompleto (0 linhas) ou com linhas malformadas (`ragged_rows`) nesta
janela 2022–2026, para nenhum dos dois tours. Porém, **cobertura de MatchStats dentro dos arquivos
não é 100%** — percentual de partidas com pelo menos um campo de estatística de saque vazio
(`coverage_report.py`):

| Ano | ATP (% partidas sem stats) | WTA (% partidas sem stats) |
|---|---:|---:|
| 2022 | 5,90% | 4,16% |
| 2023 | 5,73% | 8,47% |
| 2024 | 1,98% | 2,42% |
| 2025 | 8,80% | 2,93% |
| 2026 | 17,81% | 14,13% |

Interpretação:
- Anos completos (2022–2025) ficam entre ~2% e ~9% de partidas sem MatchStats — plausivelmente
  partidas de níveis inferiores ou torneios cuja fonte primária (ATP/WTA) não reportou estatísticas
  detalhadas. **Não é um erro de ingestão** (os arquivos vieram completos da fonte); é uma limitação
  conhecida do próprio dataset Sackmann.
- 2026 tem lacuna maior (17,8% ATP / 14,1% WTA) porque a temporada está em andamento (hoje é
  2026-09-22) — parte das partidas mais recentes ainda não teve as estatísticas publicadas/coletadas
  pela fonte original. Isso é esperado e não indica problema de qualidade; deve só ser levado em
  conta se/quando previsões "ao vivo" forem feitas (fora do escopo atual, CLAUDE.md §24).
- **Ação para a Fase 2:** ao construir features, tratar partidas sem MatchStats como dado ausente
  explícito (não preencher com zero), e medir se a exclusão dessas partidas introduz viés
  (ex.: torneios menores sistematicamente sem stats).

Nenhum outro problema de cobertura foi identificado nesta janela — mas vale registrar que **esta
ingestão cobriu só 2022–2026** por instrução explícita; não avaliamos aqui a cobertura de anos
anteriores (isso já foi discutido qualitativamente na Fase 0).

---

## 6. Testes de integridade executados

`python -m unittest tests.test_ingestion -v` → **11/11 testes passaram**:

- Lógica de não sobrescrita silenciosa (rede simulada, sem chamadas HTTP reais):
  - primeiro download grava o arquivo;
  - segundo download com conteúdo idêntico é no-op (`skipped_identical`), arquivo inalterado;
  - terceiro download com conteúdo diferente **não altera o arquivo original**, grava um
    `.conflict-*` separado e sinaliza revisão manual.
- Integridade dos dados reais baixados:
  - manifesto sem problemas (`n_issues == 0`);
  - todos os 17 arquivos esperados existem em disco;
  - SHA-256 registrado no manifesto bate com o conteúdo atual em disco (detecta corrupção/edição
    posterior);
  - todos os arquivos de partidas têm linhas > 0 e contêm as colunas de saque/devolução esperadas;
  - schema de `matches` é idêntico entre ATP e WTA;
  - schema de `players` é idêntico entre ATP e WTA;
  - schema de `rankings` reflete exatamente a diferença conhecida (`tours` só no WTA);
  - nenhuma linha malformada (`ragged_rows == 0`) em nenhum arquivo de partidas.

---

## 7. Resumo executivo

- Fonte original da Fase 0 (`JeffSackmann/tennis_atp`/`tennis_wta`) **saiu do ar**; usamos o mirror
  arquival `Aneeshers/tennis-sackmann-archive` (mesma licença CC BY-NC-SA 4.0, snapshot de
  2026-06-25) como substituto documentado, com risco registrado.
- 17 arquivos brutos (ATP + WTA, 2022–2026, + players e rankings completos) baixados,
  validados e catalogados em `data/raw/ingestion_manifest.json` / `.md`, sem qualquer normalização.
- Schema de `matches` e `players` é idêntico entre ATP e WTA; `rankings` difere em 1 coluna
  (`tours`, só WTA) — mapeado para tratamento na Fase 2.
- Cobertura de estatísticas de saque é boa (~91–98%) nos anos completos, mais fraca em 2026
  (temporada em andamento) — dentro do esperado, não é falha de ingestão.
- Pipeline é idempotente e nunca sobrescreve silenciosamente: reexecuções subsequentes não alteram
  nada quando a fonte não mudou, e reportam explicitamente qualquer divergência.
- 11 testes automatizados de integridade passando.

**Parando aqui conforme instrução. Fase 2 (normalização) não foi iniciada.**
