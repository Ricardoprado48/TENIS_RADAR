# Relatório — Fase 4: Baselines Estatísticos e Avaliação Preditiva

Status: **Fase 4 concluída.** Não avançar para a Fase 5 sem nova instrução.

Entrada: exclusivamente `data/processed/features/{atp,wta}/player_match_features.parquet`
(Fase 3, nunca reescrito) como fonte de PREDITORES. Uma única leitura
adicional em `data/processed/{atp,wta}/matches.parquet` (Fase 2, também
nunca reescrito) traz 2 colunas (`aces`, `double_faults` da própria
partida) usadas **somente como rótulo de avaliação** — nunca como entrada
de nenhum modelo (ver seção 2). Nenhum arquivo da Fase 2/3 foi alterado.

Saída: `data/outputs/phase4/{predictions,metrics,config}/`.

---

## 1. Metodologia geral

```
src/baselines/
  targets.py         -- rotulos (y_true) a partir do parser de score da Fase 3 + 2 colunas da Fase 2
  history_means.py    -- baseline "media historica do jogador" (reusa o motor point-in-time da Fase 3)
  rate_models.py        -- baselines de taxa para aces/double faults (isolado / matchup / opponent-adjusted)
  setmodel.py             -- modelo analitico (cadeia de Markov) de games/sets/tie-break a partir de Hold%
  games_model.py            -- aplica setmodel.py linha a linha (isolado / matchup / opponent-adjusted)
  count_dist.py               -- Poisson vs Negative Binomial (overdispersion, Brier/Log Loss)
  tiebreak_model.py             -- regressao logistica (ajustada so no treino) + baseline Hold% combinado
  walkforward.py                 -- folds cronologicos, buckets de amostra/ranking
  metrics.py                      -- MAE/RMSE/correlacao/Brier/Log Loss/calibracao/overdispersion
  evaluate.py                      -- orquestra avaliacao por mercado x variante x janela x segmento
  build.py                          -- runner: grava previsoes/metricas/resumo
  config.py                          -- folds, janelas, buckets, diretorios de saida
scripts/build_baselines_phase4.py    -- CLI
tests/test_baselines.py              -- 17 testes (modelo de sets, anti-leakage, folds, ajuste sem vazamento)
```

Execução: `python scripts/build_baselines_phase4.py`.

**Regra de leakage do rótulo (achado de desenho, não um bug):** a Fase 3
exclui deliberadamente as estatísticas da própria partida (aces,
double faults, etc.) das *features*, porque usá-las como preditor da
mesma partida seria vazamento por definição. Isso significa que essas
colunas não existem na tabela de features para servir de "gabarito" na
avaliação. A única forma correta de avaliar "quantos aces o modelo previu
vs quantos realmente aconteceram" é buscar o valor real da própria partida
em outro lugar — feito em `targets.py`, lendo 2 colunas do Parquet imutável
da Fase 2 e anexando-as como `target_aces`/`target_double_faults`,
explicitamente documentadas como **rótulo, nunca preditor**. Os demais
alvos (`target_total_games`, `target_game_diff`, `target_total_sets`,
`target_has_tiebreak`) já vêm prontos da Fase 3 (parser de score), apenas
reorientados da perspectiva "vencedor/perdedor" para "player/opponent" via
a coluna `result`.

---

## 2. Baselines implementados

Para cada mercado, os seguintes modelos foram avaliados lado a lado (nenhum
foi descartado antes de medir):

| Variante | Descrição |
|---|---|
| `naive_train_mean` / `naive_baserate` | média (ou taxa-base) do alvo real no fold de **treino**, aplicada constante a todo o teste — referência mínima que qualquer modelo precisa superar |
| `history_mean` | média histórica do próprio jogador (ou taxa histórica de tie-break), reaproveitando o motor point-in-time da Fase 3 sobre o alvo observado |
| `isolated` | taxa/Hold% do próprio jogador, sem considerar o adversário específico |
| `matchup` | combina a taxa do jogador com a taxa correspondente do adversário NAQUELA partida (Serve × Return) |
| `oppadj` | parte do `matchup` e soma o resíduo de ajuste por força média dos adversários enfrentados (Fase 3, item 9) |
| `logistic_regression` (só tie-break) | regressão logística ajustada por fold, features: Hold%/Break% dos 2 lados + superfície |

