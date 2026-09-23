# 017 — FORWARD TEST OPERACIONAL (FASE 11)

## 0. Escopo

Esta fase cria o registro prospectivo (forward test) do sistema **exatamente
como ele existe hoje** — sem retreinar, recalibrar, re-selecionar mercado,
alterar thresholds ou otimizar qualquer regra das Fases 7–10 usando os
próprios resultados do forward test enquanto ele é coletado. O objetivo é
comparar, ao longo do tempo, a classificação já produzida pela Fase 10
contra o resultado real — de forma append-only e imutável.

Código: `src/forward/` (`config.py`, `ids.py`, `versioning.py`, `inputs.py`,
`predictions.py`, `odds_snapshots.py`, `results.py`, `settlement.py`,
`metrics.py`, `paper_test.py`, `clv.py`, `build.py`).
CLI: `scripts/forward_register.py`, `scripts/forward_record_odds.py`,
`scripts/forward_settle.py`, `scripts/forward_report.py`,
`scripts/run_forward_day.py`.
Testes: `tests/test_forward.py` (36 testes; ver seção 9).
Saídas: `data/outputs/phase11/`.

Não foi calculado stake real, não houve aposta, nenhuma interface foi
criada, não se avançou para a Fase 12.

---

## 1. Congelamento de versão (item 2)

`TENNIS_RADAR_V1_FORWARD` (`src/forward/config.py::FORWARD_VERSION_ID`) é a
identificação explícita da versão operacional. Toda previsão registrada
carrega, além dela:

| Campo | Valor atual | Fonte |
|---|---|---|
| `features_version` | `FASE3_SERVE_RETURN_V1` | motor Serve×Return, inalterado desde a Fase 3 |
| `calibration_version` | `FASE6_1_PLATT_ISOTONIC_V1` | Platt/Isotonic por segmento, docs/011 |
| `rules_version` | `FASE10_V1` | regras operacionais de classificação, docs/016 |
| `git_commit` | `None` (nesta execução) | `git rev-parse HEAD`, best-effort — este repositório ainda não tem nenhum commit, então fica `None`; nunca interrompe o registro por isso |
| `historical_data_cutoff` | `2026-05-25` | `src.odds.pricing_compare.staleness_warning`, Fase 9, reaproveitada |
| `data_staleness_days` | `120` (nesta execução) | idem |

Mudar qualquer um desses valores no futuro exige uma **nova string** em
`FORWARD_VERSION_ID` — o código nunca reescreve um registro já gravado com a
versão anterior (`tests/test_forward.py::TestVersioning`).

`historical_data_cutoff`/`data_staleness_days` são recalculados no momento
do registro (não copiados do valor já gravado pela Fase 10): a base
histórica em si não muda (Fase 8.1 confirmou 0 linhas novas), mas o número
de dias decorridos desde o corte cresce a cada dia — o valor gravado é "a
defasagem no momento deste registro", e uma vez gravado fica **congelado**
como qualquer outro campo (item 1).

---

## 2. Regra fundamental — registro imutável (item 1)

`src/forward/predictions.py::register_predictions` congela, por
oportunidade, os mesmos campos já decididos pela Fase 10 (probabilidade,
odd, edge, classificação, `sample_quality`, ...) mais o congelamento de
versão da seção 1. A identidade de uma previsão (`prediction_id`) é um hash
estável de `(bookmaker, tour, match_id, market, player, side, line)` — **não
inclui `collected_at`/`decimal_odds`**, porque a odd pode ter várias
leituras ao longo do tempo (seção 4), mas a previsão em si é única por
oportunidade.

Comportamento em uma nova tentativa de registro com o mesmo
`prediction_id`:

| Situação | Resultado |
|---|---|
| valores idênticos aos já gravados | ignorado (reenvio seguro, mesma convenção das Fases 9/10) |
| qualquer um de `operational_probability`/`fair_odds`/`decimal_odds`/`model_edge`/`classification`/`sample_quality` diferente | **rejeitado** — `rejected_overwrite_attempts`, ledger não é alterado |

Testado em `TestImmutableRegistration` (registro cria a linha; reenvio
idêntico não duplica; tentativa de sobrescrever probabilidade é rejeitada;
tentativa de sobrescrever odd é rejeitada; uma linha ou `side` diferente
produz uma previsão **distinta**, não uma sobrescrita).

