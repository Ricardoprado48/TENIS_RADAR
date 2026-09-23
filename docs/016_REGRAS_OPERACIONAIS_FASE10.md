# 016 — REGRAS OPERACIONAIS DE CLASSIFICAÇÃO (FASE 10)

## 0. Escopo

Esta fase cria uma camada de decisão reproduzível que classifica cada
comparação já produzida pela Fase 9 (`probabilidade do modelo × linha × odd
observada × qualidade dos dados`) em um dos 5 estados operacionais definidos
pela instrução, usando regras determinísticas e explicáveis — **sem
retreinar, recalibrar, re-selecionar mercado ou alterar qualquer
probabilidade/odd/edge já calculada nas Fases 7/8/9**.

Código: `src/decision/` (`config.py`, `sample_quality.py`,
`staleness_policy.py`, `inputs.py`, `rules.py`, `build.py`).
CLI: `scripts/evaluate_opportunities.py`.
Testes: `tests/test_decision.py` (33 testes; ver seção 9).
Saídas: `data/outputs/phase10/`.

Não foi calculado stake, não houve aposta, nenhuma interface foi criada,
não se avançou para a Fase 11.

---

## 1. Critérios obrigatórios (item 2) — os "gates"

Uma oportunidade só avança além de `DESCARTAR` se **todos** os 8 critérios
abaixo forem verdadeiros (`src/decision/rules.py::_compute_gates`). Qualquer
falha produz `DESCARTAR`, com o motivo exato de cada gate que falhou —
nunca uma associação silenciosa:

| Gate | O que verifica |
|---|---|
| `mercado_aprovado` | `market` está entre os 3 já aprovados (Fases 5/6/7) |
| `linha_existe_na_distribuicao` | a odd foi casada com o radar (Fase 9 `matched=True`) |
| `previsao_nao_restrita` | `restricted == False` (herdado da Fase 7 — ver seção 6) |
| `identidade_confiavel` | os dois jogadores resolvidos por `exact`/`alias` (nunca `fuzzy_review`) |
| `probabilidade_operacional_valida` | `operational_probability` presente e em `(0, 1)` |
| `odd_acima_do_limite_configurado` | `decimal_odds >= 1.30` (piso de liquidez, ver seção 5) |
| `amostra_historica_minima` | `sample_quality != LOW` (ver seção 3) |
| `staleness_registrada` | `historical_data_cutoff`/`data_staleness_days` presentes |

O gate de amostra usa a classificação `sample_quality` (item 5) diretamente
como o "requisito mínimo" pedido pela instrução — uma amostra `LOW` nunca
avança, mesmo com edge positivo (ver seção 4, pergunta 2).

---

## 2. Estados operacionais (item 3)

```
DESCARTAR
OBSERVAR
CANDIDATO_FRACO
CANDIDATO
CANDIDATO_FORTE
```

Nenhum rótulo usa "aposta garantida"/"aposta certa"/"garantia"/"lucro
garantido" — testado explicitamente em
`tests/test_decision.py::TestExplanation::test_no_forbidden_terms_in_any_explanation`,
que varre `config.FORBIDDEN_TERMS` contra o texto de explicação de 4 cenários
diferentes (incluindo os que geram `DESCARTAR`).

Depois que todos os gates passam, a escada de classificação
(`rules.evaluate_opportunity`) combina 3 sinais:

1. **Edge atingido** (item 4) — o rótulo já calculado pela Fase 9
   (`ABAIXO_DO_LIMITE` → `ATINGE_EDGE_10`), comparado contra o **piso mínimo
   de edge do mercado** (item 9, ver seção 5);
2. **Qualidade de amostra** (item 5) — `MEDIUM` ou `HIGH` (já que `LOW` foi
   eliminado no gate);
3. **Staleness** (item 6) — só entra como um **teto**: bloqueia
   `CANDIDATO_FORTE` quando a defasagem é `MUITO_DEFASADO`, nunca rebaixa
   nenhum outro estado.