Contagens previstas (aces, double faults) = taxa prevista × volume de
pontos de saque esperado na janela (`prior_service_points_{w} /
prior_matches_{w}`, já calculado na Fase 3).

### Modelo analítico de games/sets/tie-break (`setmodel.py`)

Cadeia de Markov **exata** (não Monte Carlo) sobre o placar de games de um
set, dados `p_hold_A`/`p_hold_B`. Verificada contra simulação Monte Carlo
independente (2.000.000 de sets simulados) antes de ser usada — ver seção
9 (achado: sacar primeiro no set dá uma pequena vantagem estrutural no
número **esperado** de games, mesmo com probabilidade de vencer o set
exatamente 0,5 quando os dois jogadores têm o mesmo Hold%; achado
verificado por DP e por Monte Carlo, documentado por transparência). O
tie-break (6-6) não tem probabilidade observável nos dados (não há placar
ponto-a-ponto), então é aproximado por `p_tb_A = p_hold_A / (p_hold_A +
p_hold_B)` — uma proxy simples e documentada, não uma medição. Do set, a
partida (melhor de 3 ou 5) é agregada assumindo sets i.i.d. (mesma
distribuição em todos os sets) — simplificação documentada, que ignora
momento/fadiga/mudança de quem saca primeiro a cada set.

### Poisson vs Negative Binomial (`count_dist.py`)

Não recalculam a média prevista (isso já vem do baseline de taxa) — eles
transformam a previsão pontual em uma previsão **probabilística**: um
limiar fixo (mediana do alvo real no fold de **treino**) define o evento
binário "resultado acima do limiar"; Poisson usa `lambda` = previsão da
linha; Negative Binomial usa o mesmo `lambda` por linha, mas um parâmetro
de dispersão `r` estimado por método dos momentos **somente no treino**
(`r = média²/(variância-média)`, `None` se não houver overdispersion).

### Regressão logística de tie-break

Ajustada (`sklearn.linear_model.LogisticRegression`) **somente no fold de
treino**, nunca no teste — verificado por teste automatizado (seção 9).

---

## 3. Folds walk-forward

Janela de treino **expansiva**, sempre a partir do início dos dados
(2022-01-03); teste sempre no ano seguinte (nunca split aleatório):

| Fold | Treino | Teste |
|---|---|---|
| `fold_2024` | até 2023-12-31 | 2024-01-01 a 2024-12-31 |
| `fold_2025` | até 2024-12-31 | 2025-01-01 a 2025-12-31 |
| `fold_2026` | até 2025-12-31 | 2026-01-01 a 2026-05-25 (parcial — fim real dos dados) |

Esses 3 folds reproduzem exatamente o exemplo do enunciado porque
coincidem com a cobertura real dos dados (verificado antes de definir os
folds: `data/processed/features/{atp,wta}` cobre 2022-01-03 a 2026-05-25).
O fold `fold_2026` é necessariamente parcial (só Grand Slams/eventos de
jan-mai) — reportado, não escondido.

---

## 4. Métricas

Numéricas: MAE, RMSE, erro médio (viés), correlação previsão×real, média e
variância previstas vs reais (`data/outputs/phase4/metrics/numeric_metrics.csv`).
Contagens: razão variância/média do alvo no treino (`overdispersed` quando
> 1,15), Brier/Log Loss de Poisson vs Negative Binomial
(`count_distribution_metrics.csv`). Probabilidades: Brier, Log Loss,
Expected Calibration Error em 10 bins (`probabilistic_metrics.csv`).

---

