# Fase 8.1 — Atualização incremental da base histórica

Execução real em **2026-09-22**. Escopo: eliminar (ou reduzir) a defasagem
entre a base histórica (`data/processed/{tour}/matches.parquet`, que termina
em 2026-05-25) e as partidas atuais de setembro de 2026, sem alterar
modelos, calibração ou regras das Fases 3–7, sem consultar casas de apostas
e sem coletar odds.

**Resultado resumido:** a investigação de fontes não encontrou nenhuma fonte
estruturada ou HTTP que forneça, para o período 2026-05-26 a 2026-09-22,
as estatísticas de saque/devolução exigidas pelo schema histórico, sem
contornar bloqueio anti-bot. Por isso, **nenhuma partida nova foi
incorporada** nesta execução (0 ATP, 0 WTA). O mecanismo de atualização
incremental (investigação, deduplicação, resolução de novos jogadores,
normalização, reconstrução de features, comparação do radar) foi construído
e testado por completo (21 testes, todos com dados reais ou sintéticos
realistas) e está pronto para consumir dados assim que uma fonte adequada
existir ou for aprovada. Os dados originais das Fases 1 e 2 permanecem
byte-a-byte idênticos (hash SHA-256 verificado antes/depois).

---

## 0. Escopo

Implementado (`src/incremental/`):

- `sources.py` — investigação de fontes, seguindo a ordem de prioridade do
  enunciado, com evidência verificável (HTTP status, comparação de commit
  SHA, verificação de colunas de schema real).
- `dedupe.py` — deduplicação contra a base existente por `match_id` estável
  e por contexto (data + torneio + dupla de jogadores + placar).
- `identity_new.py` — resolução de jogadores novos (reaproveita o
  resolvedor de 4 níveis da Fase 8, `src.radar.identity.PlayerIndex`);
  jogador não encontrado recebe id sintético `NEW-<nome>`, nunca reaproveita
  silenciosamente o id de outro jogador.
- `merge.py` — integra partidas novas (dedupe → resolução →
  `src.normalization.matches.transform_raw_matches`, a MESMA função da Fase
  2, extraída para reuso) e reconstrói features com o motor exato da Fase 3
  (`build_player_profile` + `build_matchup_table`, sem nenhuma alteração).
- `build.py` — orquestrador: investiga → integra (se houver fonte) → roda o
  radar da Fase 8 contra a base resultante → compara com o radar anterior →
  grava cobertura e hashes de preservação.
- `scripts/run_incremental_update.py` — CLI (`python scripts/run_incremental_update.py`).

Alterações mínimas em código de fases anteriores (comportamento idêntico,
verificado por hash — ver seção 7):

- `src/normalization/matches.py`: a lógica de transformação de
  `build_player_match_table` foi extraída para uma função pública
  `transform_raw_matches(raw, tour)`, reaproveitada tanto pela Fase 2
  quanto pela Fase 8.1 — nunca um segundo schema.
- `src/radar/features_future.py` e `src/radar/build.py`: parâmetros
  opcionais `override_path` / `historical_overrides` / `output_dir`,
  aditivos e com default `None` (= comportamento idêntico ao da Fase 8),
  para permitir rodar o radar contra uma base alternativa sem tocar em
  `data/processed/` nem em `data/outputs/phase8/`.

Não implementado (fora de escopo, por instrução explícita): scraping de
odds, cálculo de stake, apostas automáticas, interface.

---

## 1. Investigação de fontes (item 1)

Ordem de prioridade seguida: (1) dataset estruturado; (2) mirror atualizado
do Sackmann; (3) GitHub/repositório equivalente; (4) HTTP estruturado; (5)
Tennis Abstract; (6) Firecrawl; (7) browser automation. Evidência completa
em `data/raw/incremental_2026/source_investigation.json` (formato bruto) e
`.md` (tabela). Firecrawl não está disponível como ferramenta neste
ambiente (mesma situação da Fase 8); browser automation não foi usada
(instrução explícita: "não contornar bloqueios anti-bot").