| Situação | Estado |
|---|---|
| edge abaixo do piso do mercado | `OBSERVAR` |
| edge exatamente no piso do mercado | `CANDIDATO_FRACO` |
| edge acima do piso, abaixo de 7,5%, amostra `MEDIUM` | `CANDIDATO_FRACO` |
| edge acima do piso, abaixo de 7,5%, amostra `HIGH` | `CANDIDATO` |
| edge ≥ 7,5%, amostra `MEDIUM` | `CANDIDATO` |
| edge ≥ 7,5%, amostra `HIGH`, staleness ≠ `MUITO_DEFASADO` | `CANDIDATO_FORTE` |
| edge ≥ 7,5%, amostra `HIGH`, staleness `MUITO_DEFASADO` | `CANDIDATO` (capado, com alerta) |

Edge maior nunca é automaticamente "melhor" isoladamente — dois testes
verificam isso diretamente: `test_extreme_probability_never_auto_upgrades_or_downgrades`
(uma probabilidade ≥90% não muda a classificação, só adiciona um alerta) e
`test_candidato_forte_capped_when_staleness_muito_defasado` (edge máximo +
amostra `HIGH` ainda cai para `CANDIDATO`, nunca `CANDIDATO_FORTE`, sob
defasagem alta).

---

## 3. Qualidade de amostra (item 5)

`sample_quality = LOW | MEDIUM | HIGH`, fixada em `config.py` **antes de
rodar contra os dados reais**, combinando 4 sinais — nenhum deles
recalculado, todos já produzidos pelo motor point-in-time da Fase 3/8
(`prior_matches_career`, `prior_service_points_career`,
`prior_return_points_career`, `surface_prior_matches`, reobtidos via
`src.radar.features_future.build_future_feature_rows`, reaplicado sobre
`data/outputs/phase8/partidas_resolvidas.parquet` — mesmo motor, nenhuma
feature nova):

| Nível | Requisito |
|---|---|
| `HIGH` | ≥50 partidas **e** ≥300 service points **e** ≥300 return points **e** ≥10 partidas na mesma superfície |
| `MEDIUM` | ≥10 partidas **e** ≥60 service points **e** ≥60 return points |
| `LOW` | qualquer coisa abaixo disso, **ou** qualquer sinal ausente, **ou** qualquer flag de baixa confiança já herdada (`cold_start`/`insufficient_history`/`calibrator_insufficient_sample`) |

Dado ausente nunca é tratado como suficiente — cai direto em `LOW`
(`test_low_when_missing_data_never_treated_as_ok`).

---

## 4. Staleness (item 6)

3 faixas objetivas, fixadas a priori (`config.py`, antes de olhar os
resultados desta execução):

| Faixa | `data_staleness_days` |
|---|---|
| `ATUAL` | ≤ 30 dias |
| `MODERADAMENTE_DEFASADO` | 31–90 dias |
| `MUITO_DEFASADO` | > 90 dias (ou ausente — cautela máxima) |

`CANDIDATO_FORTE` nunca é permitido quando a faixa é `MUITO_DEFASADO`
(`staleness_policy.blocks_candidato_forte`, testado isoladamente e via
`rules.evaluate_opportunity`).

**Achado real desta execução**: a base histórica está com corte em
2026-05-25 (docs/013/014) — qualquer execução feita hoje (setembro/2026)
produz ~120 dias de defasagem, ou seja, **cai sempre em `MUITO_DEFASADO`**
com os limiares acima. Isso significa que, com os dados atuais, **nenhuma
oportunidade pode chegar a `CANDIDATO_FORTE`**, mesmo com edge máximo e
amostra `HIGH` — confirmado na tabela real da seção 8 (a linha de
`total_aces_match` com edge positivo fica em `CANDIDATO_FRACO`, não em algo
mais forte). Isso não foi ajustado para "caber" o caso real — os limiares
foram escolhidos por critério próprio (30/90 dias, faixas redondas e
comparáveis com o calendário de atualização típico de uma base esportiva) e
o efeito é reportado, não escondido.

---

## 5. Regras por mercado e piso de liquidez (itens 2, 9)

**Piso de liquidez** (`MIN_LIQUID_ODDS = 1.30`): abaixo disso, a
oportunidade é descartada mesmo com edge positivo — uma odd muito próxima
de 1.0 tem pouco valor operacional, porque qualquer erro pequeno de
calibração do modelo já é suficiente para inverter o sinal do edge. Fixado
a priori, não ajustado nos dados.

**Piso mínimo de edge por mercado** (item 9) — testado nesta fase, **não
escolhido como padrão definitivo**:

| Mercado | Piso testado | Motivo |
|---|---|---|
| `aces_player` | `ATINGE_EDGE_3` (3%) | ATP/Grass já é restrito (gate separado); nos demais segmentos a Fase 6.1 não achou ganho extra de calibração — piso intermediário evita reagir a ruído pequeno de odd |
| `total_aces_match` | `ATINGE_EDGE_2` (2%) | os 6 tour/mercado estão "PRONTO PARA ODDS" (docs/012 seção 4), sem nenhuma ressalva de calibração |
| `double_faults_player` | `ATINGE_EDGE_5` (5%) | nunca teve variante Serve×Return modelada (docs/012 seção 7) — só taxa bruta por oportunidade, piso mais alto por cautela |

**Teste de sensibilidade** (item 9 — "testar sem escolher um padrão
definitivo"): `build._sensitivity_report` recompara a classificação
produzida pelo piso por mercado acima contra um piso **uniforme** de 5%
(`ATINGE_EDGE_5` para os 3 mercados), sem decidir qual dos dois é correto.
Resultado real desta execução (`phase10_summary.json`):

| Mercado | Linhas comparadas | Mudaram de classificação |
|---|---:|---:|
| `aces_player` | 3 | 0 |
| `total_aces_match` | 1 | **1** |
| `double_faults_player` | 1 | 0 |

A única linha que muda é `total_aces_match` (edge +2,1 p.p., que atinge o
piso específico de 2% mas fica abaixo do piso uniforme de 5%) — sob o piso
por mercado ela é `CANDIDATO_FRACO`; sob o piso uniforme de 5%, cairia para
`OBSERVAR`. Isso é exatamente o tipo de sensibilidade que a instrução pediu
para expor, não resolver, nesta fase.

---

## 6. Grass (item 7)

A restrição `ATP aces_player em Grass`, herdada literalmente da Fase 7
(`docs/012` seção 5 — `restricted=True`, com o mesmo `restricted_motivo`
textual), continua carregada sem nenhuma alteração — e agora, além de
permanecer visível, é usada como **gate obrigatório** (item 2: "previsão não
estiver restricted"): qualquer previsão restrita cai direto em `DESCARTAR`,
mesmo com edge positivo. `tests/test_decision.py::TestGrassRestrictionPreserved`
confirma isso com uma linha sintética ATP/`aces_player`/Grass. A restrição
nunca foi removida — apenas passou a ter uma consequência operacional
explícita nesta fase.

---

## 7. Probabilidades extremas (item 8)

Probabilidade operacional ≥90% (mesmo limiar da Fase 7) recebe a flag
`extreme_probability`, mas **nunca muda a classificação sozinha** — só
adiciona um alerta textual ("probabilidade extrema (>=90%) -- nao tratada
como qualidade superior automaticamente"). Testado diretamente
(`test_extreme_probability_never_auto_upgrades_or_downgrades`): duas
oportunidades idênticas, uma com `extreme_probability=True` e outra `False`,
produzem exatamente a mesma classificação.

---

## 8. Exemplo real ponta a ponta

Rodando `scripts/evaluate_opportunities.py` contra o lote real de 5
observações registradas na Fase 9 (`data/raw/phase9_manual_example/entradas_ilustrativas.csv`,
odds ilustrativas digitadas manualmente — Betano continua bloqueada, ver
docs/015 seção 1):

| Mercado | Linha/Lado | Odd | Edge | Status (Fase 9) | Amostra | Staleness | Classificação |
|---|---|---:|---:|---|---|---|---|
| `aces_player` | 5.5 over | 3.95 | -0.8 p.p. | `ABAIXO_DO_LIMITE` | HIGH | MUITO_DEFASADO | `OBSERVAR` |
| `aces_player` | 5.5 under | 1.30 | -1.4 p.p. | `ABAIXO_DO_LIMITE` | HIGH | MUITO_DEFASADO | `OBSERVAR` |
| `total_aces_match` | 13.5 over | 6.20 | +2.1 p.p. | `ATINGE_EDGE_2` | HIGH | MUITO_DEFASADO | `CANDIDATO_FRACO` |
| `aces_player` | 4.5 over | 4.50 | N/A (não casado) | `ABAIXO_DO_LIMITE` | LOW | MUITO_DEFASADO | `DESCARTAR` |
| `double_faults_player` | 3.5 under | 1.15 | -4.2 p.p. | `ABAIXO_DO_LIMITE` | HIGH | MUITO_DEFASADO | `DESCARTAR` |

Explicação real gerada para a 3ª linha (`opportunities_evaluated.parquet`,
coluna `explanation`):

```
CANDIDATO_FRACO

Motivos:
- edge = +2.1 p.p.
- amostra = HIGH
- calibração aprovada
- hard court

Alertas:
- Base historica atualizada ate 2026-05-25 -- defasagem de 120 dias em
  relacao a hoje. Edge calculado nao deve ser tratado como alta confianca
  so por ser grande (docs/014).
```

E a 4ª linha (mercado não casado + amostra `LOW`), mostrando múltiplos gates
falhando ao mesmo tempo:

```
DESCARTAR

Motivos:
- linha nao casada com o radar atual: linha 4.5 (over) nao existe na grade
  do modelo para este jogador/mercado -- linhas disponiveis: [5.5, 6.5, ...]
- jogador e/ou adversario nao resolvidos com identidade confiavel (exact/alias)
- probabilidade operacional ausente ou fora do intervalo (0, 1)
- qualidade de amostra = LOW (abaixo do minimo exigido para avancar)
```

E a 5ª linha, mostrando o gate de liquidez isoladamente (edge negativo E odd
abaixo do piso):

```
DESCARTAR

Motivos:
- odd observada (1.15) abaixo do limite minimo configurado (1.3)
```

---

## 9. Testes (item 15)

`tests/test_decision.py`, **33 testes**, cobrindo todos os casos pedidos:

| Teste | Item coberto |
|---|---|
| `TestEdgeInsufficient` (1) | edge insuficiente → `OBSERVAR` |
| `TestEdgeSufficient` (5) | edge suficiente → `CANDIDATO_FRACO`/`CANDIDATO`/`CANDIDATO_FORTE`, monotonicidade |
| `TestLowSample` (1) | amostra baixa → `DESCARTAR` |
| `TestRestrictionActive` (1) | restrição ativa → `DESCARTAR` mesmo com edge positivo |
| `TestGrassRestrictionPreserved` (1) | Grass — restrição herdada da Fase 7 continua bloqueando |
| `TestStalenessHigh` (2) | staleness alta → `CANDIDATO_FORTE` capado; staleness ausente → `DESCARTAR` |
| `TestExtremeProbability` (1) | probabilidade extrema não muda classificação, só alerta |
| `TestLineMissing` (1) | linha ausente (não casada) → `DESCARTAR` |
| `TestMarketNotApproved` (1) | mercado não aprovado → `DESCARTAR` |
| `TestInvalidOdds` (2) | odds inválidas (abaixo do piso, `NaN`) → `DESCARTAR` |
| `TestRepeatedObservation` (1) | repetição exata da mesma observação não duplica o ledger |
| `TestExplanation` (4) | explicação sempre com "Motivos:", nunca termos proibidos, `stake_policy` sempre `NOT_IMPLEMENTED` |
| `TestSampleQuality` (5) | os 3 níveis + dado ausente + inconsistência de features |
| `TestStalenessPolicy` (5) | as 3 faixas + ausência + bloqueio de `CANDIDATO_FORTE` |
| `TestBuildEndToEndWithRealData` (2) | pipeline completo contra Fase 8/9 reais; idempotência |

Suíte cumulativa completa do projeto: **205/205 testes passando** (172 das
Fases 0-9 + 33 novos), sem nenhuma regressão.

---

## 10. Saídas (item 14)

Todas em `data/outputs/phase10/`:

- `opportunities_evaluated.parquet` — ledger append-only (mesma disciplina
  da Fase 9: nunca sobrescreve uma avaliação anterior; dedup só em reenvio
  **exato**, incluindo `collected_at`); cada linha inclui classificação,
  motivos, alertas, texto de explicação completo, e `stake_policy =
  "NOT_IMPLEMENTED"` (item 12).
- `operational_rules.json` — despejo completo de todas as regras/thresholds
  usados (estados, gates, ranks de edge, thresholds de amostra, política de
  staleness, piso de liquidez, piso de edge por mercado) — para
  reprodutibilidade e auditoria.
- `classification_summary.csv` — contagem por `tour`/`market`/classificação
  (visão do estado atual, regenerada a cada execução).
- `rejected_opportunities.csv` — subconjunto `DESCARTAR`, com os motivos
  exatos de cada gate que falhou.
- `phase10_summary.json` — resumo agregado, incluindo o relatório de
  sensibilidade do item 9.

---

## 11. Respostas finais

**1. Quais fatores realmente alteram a classificação?**
Depois que os 8 gates do item 2 passam (o que já elimina mercado não
aprovado, linha não casada, restrição ativa, identidade não confiável,
probabilidade inválida, odd abaixo do piso de liquidez e amostra `LOW`), só
3 sinais movem a classificação entre `OBSERVAR`/`CANDIDATO_FRACO`/
`CANDIDATO`/`CANDIDATO_FORTE`: o edge atingido (relativo ao piso do
mercado), a qualidade de amostra (`MEDIUM` vs. `HIGH`) e a staleness (que só
age como teto para `CANDIDATO_FORTE`). Probabilidade extrema nunca move a
classificação (seção 7) — só adiciona um alerta.

**2. Quais oportunidades são descartadas mesmo com edge positivo?**
Qualquer uma que falhe um gate do item 2, independentemente do edge: uma
previsão restrita (ATP `aces_player`/Grass) com edge de +15 p.p. ainda é
`DESCARTAR` (`TestRestrictionActive`, testado explicitamente com edge
positivo grande); uma odd de 1,15 com edge levemente negativo também é
`DESCARTAR`, mas pelo motivo do piso de liquidez, não do edge em si; e uma
amostra `LOW` (poucas partidas/pontos de saque-devolução) descarta mesmo com
edge tecnicamente calculável. Isso responde diretamente a possibilidade de
"edge positivo mas oportunidade ruim" que a instrução aponta.

**3. Staleness atual limita quais classificações?**
Com a defasagem real de 120 dias (base histórica até 2026-05-25, ver
docs/013/014), toda avaliação cai em `MUITO_DEFASADO` — o que bloqueia
**exclusivamente** `CANDIDATO_FORTE` (nunca visto nesta execução, mesmo
onde o edge e a amostra seriam suficientes). As demais classificações não
são afetadas pela staleness além do alerta textual sempre presente.

**4. Há mercados que exigem edge maior?**
Sim, testado (não escolhido como definitivo, item 9): `double_faults_player`
tem o piso mais alto (5%), `aces_player` intermediário (3%), `total_aces_match`
o mais baixo (2%) — motivos documentados na seção 5. O teste de sensibilidade
mostra que, no lote real desta execução, isso muda a classificação de 1 das
5 linhas avaliadas (a única no piso de `total_aces_match`).

**5. A regra é totalmente reproduzível?**
Sim — `evaluate_opportunity` é uma função pura sobre os campos já
persistidos (nenhuma aleatoriedade, nenhum estado externo além dos
parquets/CSVs de entrada), e a execução completa é idempotente
(`test_idempotent_run_produces_same_ledger_size`: rodar `build.run()` duas
vezes produz o mesmo tamanho de ledger, porque o dedup usa a mesma chave
completa — incluindo `collected_at` — já usada na Fase 9). Todos os
thresholds estão em `config.py`, versionados em código, e despejados em
`operational_rules.json` a cada execução para auditoria.

**6. O sistema está pronto para Forward Test?**
Parcialmente, pelo mesmo motivo já registrado na Fase 9 (docs/015 pergunta
7): o mecanismo de classificação está pronto e testado ponta a ponta contra
dados reais da Fase 8/9, mas depende de odds observadas manualmente
(Betano continua bloqueada para coleta automática). O que é genuinamente
novo aqui — e já funcional — é que, uma vez que uma odd é registrada
(`scripts/record_odds.py`, Fase 9), ela já sai classificada em um dos 5
estados operacionais, com motivos e alertas explícitos, pronta para
`data/outputs/phase10/opportunities_evaluated.parquet` acumular um histórico
imutável linha a linha (item 13) — a base exata que a Fase 11 (forward
test) precisaria para comparar classificação prévia contra resultado real.

---

**Parando aqui conforme instrução. Não foi calculado stake, não houve
aposta, nenhuma interface foi criada, não se avançou para a Fase 11.
Aguardando nova instrução.**