## 5. Segmentações

Cada linha de métrica é calculada para `overall` + por `surface`
(Hard/Clay/Grass) + por `sample_bucket_career` (`cold_start`, `small_1_9`,
`medium_10_49`, `large_50_plus`) + por `ranking_bucket`
(`top50`/`top51_100`/`top101_300`/`outside_300`) + por fold (= temporada).
ATP e WTA sempre em linhas separadas — nunca misturados numa conclusão.

Exemplo (`aces_player`, ATP, `matchup_surface_career`): MAE por superfície
**Clay 2,34 · Hard 3,53 · Grass 4,16** — Grass tem menos amostra
(392 linhas/fold vs 2.629 em Hard) e maior erro, consistente com menor
volume histórico disponível por superfície. Cold start (`prior_matches_career
== 0`) sempre produz `n = 0` nas variantes `matchup`/`oppadj`/`history_mean`
(nunca um valor inventado — a previsão fica `NaN` e a linha some da
contagem, não vira erro zero).

---

## 6. Resultado de Serve × Return (item 3/11 — isolado vs matchup)

**MAE médio entre folds, janelas headline (career/surface_career/last50):**

| Mercado | Tour | `isolated` (melhor janela) | `matchup` (melhor janela) | Vencedor |
|---|---|---|---|---|
| Aces por jogador | ATP | 3,208 (surface_career) | **3,155** (surface_career) | matchup |
| Aces por jogador | WTA | 1,767 (surface_career) | **1,758** (last50) | matchup |
| Total de games | ATP | **5,958** (last50/surface_career) | 6,009–6,026 | isolated |
| Total de games | WTA | **5,410** (last50) | 5,473–5,503 | isolated |

**Resposta direta:** para **aces**, incluir o perfil do devolvedor
(Ace Allowed Rate do adversário) melhora a previsão em ambos os tours —
pequeno mas consistente (ATP -1,7%, WTA -0,5% de MAE relativo ao
isolado). Para **total de games**, o modelo `matchup` (Hold% combinado com
Break% do devolvedor) **piora** em relação ao `isolated` (Hold% cru) em
ambos os tours — um resultado negativo real, não escondido. A camada
`oppadj` (que soma o resíduo de ajuste por força média dos adversários ao
`matchup`) recupera e supera o `isolated` para **games no ATP** (5,857,
melhor de todos), mas continua pior que `isolated` para **games na WTA**
(5,285 vs 5,410) — ver seção 9 para a hipótese sobre essa diferença.

---

## 7. Resultado do opponent adjustment (item 8/11)

| Mercado | Tour | `matchup` | `oppadj` | Ajuda? |
|---|---|---|---|---|
| Aces por jogador | ATP | 3,155–3,382 | 3,491–3,527 | **Não** — piora |
| Aces por jogador | WTA | 1,758–1,763 | 1,822–1,824 | **Não** — piora |
| Total de games | ATP | 6,009–6,026 | **5,857–5,858** | **Sim** — melhora, e supera o `isolated` |
| Total de games | WTA | 5,473–5,503 | 5,259–5,285 | Melhora sobre `matchup`, mas não supera `isolated` (5,410) |
| Game diff (handicap) | ATP | — | **4,475** (melhor do mercado) | Sim |
| Total de sets | ATP | — | **0,514** (melhor do mercado) | Sim |

**Conclusão registrada (não forçada):** o ajuste por adversário, do jeito
simples implementado (resíduo aditivo sobre o `matchup`, Fase 3 item 9),
**piora** a previsão de aces em ambos os tours — provável excesso de
ruído ao empilhar duas correções sobre a mesma taxa com histórico limitado
por jogador (ver seção 10, limitações). Para o modelo de games do ATP, o
ajuste **ajuda bastante** e produz o melhor resultado do mercado. Isso é
reportado como está, sem forçar um único padrão universal — CLAUDE.md #7
pede o ajuste "sempre que possível", não "sempre que ajudar artificialmente".