| fonte | prioridade | status | motivo |
|---|---|---|---|
| `JeffSackmann/tennis_atp` | 2 | indisponível | HTTP 404 — repositório original não existe mais publicamente (reconfirmado; mesma conclusão da Fase 1) |
| `JeffSackmann/tennis_wta` | 2 | indisponível | HTTP 404 |
| `Aneeshers/tennis-sackmann-archive` (mirror usado na Fase 1) | 2 | indisponível | mesmo commit SHA e mesmo blob SHA de `atp_matches_2026.csv`/`wta_matches_2026.csv` gravados na ingestão da Fase 1 — o mirror é um snapshot congelado, não recebeu nenhum commit novo |
| `abbygracemorrow/ATP-data` (derivado de dataset Kaggle "ATP Tennis 2000-2023 Daily Pull") | 3 | schema inadequado | 13 colunas reais (`Tournament, Date, Series, Court, Surface, Round, Best of, Player_1, Player_2, Winner, Rank_1, Rank_2, Score`) — **faltam as 18 colunas de estatísticas de saque/devolução** (aces, double faults, service points, ...); além disso, só ATP |
| `Mriganka-codes/tennis_data` | 3 | schema inadequado / fora de escopo | formato JSON (não tabular), cobre só "partidas de hoje" (não histórico), e é um scraper de **tennisexplorer.com com odds** — descartado também por conter odds, fora do escopo desta fase |
| `atptour.com` (rankings, match stats) | 4 | indisponível | HTTP 403 — bloqueio anti-bot (Akamai), mesma conclusão da Fase 8 |
| `espn.com` (resultados por jogador) | 4 | schema inadequado | HTTP 200 (acessível), mas fornece somente placar/rodada/adversário — **nenhuma estatística de saque** |

**Achado adicional relevante:** por inspeção direta do código (`src/baselines/rate_models.py`,
`src/probabilistic/build.py`, `src/features/profile.py`), confirmou-se que
`player_rank`/`opponent_rank`/`score` **não alimentam nenhum modelo** desta
base — são usados somente para segmentação descritiva de erro em backtests
(`ranking_bucket`, Fase 4). Ou seja: mesmo se uma fonte "somente resultado"
(placar + ranking, sem aces/DFs) fosse incorporada, o resultado seria
**exatamente zero mudança** em qualquer probabilidade, odd justa ou odd
mínima do radar — o ganho seria puramente cosmético, com o custo real de
introduzir um segundo schema, uma fonte de proveniência/licença não
verificada (dataset Kaggle de terceiro, ATP apenas) e risco de
inconsistência de identidade. Por isso a decisão foi não incorporar dados
somente-resultado — reaproveitar o `ranking_bucket`, se algum dia for usado
como feature real, exigiria uma decisão de modelagem separada (fora do
escopo desta fase: "não retreinar/recalibrar").

**Conclusão:** nenhuma fonte investigada é, ao mesmo tempo, (a) estruturada
ou acessível sem bloqueio anti-bot e (b) portadora das estatísticas de
saque/devolução exigidas pelo schema histórico. `adequate_source_found =
false`.

---

## 2. Dados mínimos necessários (item 2)

`src/incremental/config.py:RAW_SCHEMA_COLUMNS` define as 39 colunas do CSV
bruto Sackmann exigidas por `transform_raw_matches` (torneio, superfície,
rodada, jogadores, placar, ranking, e as 18 colunas de saque/devolução:
aces, double faults, service points, first serves in, first serve points
won, second serve points won, service games, break points saved/faced —
para vencedor e perdedor). `evaluate_candidate_repo` verifica isso contra o
cabeçalho REAL de cada fonte candidata (não contra a descrição do README) —
foi assim que `abbygracemorrow/ATP-data` foi corretamente classificada como
inadequada (faltam 18/18 colunas de estatística).

---

## 3. Preservação (item 3)

- Nenhum arquivo de `data/raw/sackmann_atp/`, `data/raw/sackmann_wta/` ou
  `data/processed/{tour}/matches.parquet` foi escrito nesta fase — hash
  SHA-256 idêntico antes/depois (`historical_data_unchanged: true` em
  `phase8_1_summary.json`, e testado em `tests/test_incremental.py:TestHistoricalDataPreserved`).