---

## 3. Fluxo diário / CLI (item 17)

```
python scripts/forward_register.py                                  # item 3/4: registra as oportunidades novas do dia (todas as classificações)
python scripts/forward_record_odds.py --prediction-id ... --decimal-odds ...   # item 5: novo snapshot de odd
python scripts/forward_settle.py --input-json resultado.json         # item 7/8: registra resultado real + aplica settlement
python scripts/forward_report.py                                     # item 18/19: relatório diário + dashboard cumulativo
python scripts/run_forward_day.py                                    # agregador: registra + settle + os dois relatórios
```

Nenhum comando exige bookmaker automático — odds continuam manuais (Fase 9,
Betano bloqueada, docs/015).

---

## 4. Registro pré-jogo (item 3)

Cada linha de `forward_predictions.parquet` tem, entre outros:
`registered_at`, `tour`, `tournament`, `match_id`, `player`, `opponent`,
`surface_ctx`, `market`, `side`, `line`, `operational_probability`,
`fair_odds`, `odd_minima_2pct`…`odd_minima_10pct`, `bookmaker`,
`decimal_odds`, `model_edge`, `status` (edge Fase 9), `classification`,
`reasons`, `alerts`, `explanation`, `sample_quality`, `method_selected`
(calibration status), `restricted`/`restricted_motivo`,
`extreme_probability`, `staleness_bucket`, `stake_policy` — mais os 7 campos
de versão da seção 1.

`tournament`/`opponent` vêm de um join **read-only** com
`data/outputs/phase9/odds_observed.parquet` (`inputs.py`) — a única
informação que `opportunities_evaluated.parquet` (Fase 10) não carregava.
Nenhuma probabilidade/odd/edge/classificação é recalculada neste join.

**Item 4 — todas as classificações são registradas**, inclusive
`DESCARTAR`: `register_predictions` não filtra por classificação por
padrão. Isso é o que permite a seção 8 comparar se o filtro da Fase 10
realmente separa situações melhores das piores.

---

## 5. Snapshots de odds e closing line (itens 5, 6)

`odds_snapshots.parquet` é append-only, uma linha por leitura manual de odd
por `prediction_id` (dedup só em reenvio **exato**, mesma odd no mesmo
`collected_at`). A odd usada no momento do registro já conta como o
primeiro snapshot.

`odds_snapshots.summarize_odds_movement()` calcula, por `prediction_id`:

- `first_observed_odds` / `last_observed_odds` — primeira/última leitura;
- `best_observed_odds` — a **maior** odd decimal observada; nunca assumida
  como executável (item 5 — pode já ter sumido do mercado quando lida);
- `closing_odds_observed` — a última leitura manual **antes do horário
  informado de início da partida** (`match_started_at`); se nenhum horário
  for informado, é a última leitura de qualquer horário — em ambos os
  casos, o texto `closing_odds_note` deixa explícito que isso **não é** o
  fechamento oficial da casa (item 6), só a última observação manual
  disponível.

Testado em `TestOddsSnapshots` (3 leituras preservadas e agregadas
corretamente; `closing_odds_observed` respeita o corte de início de
partida, mesmo havendo leituras depois dele).

---

## 6. Resultado e settlement (itens 7, 8)

`results.py::record_result` grava o resultado **bruto** por
`(tour, match_id)` — `match_status` (`completed`/`retirement`/`walkover`),
contagens reais de aces/double faults por jogador, sets — de forma
imutável: uma tentativa de gravar um valor bruto diferente para uma partida
já registrada é rejeitada (`test_record_result_is_immutable`).

`settlement.py::settle_prediction` decide objetivamente:

| `match_status` | Settlement |
|---|---|
| `completed`, estatística real ≠ linha | `WIN`/`LOSS` conforme o lado (`over`/`under`) |
| `completed`, estatística real == linha | `VOID` (push) |
| `completed`, estatística do jogador da previsão não encontrada no resultado | `UNRESOLVED` |
| nenhum resultado registrado ainda | `UNRESOLVED` |
| `retirement` | `BOOKMAKER_RULE_REQUIRED` |
| `walkover` | `BOOKMAKER_RULE_REQUIRED` |