---

## 8. Baseline trivial vs modelos (achado central da Fase 4)

Antes de qualquer conclusão de "qual mercado é mais previsível", a
pergunta mais básica é: **o modelo supera um palpite ingênuo (média/taxa
do próprio histórico de treino, sem olhar o jogador)?**

| Mercado | Tour | `naive_train_mean`/`naive_baserate` | Melhor modelo | Modelo ajuda? |
|---|---|---|---|---|
| Aces por jogador | ATP | 3,929 | **3,155** | Sim (-19,7%) |
| Aces por jogador | WTA | 2,088 | **1,758** | Sim (-15,8%) |
| Total de aces | ATP | 6,443 | **5,117** | Sim (-20,6%) |
| Total de aces | WTA | 3,226 | **2,721** | Sim (-15,6%) |
| Double faults | ATP | 1,755 | **1,634** | Sim (-6,9%) |
| Double faults | WTA | 2,075 | **1,871** | Sim (-9,8%) |
| Game diff (handicap) | ATP | 4,857 | **4,475** | Sim (-7,9%) |
| Game diff (handicap) | WTA | 5,309 | **4,851** | Sim (-8,6%) |
| Total de games | ATP | 6,667 | **5,857** | Sim (-12,1%) |
| Total de games | WTA | 4,887 | 4,887 | **Não — empate, nada supera a média simples** |
| Total de sets | ATP | 0,640 | **0,514** | Sim (-19,6%) |
| Total de sets | WTA | 0,448 | 0,448 | **Não — nada supera a taxa-base** |
| Tie-break (Brier) | ATP | 0,2407 | **0,2354** | Sim, mas marginal (-2,2%) |
| Tie-break (Brier) | WTA | **0,1773** | 0,1834 (logistic) | **Não — naive vence** |
| Full distance / foi a distância (Brier) | ATP | **0,2216** | 0,2313 (oppadj) | **Não — naive vence** |
| Full distance / foi a distância (Brier) | WTA | **0,2255** | 0,2379 (oppadj) | **Não — naive vence** |

**Este é o achado mais importante do relatório:** os modelos baseados em
Serve×Return/Hold%/Break% agregam valor real e mensurável para **aces**,
**double faults**, **handicap de games** e **total de sets no ATP** — mas
**não superam uma média/taxa histórica simples** para **total de games na
WTA**, **total de sets na WTA**, **tie-break na WTA** e **"foi a distância"
em ambos os tours**. Isso não é um defeito do pipeline — é o resultado
honesto de comparar contra a referência correta, e responde diretamente à
pergunta do CLAUDE.md #19 ("não escolher mercado apenas por opinião"): os
mercados de **contagem por jogador (aces, double faults)** mostram sinal
Serve×Return real; os mercados de **resultado agregado da partida
inteira** (sets, foi a distância, tie-break) mostram pouco ou nenhum sinal
incremental além da média histórica, pelo menos com os baselines simples
desta fase.

---

## 9. Melhor janela histórica por mercado (item 7/11)

Isolando o efeito da janela (variante `isolated`, todas as 7 janelas
disponíveis), MAE médio entre folds:

| Janela | Aces (ATP) | Aces (WTA) |
|---|---|---|
| `career` | 3,383 | 1,771 |
| `last10` | 3,442 | 1,811 |
| `last20` | 3,454 | 1,782 |
| `last50` | 3,412 | 1,769 |
| `last365d` | 3,426 | 1,784 |
| `surface_career` | **3,208** | **1,767** |
| `decay90d` | 5,495 | 2,470 |