- Toda evidência da investigação de fontes fica em
  `data/raw/incremental_2026/source_investigation.{json,md}`, com fonte,
  status HTTP, commit/blob SHA comparado e timestamp de checagem.
- Caso uma fonte adequada seja aprovada no futuro, o raw incremental
  esperado vai em `data/raw/incremental_2026/{tour}_novas_partidas.csv`
  (schema Sackmann, sem `winner_id`/`loser_id` — resolvidos pelo pipeline) —
  nenhum arquivo desses existe nesta execução.
- A base combinada (quando há partidas novas) vai em
  `data/processed/incremental_2026/{tour}/matches.parquet` — **nunca**
  em `data/processed/{tour}/matches.parquet` (Fase 2).

---

## 4. Deduplicação (item 4)

`src/incremental/dedupe.py:detect_duplicates` compara cada partida
incremental contra `data/processed/{tour}/matches.parquet` por:

1. `match_id` estável (`{TOUR}:{tourney_id}:{match_num}`, igual à Fase 2);
2. contexto (data + torneio + dupla de jogadores em qualquer ordem +
   placar), como reforço para o caso de `match_num` não ser estável entre
   fontes diferentes.

Nunca sobrescreve uma partida existente — uma partida marcada como
duplicata é simplesmente descartada da integração (não gera erro, não
substitui a linha histórica). Testado com 3 casos reais (duplicata exata
por `match_id`, duplicata por contexto com `match_id` diferente, partida
genuinamente nova não sinalizada) — ver seção 9.

---

## 5. Normalização (item 5)

`transform_raw_matches` (extraída de `src/normalization/matches.py`, usada
sem nenhuma alteração de regra) aplica exatamente as mesmas regras da Fase
2: duas linhas por partida (perspectiva vencedor/perdedor), dtypes Int64
anuláveis (nunca preenche estatística ausente com 0), mesma ordem de
colunas (`OUTPUT_COLUMNS`). Verificado por teste que reexecuta
`build_player_match_table` original e compara byte-a-byte com
`data/processed/{tour}/matches.parquet` — idêntico (ver seção 7).

Resolução de novos jogadores (`identity_new.py`): reaproveita o resolvedor
de 4 níveis da Fase 8 (exact/alias/fuzzy_review/unresolved) contra
`data/processed/{tour}/players.parquet`. Um jogador que não resolve recebe
um id sintético `NEW-<nome-normalizado>` — nunca reaproveita o id de um
jogador existente por engano, e dois jogadores desconhecidos diferentes
sempre recebem ids diferentes (testado).

---

## 6. Features (item 6)

`merge.rebuild_features(combined)` chama exatamente
`src.features.profile.build_player_profile` +
`src.features.matchup.build_matchup_table` — as mesmas duas funções que
`src.features.build.build_features_for_tour` chama na Fase 3, sem nenhuma
modificação. Nenhum modelo é retreinado.

Prova de ausência de leakage (`tests/test_incremental.py:TestNoLeakage`,
com dados reais + uma partida sintética realista entre dois jogadores reais
da base, datada de 2026-06-01):

1. a taxa de aces no saque (`player_serve_ace_rate_career`) calculada pela
   partida nova bate exatamente com `soma(aces) / soma(service_points)` de
   TODAS as partidas reais anteriores a 2026-06-01 desse jogador — nenhuma
   informação da própria partida nova entra no cálculo;
2. as features de uma partida histórica anterior (antes e depois de incluir
   a partida nova na base) são idênticas linha a linha — a partida nova,
   datada no futuro relativo às demais, não contamina nenhuma janela
   anterior.

---

## 7. Consistência com as Fases 4–7 (item 7)

Nenhuma configuração, modelo ou calibrador das Fases 4–7 foi tocado.
Verificações realizadas:

- `src.normalization.matches.build_player_match_table` (Fase 2, chamada
  original) reexecutada e comparada, com `pandas.testing.assert_frame_equal`,
  contra `data/processed/{atp,wta}/matches.parquet` já existente —
  **idêntico**, confirmando que a extração de `transform_raw_matches` não
  alterou nenhum comportamento.