**Decisão deliberada sobre retirement/walkover**: a instrução pede
explicitamente para não inventar uma política de settlement para retirement
que dependa da regra específica da bookmaker. Em vez de tentar decidir
"quando o mercado já estava matematicamente definido antes da desistência"
(o que na prática varia entre bookmakers — algumas casas liquidam o mercado
pelo valor já atingido, outras anulam toda aposta em qualquer retirement,
independentemente do valor já atingido), **este projeto marca TODO
retirement/walkover como `BOOKMAKER_RULE_REQUIRED`**, sem exceção — mais
conservador do que o que algumas casas realmente fariam, mas o único
comportamento que não inventa uma regra não documentada (nenhuma política
de retirement da Betano foi confirmada — docs/015 seção 1: a casa está
bloqueada para qualquer acesso automático). O resultado esportivo bruto
continua preservado em `results.parquet` de qualquer forma, para o dia em
que uma regra documentada existir.

`settlements.parquet` é um **log de eventos** (não um snapshot do estado
atual): uma nova linha só é gravada quando o settlement de um
`prediction_id` muda em relação à última gravada (ex.: `UNRESOLVED` →
`WIN`). Uma vez que um `prediction_id` atinge um estado **terminal**
(`WIN`/`LOSS`/`VOID`), uma tentativa de gravar um settlement terminal
diferente é rejeitada (`test_settlement_terminal_state_is_immutable`) — a
progressão natural `UNRESOLVED` → estado final continua permitida
(`test_settlement_progresses_from_unresolved_to_terminal`).

---

## 7. Métricas preditivas e de preço (itens 9, 10)

Calculadas **somente** sobre oportunidades com settlement `WIN`/`LOSS`
(outcome binário definido) — `VOID`/`UNRESOLVED`/`BOOKMAKER_RULE_REQUIRED`
são excluídas das métricas de probabilidade, mas continuam contadas
separadamente (`paper_test.py`) para transparência.

- **Brier Score** e **Log Loss** — fórmulas padrão, verificadas por exemplo
  numérico manual em `TestMetrics`;
- **Calibração por bucket** (`calibration_by_bucket`) — 10 faixas de 10 p.p.
  de probabilidade prevista, comparando `mean_predicted` vs. `observed_rate`;
- por `market`/`tour`/`surface_ctx` separadamente (`forward_metrics.parquet`).

**Limitação registrada explicitamente**: o sistema não produz uma previsão
pontual de contagem (só probabilidade de Over/Under uma linha específica),
então MAE/RMSE de contagem — usados nas Fases 4–6 para os modelos brutos —
não são recalculados aqui. Brier/Log Loss/calibração cobrem a qualidade da
**probabilidade**, que é o que de fato alimenta a decisão da Fase 10; isso é
uma limitação documentada, não um dado inventado.

**Preço** (`clv.py`): CLV% = `(odd_usada / odd_de_fechamento − 1) × 100`,
mais a diferença de probabilidade implícita (`clv_probability_diff`).
Positivo significa que a odd obtida era melhor que o fechamento — **nunca
interpretado isoladamente como prova de lucratividade** (item 10;
`test_never_interpreted_as_profit_proof_no_verdict_field` confirma que
nenhum campo tipo `verdict`/`profitable` é produzido).

---

## 8. Paper test — `PAPER_TEST_ONLY` (item 11)

`paper_test.py` simula **1 unidade fictícia flat** por oportunidade
**elegível** (`classification != DESCARTAR` — uma oportunidade `DESCARTAR`
já foi reprovada por um gate obrigatório da Fase 10 e nunca seria de fato
considerada operacionalmente; continua registrada em
`forward_predictions.parquet`, item 4, só fica fora do P&L simulado).

- `WIN` → `(odd − 1) × 1 unidade`; `LOSS` → `−1 unidade`; `VOID` → `0`
  (stake devolvido, fora do denominador do ROI);
- `cumulative_pnl_units`, `drawdown_units` (máximo recuo em unidades),
  `running_loss_streak` (sequência de perdas);
- `summarize_paper_test` devolve `roi`, `max_drawdown_units`,
  `max_consecutive_losses`, distribuição WIN/LOSS/VOID/pendente.