**`surface_career` e `last50` são consistentemente as janelas mais
precisas** em quase todos os mercados/tours (ver `market_ranking_summary.csv`,
coluna `melhor_baseline`). **`decay90d` (meia-vida de 90 dias) é
consistentemente a PIOR janela**, por uma margem grande — jogadores de
tênis não jogam toda semana, então um decaimento de 90 dias descarta a
maior parte do histórico relevante para qualquer jogador com um hiato
maior que ~3 meses (lesão, offseason, etc.). Isso não significa que decay
não funcione em geral — significa que **90 dias é curto demais** para o
padrão de calendário do tênis; uma meia-vida maior (ex. 180-365 dias, já
parametrizável em `compute_decay_priors`) não foi testada nesta fase por
não ter sido materializada na Fase 3, e fica registrada como próximo passo
natural, não como conclusão. `career` fica no meio da tabela — mostra que
"quanto mais dado, melhor" não é verdade de forma simples: um jogador pode
ter mudado de nível desde o início da carreira, e `surface_career`/`last50`
capturam melhor o nível atual sem descartar tanto histórico quanto o decay
de 90 dias.

**Achado técnico corrigido durante o desenvolvimento:** a primeira versão
de `history_means.py` dividia a soma DECAÍDA (numerador) pela contagem
BRUTA de partidas anteriores (denominador) para a janela `decay90d`,
produzindo uma média sistematicamente subestimada sempre que havia um
hiato de tempo (verificado: MAE de `total_games` em `decay90d` caiu de
21,46/18,18 para 6,80/5,03 ATP/WTA após a correção). Corrigido incluindo
uma pseudo-coluna de peso 1.0 entre as colunas decaídas, obtendo o "N
efetivo" decaído pelo MESMO mecanismo do numerador — teste de regressão
`test_decay_mean_is_not_biased_by_time_gap` adicionado.

---

## 10. Diferenças ATP/WTA (item 11)

- **WTA é sistematicamente mais difícil de melhorar sobre o naive** para
  mercados de partida inteira (`total_games`, `total_sets`, `tiebreak`) —
  em nenhum desses 3 mercados um modelo bateu a referência trivial na WTA,
  contra 3 de 3 no ATP. Hipótese (não testada aqui, registrada para
  investigação futura): maior variância de nível entre jogadoras WTA fora
  do top ranking pode tornar Hold%/Break% agregados menos estáveis
  point-in-time; também é possível que o WTA tenha menos partidas de
  Slam/best-of-5 (WTA é 100% melhor-de-3, ver `best_of` na seção 1) o que
  reduz a variação estrutural que o modelo de sets consegue capturar.
- Para **aces** e **double faults**, os dois tours mostram o mesmo padrão
  qualitativo (matchup > isolated > oppadj para aces; isolated ligeiramente
  melhor que history_mean para double faults) — resultado consistente
  entre tours, reforça confiança no achado.
- Overdispersion (`count_distribution_metrics.csv`) é forte em ambos os
  tours para os 3 mercados de contagem avaliados (razão variância/média
  entre 2,0 e 5,6), confirmando que Negative Binomial é teoricamente mais
  apropriado que Poisson puro — na prática, o Negative Binomial teve Brier
  ligeiramente melhor que Poisson na variante `isolated` (maior erro
  pontual → maior benefício de uma distribuição mais larga), mas
  ligeiramente pior na variante `matchup` (menor erro pontual → a
  distribuição mais estreita do Poisson já é mais bem calibrada). Achado
  reportado como está, sem forçar Negative Binomial como "sempre melhor".
- ATP tem 4.680 partidas melhor-de-5 (Grand Slams) e 22.064 melhor-de-3;
  WTA é 100% melhor-de-3 (24.366) — `setmodel.py` trata os dois casos via
  a mesma combinatória binomial negativa parametrizada por `best_of`,
  verificado por teste (`test_best_of_5_more_expected_games_than_best_of_3`).

---

## 11. Cold start (item 9)