- O radar da Fase 8 (`src/radar/build.py:run()`), chamado sem
  `historical_overrides` (comportamento padrão, igual à Fase 8), produz
  `precos_por_linha.parquet`, `odds_minimas_por_edge.parquet`,
  `previsoes_por_partida.parquet` e `partidas_resolvidas.parquet`
  **byte-a-byte idênticos** (SHA-256) aos gerados na Fase 8 original.

---

## 8. Radar: antes vs. depois (item 8)

Como `n_new_matches_incorporated == 0` nos dois tours, o radar "depois"
(`data/outputs/phase8_1/radar_atualizado/`) foi gerado a partir da MESMA
base histórica do radar "antes" (`data/outputs/phase8/`). A comparação
(`data/outputs/phase8_1/comparacao_radar_antes_depois.csv`), feita linha a
linha por `match_id + player_id + market + line + side`, confere:

| métrica | valor |
|---|---|
| linhas de preço comparadas | 1972 |
| linhas com `prior_matches_career` alterado | 0 |
| linhas com `calibrated_probability` alterada | 0 |
| linhas com `fair_odds` alterada | 0 |
| linhas com `sample_bucket_career` alterado | 0 |

**Nenhuma mudança em nenhuma linha.** Isso não é interpretado como "radar
validado" nem como melhora — é a consequência direta e esperada de nenhum
dado novo ter sido incorporado (item 8 da instrução: "não interpretar
automaticamente mudança como melhora" — aqui se aplica o inverso: ausência
de mudança também não deve ser lida como "nada mudou no mundo real", apenas
como "nenhum dado novo entrou nesta execução"). O mecanismo de comparação
(`_compare_radar_outputs`) foi validado end-to-end com dados sintéticos que
de fato mudam o resultado — ver `TestRadarAfterUpdate` (seção 9): ao
incorporar manualmente uma partida real fabricada, o radar recalculado com
`historical_overrides` roda com sucesso sobre a base combinada.

---

## 9. Cobertura (item 9)

| métrica | valor |
|---|---|
| partidas novas ATP incorporadas | **0** |
| partidas novas WTA incorporadas | **0** |
| intervalo temporal da defasagem | 2026-05-26 a 2026-09-22 (**120 dias**) |
| % das partidas incorporadas com estatísticas completas | não aplicável (0 partidas incorporadas) |
| mercados que continuam calculáveis | os mesmos 3 aprovados nas Fases 5/6/6.1/7: aces por jogador, total de aces, double faults — usando a base até 2026-05-25, sem nenhuma alteração |
| jogadores atuais ainda sem histórico suficiente | inalterado em relação à Fase 8 — 5 jogadores não resolvidos (ver tabela abaixo); nenhum jogador novo foi encontrado nesta execução |

Jogadores não resolvidos (herdados da Fase 8, `data/outputs/phase8/jogadores_nao_resolvidos.csv`, inalterado):

| tour | torneio | jogador (bruto) | motivo |
|---|---|---|---|
| WTA | Korea Open (Seoul) | A. Korneeva | sobrenome + inicial ambíguo: 2 candidatos |
| WTA | Korea Open (Seoul) | S. Park | sobrenome + inicial ambíguo: 11 candidatos |
| WTA | Korea Open (Seoul) | Y. Ku | sobrenome + inicial ambíguo: 2 candidatos |
| WTA | Korea Open (Seoul) | Y. Ma | sobrenome + inicial ambíguo: 3 candidatos |
| WTA | Singapore Tennis Open | Xinyu Wang | sobrenome + inicial ambíguo: 7 candidatos |

---

## 10. Testes (item 10)

`tests/test_incremental.py` — **21 testes, todos passando**:

| requisito da instrução | classe de teste |
|---|---|
| ausência de duplicatas | `TestDeduplication` (3 testes: match_id exato, contexto com match_id diferente, partida genuinamente nova) |
| compatibilidade de schema | `TestSchemaCompatibility` (2 testes: colunas de saída idênticas a `OUTPUT_COLUMNS`, schema bruto cobre todos os campos mínimos do item 2) |
| continuidade temporal | `TestTemporalContinuity` (base combinada permanece ordenada cronologicamente após integrar uma partida nova) |
| ausência de leakage | `TestNoLeakage` (2 testes — ver seção 6) |
| identidade dos jogadores | `TestPlayerIdentity` (3 testes: jogador existente resolve exato, jogador desconhecido recebe id sintético nunca reaproveitado, dois desconhecidos recebem ids distintos) |
| idempotência | `TestIdempotentIncrementalRun` (rodar a integração 2x com a mesma partida — a segunda vez é corretamente detectada como duplicata, 0 partidas novas) |
| preservação dos dados históricos | `TestHistoricalDataPreserved` (hash do `matches.parquet` original inalterado após rodar toda a integração + reconstrução de features) |
| radar funcionando após atualização | `TestRadarAfterUpdate` (roda `radar_build.run()` com `historical_overrides` apontando para uma base combinada sintética com 1 partida nova real — completa com sucesso) |
| investigação de fontes (auxiliar, não pedido explicitamente mas necessário para tornar a conclusão da seção 1 verificável) | `TestSourceInvestigation` (6 testes com fetchers mockados — reconfirma a lógica de decisão de cada fonte sem depender de rede a cada execução do teste) |

Suíte cumulativa completa (`tests.test_ingestion` … `tests.test_incremental`):
**149 testes, todos passando** (128 das Fases 1–8 + 21 novos da Fase 8.1),
confirmando zero regressão.

---

## 11. Respostas finais

**1. Foi possível atualizar a base até uma data próxima da atual?**
Não. A investigação (item 1) não encontrou nenhuma fonte estruturada ou
HTTP que forneça estatísticas de saque/devolução para 2026-05-26 em diante
sem contornar bloqueio anti-bot. A base permanece com corte em 2026-05-25.

**2. Qual fonte foi usada?**
Nenhuma. Todas as fontes investigadas foram rejeitadas: os repositórios
originais do Sackmann não existem mais (HTTP 404), o mirror usado na Fase 1
está congelado no mesmo commit desde então, os repositórios GitHub
alternativos encontrados carecem das colunas de estatística exigidas (ou
são scrapers de odds, fora de escopo), os endpoints oficiais ATP/WTA
continuam bloqueados por proteção anti-bot, e fontes acessíveis como ESPN
fornecem somente placar — sem nenhum efeito sobre os modelos (comprovado
por inspeção de código, seção 1).

**3. Qual a defasagem restante?**
A mesma da Fase 8: **120 dias** (2026-05-25 até 2026-09-22), inalterada.

**4. A cobertura de aces/double faults continua adequada?**
Sim, para o período já coberto (até 2026-05-25) — nada foi alterado nessa
base. Para o período 2026-05-26–2026-09-22, a cobertura é **0%** (nenhuma
partida desse intervalo foi incorporada, porque nenhuma fonte disponível
fornece essas estatísticas).

**5. Quanto as previsões do radar mudaram após incorporar os dados recentes?**
**Nada mudou** — 0 de 1972 linhas de preço, porque 0 partidas novas foram
incorporadas. Essa comparação (byte-a-byte) serve como prova de
não-regressão/idempotência do pipeline, não como avaliação de ganho
preditivo (não havia dado novo para avaliar).

**6. A base está pronta para iniciar a Fase 9?**
Não fica "mais pronta" do que já estava ao final da Fase 8 — a defasagem de
120 dias documentada em `docs/013` permanece exatamente a mesma. Isso deve
ficar registrado como um risco explícito para quem decidir avançar para a
Fase 9 (consulta pontual de odds reais): comparar odds de mercado com
previsões baseadas em uma base ~4 meses desatualizada reduz a utilidade
prática da comparação, mesmo que o pipeline em si esteja correto e testado.

---

Não foi consultada nenhuma casa de apostas. Não foi coletada nenhuma odd
real. Não foi calculado stake. Nenhuma aposta automática ou interface foi
criada. Não houve avanço para a Fase 9.

**Fim da Fase 8.1 — aguardando nova instrução.**