Todo o módulo é rotulado `PAPER_TEST_LABEL = "PAPER_TEST_ONLY"`. **Nunca**
usa Kelly, nunca stake variável, nunca recomenda valor monetário —
`test_never_uses_kelly_or_variable_stake` verifica que nenhuma coluna
`kelly_fraction`/`recommended_stake_brl` existe na saída.

---

## 9. Comparação de thresholds e de classificações (itens 12, 13)

`metrics.threshold_comparison` reporta, para cada um dos 5 thresholds já
definidos (`ATINGE_EDGE_2` … `ATINGE_EDGE_10`, cumulativos): amostra
settled, taxa observada, Brier, ROI do paper test — **sem escolher
vencedor** (nenhuma coluna `winner`/`best_threshold` é produzida,
`test_threshold_comparison_never_declares_a_winner`).

`metrics.classification_comparison` faz o mesmo por
`DESCARTAR`/`OBSERVAR`/`CANDIDATO_FRACO`/`CANDIDATO`/`CANDIDATO_FORTE` —
para permitir, com amostra suficiente, responder se a camada de decisão da
Fase 10 de fato separa situações melhores das piores (pergunta que só pode
ser respondida com uma amostra maior, ver seção 11).

---

## 10. Staleness (item 14)

`data_staleness_days` continua explícita em toda previsão registrada
(seção 1) — nesta execução, **120 dias** em todas as 5 previsões (mesmo
achado das Fases 9/10: base histórica com corte em 2026-05-25). Nenhuma
oportunidade é eliminada retrospectivamente por causa do resultado —
`forward_predictions.parquet` preserva a linha inteira independentemente do
settlement.

A análise `staleness × desempenho` (comparar Brier/CLV/ROI por faixa de
`data_staleness_days`) é possível com os dados já persistidos
(`forward_metrics.parquet` + `data_staleness_days` congelado por previsão),
mas **não é conclusiva com 5 observações** — ver seção 11 sobre amostra
mínima.

---

## 11. Checkpoints de amostra (item 15)

`metrics.sample_size_checkpoints` reporta, de forma puramente descritiva,
se a amostra atual atingiu 25/50/100/250/500 previsões — **nunca** uma
regra automática de aprovação/reprovação. Nesta execução (5 previsões
registradas), nenhum checkpoint foi atingido: qualquer leitura das métricas
das seções 7–9 nesta fase é **apenas ilustrativa do mecanismo**, não uma
conclusão sobre a qualidade do modelo.

---

## 12. Exemplo real ponta a ponta

Rodando `scripts/forward_register.py` contra as 5 oportunidades já
classificadas pela Fase 10 (mesmo lote ilustrativo de docs/016), seguido de
`scripts/forward_settle.py` com um resultado ilustrativo digitado
manualmente (Sebastian Baez 6 aces / 3 duplas faltas, Jenson Brooksby 5
aces — `data/raw/phase11_manual_example/resultado_ilustrativo.json`,
rotulado como ilustrativo, não real, CLAUDE.md §23):

| Mercado | Linha/Lado | Classificação (Fase 10) | Resultado real | Settlement | Paper P&L |
|---|---|---|---|---:|---:|
| `aces_player` | 5.5 over | `OBSERVAR` | 6 aces | `WIN` | +2.95 u |
| `aces_player` | 5.5 under | `OBSERVAR` | 6 aces | `LOSS` | −1.00 u |
| `total_aces_match` | 13.5 over | `CANDIDATO_FRACO` | 11 aces | `LOSS` | −1.00 u |
| `aces_player` | 4.5 over | `DESCARTAR` | (não casado — jogador não identificado no resultado bruto) | `UNRESOLVED` | fora do paper test |
| `double_faults_player` | 3.5 under | `DESCARTAR` | 3 duplas faltas | `WIN` | fora do paper test |

Saída real de `scripts/forward_report.py::daily_report`:

```
FORWARD TEST -- 2026-09-22

Partidas analisadas: 2
Odds registradas: 5
Candidatos: 1

aces_player Sebastian Baez Over 5.5
Modelo: 24%
Odd observada: 3.95
Edge: -0.8 p.p.
Status: OBSERVAR
Resultado: WIN
```

`cumulative_dashboard` real (`data/outputs/phase11/forward_metrics.parquet`
+ `paper_test.parquet` + `clv_analysis.parquet`):

```
Amostra: 5 oportunidades

aces_player:
N = 2
Brier = 0.5705
CLV médio = +0.00%
Paper ROI = +97.5%
```