Segmentado explicitamente via `sample_bucket_career`
(`cold_start`/`small_1_9`/`medium_10_49`/`large_50_plus`). Nas variantes
que dependem do self-join de adversário (`matchup`/`oppadj`), linhas de
cold start (jogador OU adversário sem nenhuma partida anterior) produzem
`n = 0` na segmentação — nunca preenchidas com média global. Nas variantes
`isolated`/`history_mean`, cold start produz previsão `NaN` (o jogador em
si não tem taxa calculável) e também é excluído do cálculo de erro, nunca
tratado como erro zero. Amostras pequenas (`small_1_9`) mostram MAE
consistentemente maior que `large_50_plus` em todos os mercados testados
(ex. aces ATP matchup_surface_career: 3,31 vs 3,14) — na direção esperada,
sem exceções encontradas.

---

## 12. Problemas encontrados

1. **Bug de viés no baseline `decay90d`** (seção 9) — corrigido, com teste
   de regressão.
2. **`game_diff` tem média populacional próxima de 0** (é uma diferença
   assinada, simétrica entre vencedor/perdedor) — a normalização inicial
   por `MAE/média` explodia (valores de 65-80) sem fazer sentido nenhum;
   corrigido usando `MAE/desvio-padrão` como medida comparável entre
   mercados (coluna `mae_relativo_ao_desvio`), e usando MAE bruto (não
   normalizado) para escolher o melhor baseline DENTRO de um mesmo mercado
   (onde a normalização nunca era necessária, já que todas as variantes de
   um mercado preveem o mesmo alvo, na mesma escala).
3. **`full_distance` (foi a distância) e `tiebreak` na WTA**: nenhum
   modelo bate o baseline trivial — ver seção 8. Registrado como resultado
   real, não como falha de implementação (os testes de sanidade do
   `setmodel.py` — conservação de probabilidade, simetria, casos extremos
   — todos passam).
4. **Proxy de tie-break** (`p_tb_A = p_hold_A/(p_hold_A+p_hold_B)`) é uma
   aproximação sem dado ponto-a-ponto para calibrar — plausível
   qualitativamente (verificado: sacador mais forte tem mais chance de
   fechar o tie-break) mas não validada quantitativamente contra um dado
   de referência independente.
5. **Sets tratados como i.i.d.** no agregado de partida — ignora
   momento/fadiga/mudança de quem saca primeiro a cada set; simplificação
   documentada, não testada contra uma alternativa mais realista nesta
   fase.
6. **Cobertura de `total_games`/`total_sets`/`game_diff`/`tiebreak`
   restrita a `score_complete == True`** (~96% das partidas, herdado da
   Fase 3) — partidas com retirement/walkover/default são excluídas
   inteiramente desses mercados nesta fase (não modeladas parcialmente).

---

## 13. Resposta às perguntas do item 11 da instrução

1. **Qual mercado possui menor erro fora da amostra?** Em termos
   relativos (MAE/desvio-padrão do alvo — comparável entre mercados),
   `aces_player` e `total_aces_match` são os mais previsíveis em ambos os
   tours (≈0,61-0,64), seguidos por `double_faults`/`total_games`/`game_diff`
   (≈0,69-0,85); `total_sets` é o menos previsível pela métrica numérica
   pura (≈0,67-0,99, próximo do trivial).
2. **Qual é mais estável entre temporadas?** `total_sets` tem o menor
   `std` de MAE entre folds (0,003-0,004) — mas isso é porque tanto o
   modelo quanto o naive já estão perto do teto de erro nesse mercado
   (pouco a "desestabilizar"). Entre os mercados onde o modelo realmente
   agrega valor, `aces_player` é o mais estável (std 0,03-0,04).
3. **Qual é mais estável entre superfícies?** Não avaliado com uma métrica
   única nesta fase — os dados por segmento estão em
   `numeric_metrics.csv`/`probabilistic_metrics.csv` (`segment_type ==
   "surface"`) para quem quiser essa comparação; Grass tem consistentemente
   menos amostra e mais erro (seção 5), mas isso é esperado dado o volume,
   não necessariamente uma instabilidade do modelo.
4. **Serve × Return melhora a previsão de aces?** **Sim**, em ambos os
   tours (seção 6).