CLV = 0,00% em todas as 5 linhas porque só existe **um** snapshot de odd por
oportunidade nesta execução (a própria odd do registro) — não há ainda uma
segunda leitura manual mais próxima do início da partida para gerar
`closing_odds_observed` diferente da odd usada. Isso é esperado com uma
única coleta e será preenchido naturalmente conforme
`scripts/forward_record_odds.py` for usado ao longo do dia (item 5).

Estes números (Brier 0,57 em 2 observações, ROI de +97,5% em 2 apostas
resolvidas) **não significam nada estatisticamente** — é exatamente o ponto
da seção 11: nenhum checkpoint de amostra foi atingido.

---

## 13. Testes (item 20)

`tests/test_forward.py`, **36 testes**:

| Classe | Cobre |
|---|---|
| `TestImmutableRegistration` (5) | registro imutável; reenvio idêntico não duplica; sobrescrita de probabilidade/odd rejeitada; linha diferente = previsão distinta |
| `TestVersioning` (2) | congelamento de versão; `git_commit` nunca lança exceção |
| `TestOddsSnapshots` (3) | múltiplos snapshots preservados e agregados; `closing_odds_observed` respeita o corte de início; resubmissão exata não duplica |
| `TestResultsAndSettlement` (9) | WIN/LOSS/VOID/UNRESOLVED; retirement e walkover → `BOOKMAKER_RULE_REQUIRED`; resultado imutável; settlement terminal imutável; progressão UNRESOLVED→terminal |
| `TestCLV` (2) | CLV positivo calculado corretamente; nunca produz veredito de lucratividade |
| `TestPaperTest` (4) | `DESCARTAR` excluído; P&L flat WIN/LOSS/VOID; ROI exclui VOID do stake; nunca usa Kelly/stake variável |
| `TestMetrics` (4) | Brier/Log Loss por exemplo numérico manual; só WIN/LOSS entram nas métricas; checkpoints só descritivos |
| `TestThresholdAndClassificationComparison` (2) | thresholds e classificações nunca declaram vencedor |
| `TestNoTemporalLeakage` (2) | probabilidade não muda após settlement; `historical_data_cutoff` nunca no futuro |
| `TestIds` (2) | id estável e determinístico; muda com qualquer campo da chave |
| `TestBuildEndToEnd` (1) | pipeline completo registro → resultado → settlement → relatórios |

Suíte cumulativa completa do projeto: **241/241 testes passando** (205 das
Fases 0–10 + 36 novos), sem nenhuma regressão (`full_suite_output_phase11.txt`).

---

## 14. Saídas (item 16)

Todas em `data/outputs/phase11/`, todas append-only:

- `forward_predictions.parquet` — previsões congeladas (item 1/2/3);
- `odds_snapshots.parquet` — leituras de odd ao longo do tempo (item 5);
- `results.parquet` — resultado bruto por partida (item 7);
- `settlements.parquet` — log de eventos de settlement (item 8);
- `forward_metrics.parquet` — Brier/Log Loss por dimensão (item 9);
- `paper_test.parquet` — P&L simulado, rotulado `PAPER_TEST_ONLY` (item 11);
- `clv_analysis.parquet` — CLV por previsão (item 10);
- `phase11_summary.json` — resumo agregado de cada execução de
  `settle_day` (thresholds, classificações, checkpoints, paper test).

---

## 15. Como interpretar os resultados (e como não interpretar)

- **Nunca** leia uma classificação `CANDIDATO_FORTE`/`CANDIDATO` como "boa
  aposta" — são rótulos operacionais objetivos, não recomendações
  (herdado da Fase 10, docs/016).
- **Nunca** trate um Brier Score ou um ROI de paper test calculado com
  poucas dezenas de observações como validação ou invalidação do modelo —
  use os checkpoints da seção 11 como referência mínima antes de tirar
  qualquer conclusão.
- **Nunca** interprete CLV positivo isoladamente como prova de
  lucratividade (item 10) — é um sinal de que a odd obtida era melhor que
  o fechamento observado, nada além disso.
- Toda métrica é sempre reportada **junto com o tamanho da amostra** —
  nenhum número desta fase deve circular sem o `N` ao lado.