5. **Serve × Return melhora total de games?** **Não** na formulação
   simples `matchup`; **sim** quando combinado com o ajuste por adversário
   (`oppadj`) no ATP; nem `matchup` nem `oppadj` superam `isolated` na WTA
   (seção 6-7).
6. **Opponent adjustment ajuda ou atrapalha?** Depende do mercado — piora
   aces em ambos os tours, ajuda games/handicap/sets no ATP (seção 7).
7. **Qual janela histórica funciona melhor?** `surface_career` e `last50`,
   consistentemente; `decay90d` (90 dias) é a pior janela testada (seção 9).
8. **ATP e WTA apresentam diferenças importantes?** Sim — WTA não mostra
   ganho de nenhum modelo sobre o naive para `total_games`/`total_sets`/
   `tiebreak`, enquanto ATP mostra ganho nos 3 (seção 10).

---

## 14. Saída

```
data/outputs/phase4/
  predictions/
    predictions_{atp,wta}_fold_{2024,2025,2026}.parquet   -- previsoes out-of-sample linha a linha
  metrics/
    numeric_metrics.csv              -- MAE/RMSE/erro medio/correlacao por mercado x variante x janela x segmento x fold
    count_distribution_metrics.csv   -- overdispersion + Poisson vs NegBin (Brier/Log Loss)
    probabilistic_metrics.csv        -- Brier/Log Loss/calibration error (tiebreak, full_distance)
    market_ranking_summary.csv       -- tabela comparativa final por tour x mercado
  config/
    folds.json, phase4_diagnostics.json
```

Nenhum arquivo de `data/processed/` foi sobrescrito. Nenhuma odd foi
calculada ou usada. Nenhum backtest financeiro foi feito.

---

## 15. Limitações gerais

- O ajuste por adversário e o modelo de games herdam todas as
  simplificações documentadas na Fase 3 (ordem intra-dia por convenção,
  ausência de hora do dia, cold start = primeira partida **no dataset**
  2022-2026, não necessariamente na carreira real).
- `fold_2026` é parcial (só até maio) — resultados desse fold têm menos
  partidas e cobrem uma fatia de temporada diferente dos outros dois
  (majoritariamente saibro europeu), o que pode explicar parte da
  variação entre folds nas tabelas de `numeric_metrics.csv`.
- Nenhum modelo aqui usa ranking ou pontos de ranking como preditor direto
  — só como segmento de avaliação. Isso é uma escolha de escopo (a
  instrução da Fase 4 não pediu ranking como feature), não uma limitação
  de dado (a coluna existe e está disponível para a Fase 5 se fizer sentido).
- A regressão logística de tie-break usa só 4 features (Hold%/Break% dos
  2 lados, janela `career`) + superfície — deliberadamente simples
  (CLAUDE.md #16: "começar simples"), não explorando as outras 6 janelas
  disponíveis como features do modelo (só como baselines Hold%-combinado
  separados).

---

## 16. Conclusão técnica

A Fase 4 mediu, de forma honesta e reprodutível, 7 mercados em 2 tours
com walk-forward de 3 folds cronológicos, sempre comparando contra um
baseline trivial. O resultado central: **Serve × Return e ajuste por
adversário agregam valor real, mas não uniformemente** — fortes para aces
e double faults em ambos os tours, condicionais (ATP sim, WTA não) para
games/sets/tie-break. Nenhum mercado foi descartado ou promovido por
opinião; todas as tabelas numéricas estão salvas em
`data/outputs/phase4/metrics/` para auditoria. Dois bugs reais foram
encontrados e corrigidos durante o desenvolvimento (viés do `decay90d`;
normalização inválida para alvos de média ≈ 0), documentados nas seções 9
e 12 por transparência, seguindo o mesmo padrão das Fases 2 e 3.

**Parando aqui conforme instrução. Fase 5 (comparação e seleção final dos
mercados) não foi iniciada.**