- `BOOKMAKER_RULE_REQUIRED` não é um erro do sistema — é o resultado
  esperado sempre que a partida termina em retirement/walkover, até que uma
  regra de settlement específica da bookmaker seja documentada.

---

## 16. Limitações registradas

1. **Odds seguem manuais** (Betano bloqueada, docs/015) — o volume de
   oportunidades registradas depende inteiramente de quantas odds forem
   digitadas manualmente via `scripts/record_odds.py` (Fase 9) antes de
   cada partida.
2. **"Partidas analisadas" no relatório diário** conta só partidas com pelo
   menos uma odd já registrada (não o radar diário completo da Fase 8) —
   uma limitação direta da limitação anterior.
3. **Retirement/walkover sempre ficam pendentes de regra documentada**
   (seção 6) — nenhuma política de bookmaker foi confirmada nesta fase.
4. **MAE/RMSE de contagem não são recalculados** (seção 7) — só a
   qualidade da probabilidade (Brier/Log Loss/calibração) é medida.
5. **Amostra atual (5 previsões, 1 resultado ilustrativo)** é
   demonstrativa do mecanismo, não uma avaliação real do modelo — nenhum
   checkpoint de amostra (seção 11) foi atingido.
6. **Staleness de 120 dias permanece** (herdada das Fases 9/10) — qualquer
   Brier/CLV/ROI calculado nesta fase deve ser lido junto com esse número.

---

## 17. Rotina operacional diária

Camada fina sobre os scripts da seção 3, só para reduzir a rotina do dia a
poucos comandos — `scripts/daily_forward_workflow.py`. Não recalcula nada:
cada modo apenas chama, na ordem certa, as mesmas funções de
`src.radar.build` e `src.forward.build`/`odds_snapshots`/`predictions`/
`settlement` já usadas pelos scripts individuais.

```
python scripts/daily_forward_workflow.py morning   # roda o radar (Fase 8) + registra no forward test (Fase 11)
python scripts/daily_forward_workflow.py odds       # sem argumentos: lista o que está em aberto e a última odd conhecida
python scripts/daily_forward_workflow.py odds --prediction-id ID --bookmaker Betano --decimal-odds 1.80
python scripts/daily_forward_workflow.py settle --input-json resultado.json   # registra resultado + aplica settlement
python scripts/daily_forward_workflow.py report     # relatório diário + dashboard cumulativo + tamanho da amostra
```

- **`morning`** — roda `src.radar.build.run()` (Fase 8) e em seguida
  `build.register_day()` (Fase 11), imprimindo um resumo das partidas do
  dia (recebidas, resolvidas, linhas de preço, candidatos do radar) e o
  total de previsões novas registradas. Não consulta nenhuma casa de
  apostas nesta etapa — a mensagem final do modo deixa isso explícito.
- **`odds`** — sem `--prediction-id`, orienta: lista as previsões ainda sem
  settlement final (`WIN`/`LOSS`/`VOID`), com a probabilidade do modelo, a
  odd justa e a última odd observada de cada uma, para o usuário saber o
  que checar na casa. Com `--prediction-id`/`--decimal-odds` (ou
  `--input-json` para várias leituras de uma vez), grava o snapshot via
  `odds_snapshots.record_snapshot` (item 5, nunca sobrescreve leituras
  anteriores) e imprime a comparação da odd informada com o modelo
  (probabilidade, odd justa, probabilidade implícita, edge).
- **`settle`** — com `--input-json`, registra cada resultado
  (`results.record_result`, item 7) e depois roda `build.settle_day()`
  (settlement + métricas + paper test + CLV, itens 8–11). Sem
  `--input-json`, só reprocessa o settlement com os resultados já
  registrados.
- **`report`** — imprime `build.daily_report()`, `build.cumulative_dashboard()`
  (itens 18/19) e o tamanho atual de `forward_predictions.parquet`.

`tests/test_daily_forward_workflow.py` cobre só a orquestração (quais
funções cada modo chama, o que fica de fora quando não há argumentos, o
tratamento de `prediction_id` desconhecido, o roteamento do CLI) — a lógica
de negócio em si continua coberta por `tests/test_forward.py`.

---

**Parando aqui conforme instrução. Não foi calculado stake real, não houve
aposta, nenhuma interface foi criada, não se avançou para a Fase 12.
Aguardando nova instrução.**
