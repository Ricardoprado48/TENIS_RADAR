# 009 — Fase 5: Comparação de Robustez e Seleção Técnica dos Mercados

## 0. Escopo e princípio de execução

Esta fase **não treina, não ajusta e não recalcula nenhum modelo**. Toda a
análise abaixo é uma agregação estatística feita exclusivamente sobre os
arquivos já produzidos pela Fase 4 em `data/outputs/phase4/metrics/`:

- `numeric_metrics.csv` (6.912 linhas — MAE/RMSE por tour × fold × mercado ×
  variante × janela × segmento);
- `probabilistic_metrics.csv` (1.872 linhas — Brier/Log Loss/calibração);
- `count_distribution_metrics.csv` (330 linhas — Poisson vs Negative
  Binomial).

Nenhum arquivo de `data/processed/` ou `data/raw/` foi lido nesta fase.
Código novo (`src/selection/`, `scripts/build_market_selection_phase5.py`) só
lê, filtra, compara e classifica números que já existiam — não há nenhum
`.fit()`, `.predict()` ou geração de previsão nova aqui.

Não foram calculadas odds, não foram coletadas odds reais, não foi feito
nenhum backtest financeiro, nenhuma interface foi criada e nenhum modelo foi
alterado.

## 1. Regra obrigatória usada em toda a fase

> Um modelo só pode ser considerado candidato se superar o baseline trivial
> fora da amostra de forma consistente. Não considerar suficiente uma
> melhora média pequena que dependa de apenas um fold.

Operacionalização (fixada em `src/selection/config.py` **antes** de olhar o
resultado final da classificação):

- **"Superar o baseline"** em um fold = MAE (ou Brier) da variante
  estritamente menor que o do baseline `naive_train_mean` /
  `naive_baserate` (média/taxa do próprio fold de treino, aplicada
  constante ao fold de teste) **no mesmo fold**.
- **"Vitória forte"** num fold = vitória com melhora relativa ≥ 1% (evita
  contar como vitória uma diferença de arredondamento).
- **Melhora real** = melhora relativa média entre folds ≥ 3%.
- **Cobertura mínima** = n ≥ 300 no segmento `overall` em todos os folds
  usados (todos os mercados desta fase têm, no mínimo, n≈2.200 no fold mais
  curto — 2026 parcial — e n≈5.000–6.000 nos demais; cobertura nunca foi o
  fator limitante).
- **Deterioração de superfície sinalizada** = superfície com n ≥ 150 onde o
  modelo é ≥ 10% pior que o baseline trivial naquela superfície.

## 2. Comparação por mercado — robustez temporal (item 3)

Tabela com o número de folds vencidos e a melhora relativa fold a fold, para
a **melhor abordagem** de cada mercado (critério: mais folds vencidos →
maior melhora relativa média → menor variação entre folds). Fonte:
`data/outputs/phase5/robustez_temporal.csv`.

### ATP

| Mercado | Melhor abordagem | 2024 | 2025 | 2026* | Folds vencidos |
|---|---|---|---|---|---|
| aces_player | matchup_surface_career | +19,6% | +17,8% | +21,7% | 3/3 |
| total_aces_match | matchup_surface_career | +20,5% | +17,8% | +23,3% | 3/3 |
| double_faults_player | isolated_last50 | +7,3% | +5,1% | +8,5% | 3/3 |
| total_games | oppadj_last50 | +12,9% | +13,0% | +10,6% | 3/3 |
| game_diff | oppadj_last50 | +7,3% | +8,4% | +8,0% | 3/3 |
| total_sets | oppadj_last50 | +20,4% | +19,7% | +18,8% | 3/3 |
| tiebreak (Brier) | logistic_regression_career | +2,1% | +3,1% | +1,4% | 3/3 |
| full_distance (Brier) | oppadj_last50 | −4,2% | −3,3% | −5,7% | 0/3 |

### WTA

| Mercado | Melhor abordagem | 2024 | 2025 | 2026* | Folds vencidos |
|---|---|---|---|---|---|
| aces_player | matchup_last50 | +16,5% | +15,5% | +15,4% | 3/3 |
| total_aces_match | matchup_last50 | +17,1% | +14,7% | +15,1% | 3/3 |
| double_faults_player | isolated_last50 | +9,8% | +9,0% | +10,7% | 3/3 |
| game_diff | isolated_last50 | +8,6% | +7,6% | +9,6% | 3/3 |
| total_games | history_mean_career | −0,8% | −0,5% | +0,8% | 1/3 |
| total_sets | oppadj_last50 | −5,1% | −4,8% | −5,0% | 0/3 |
| tiebreak (Brier) | logistic_regression_career | −0,8% | −0,9% | −0,2% | 0/3 |
| full_distance (Brier) | oppadj_last50 | −5,0% | −6,9% | −4,6% | 0/3 |

\* fold 2026 é parcial (dados até 2026-05-25).

**Leitura direta**: nos dois tours, aces (por jogador e total), double
faults e game_diff vencem o baseline trivial em todos os folds com melhora
relativa estável (a diferença entre o melhor e o pior fold nunca passa de
~5 pontos percentuais). Em contraste, total_games/total_sets/tiebreak/
full_distance da WTA e full_distance do ATP **nunca** vencem o baseline —
não é uma melhora pequena, é ausência de melhora, e consistente ao longo de
3 folds (não é um fold ruim isolado).

## 3. Robustez por superfície (item 4)

Fonte: `data/outputs/phase5/robustez_superficie.csv`. Amostra por superfície
(soma dos 3 folds): Hard ≈ 7.700–8.200, Clay ≈ 3.500–4.700, Grass ≈
1.150–1.230 — Grass tem ~15% da amostra de Hard, então não se exige a mesma
precisão lá, mas deteriorações grandes com n≥150 são sinalizadas.

| Mercado (tour) | Hard | Clay | Grass | Sinalizado? |
|---|---|---|---|---|
| aces_player (ATP, matchup_surface_career) | +12,9% | +33,4% | +16,7% | não |
| aces_player (WTA, matchup_last50) | +14,9% | +19,4% | +13,2% | não |
| total_aces_match (ATP) | +10,8% | +38,6% | +18,1% | não |
| total_aces_match (WTA) | +13,9% | +21,7% | +11,6% | não |
| double_faults_player (ATP) | +6,1% | +7,8% | +8,5% | não |
| double_faults_player (WTA) | +10,4% | +8,8% | +8,8% | não |
| total_games (ATP, oppadj_last50) | +10,8% | +11,4% | +14,8% | não |
| total_sets (ATP, oppadj_last50) | +18,8% | +18,1% | +30,7% | não |
| **game_diff (ATP, oppadj_last50)** | +9,1% | +6,0% | **−46,9%** | **sim** |
| game_diff (WTA, isolated_last50) | +8,6% | +8,5% | +7,2% | não |

**Achado relevante**: `game_diff` no ATP vence o baseline em Grass quando
olhado como taxa média (a tabela do item 2 mostra +7–8% por fold), mas isso
é a média entre `total_games`/derivação, não a métrica direta de handicap —
ao medir diretamente `game_diff` por superfície, a variante vencedora
(`oppadj_last50`) é **47% pior** que o baseline trivial em Grass (n=1.192,
amostra suficiente para confiar no sinal). Esse é o único caso, em todo o
levantamento, de deterioração de superfície com amostra adequada. Por isso
`game_diff` do ATP foi classificado como **EXPERIMENTAL**, não CANDIDATO,
mesmo vencendo em 3/3 folds no agregado — a regra do item 4 ("não exigir a
mesma precisão, mas sinalizar deteriorações relevantes") foi aplicada
literalmente aqui.

## 4. Serve × Return — aces (item 5)

Fonte: `data/outputs/phase5/serve_return_analysis.csv`, janela `career` e
`last50` (únicas onde naive, isolated, matchup e oppadj coexistem).

### Quanto o devolvedor acrescenta (isolated → matchup, janela `career`, segmento overall)

| Tour | Fold | isolated (MAE) | matchup (MAE) | matchup melhor? |
|---|---|---|---|---|
| ATP | 2024 | 3,290 | 3,286 | sim |
| ATP | 2025 | 3,358 | 3,310 | sim |
| ATP | 2026 | 3,502 | 3,429 | sim |
| WTA | 2024 | 1,714 | 1,729 | não (marginal) |
| WTA | 2025 | 1,812 | 1,792 | sim |
| WTA | 2026 | 1,788 | 1,776 | sim |

No ATP, `matchup` bate `isolated` em 3/3 folds na janela `career` (margem
pequena, ~0,05–0,07 aces de MAE). Na WTA, o efeito é positivo em 2/3 folds
na janela `career`, mas se torna consistente (3/3, e maior) na janela
`last50` — ver item 6.

### Por superfície (janela `last50`, média dos 3 folds)

| Tour | Superfície | isolated | matchup | matchup melhor? |
|---|---|---|---|---|
| ATP | Hard | 3,583 | 3,537 | sim |
| ATP | Clay | 2,920 | 2,895 | sim |
| ATP | Grass | 4,347 | 4,441 | **não** |
| WTA | Hard | 1,842 | 1,842 | empate |
| WTA | Clay | 1,561 | 1,523 | sim |
| WTA | Grass | 1,933 | 1,940 | **não** |

**Resposta objetiva**: o perfil do devolvedor melhora a previsão de aces de
forma consistente em Hard e Clay, nos dois tours, e na maioria dos folds em
`career`/`last50`. A única exceção sistemática é **Grass**, nos dois tours —
lá `isolated` é ligeiramente melhor que `matchup` (diferença pequena, ~0,01–
0,09 aces, amostra menor ~1.200). Isso é reportado como observação, não
como reversão da conclusão geral: em amostra e cobertura agregadas, o
devolvedor ajuda.

### Opponent adjustment além do matchup simples

| Tour | Superfície | matchup | oppadj | oppadj melhor? |
|---|---|---|---|---|
| ATP | Hard | 3,537 | 3,672 | não |
| ATP | Clay | 2,895 | 3,123 | não |
| ATP | Grass | 4,441 | **4,246** | **sim (único caso)** |
| WTA | Hard | 1,842 | 1,884 | não |
| WTA | Clay | 1,523 | 1,660 | não |
| WTA | Grass | 1,940 | 1,936 | quase empate |

Em 5 das 6 combinações tour×superfície, `oppadj` é **pior** que `matchup`
simples para aces — e pior em todos os 3 folds em todas as combinações
overall já mostradas no item 2 (via `mean_delta_rel` menor da linha
`oppadj` frente à `matchup` na tabela completa). O único caso onde `oppadj`
ganha é ATP/Grass, isoladamente — amostra pequena, não suficiente para
justificar usar `oppadj` para aces.

**Resposta**: não, opponent adjustment não adiciona valor além do
Serve×Return simples para aces; pelo contrário, piora a previsão na imensa
maioria dos casos. O `matchup` simples é suficiente.

## 5. Hold × Break — mercados derivados de games (item 5)

Fonte: `data/outputs/phase5/hold_break_analysis.csv`, janela `last50`.

| Tour | Fold | isolated | matchup | oppadj |
|---|---|---|---|---|
| ATP | 2024 | 5,837 | 5,910 | **5,752** |
| ATP | 2025 | 5,938 | 6,014 | **5,787** |
| ATP | 2026 | 6,100 | 6,155 | **6,033** |
| WTA | 2024 | 5,407 | 5,500 | 5,265 (ainda pior que naive) |
| WTA | 2025 | 5,400 | 5,476 | 5,268 (ainda pior que naive) |
| WTA | 2026 | 5,424 | 5,518 | 5,243 (ainda pior que naive) |

**No ATP**: `matchup` sozinho é **pior** que `isolated` em `total_games`
(consistente nos 3 folds) — considerar apenas Hold%/Break% do adversário sem
a correção de força do adversário piora a previsão. `oppadj` recupera e
supera tanto `isolated` quanto `matchup` nos 3 folds e nas 3 superfícies
(ver item 3). Ou seja: **para games, ao contrário de aces, o ajuste pela
força do adversário é o que faz o matchup valer a pena.**

**Na WTA**: nenhuma das três variantes de `total_games` supera o baseline
trivial (todas as linhas de `total_games` WTA no item 2 são negativas); mas
entre as três variantes de modelo, `oppadj` é sempre a "menos ruim" — a
mesma direção de efeito do ATP aparece, só que insuficiente para vencer o
naive nesse mercado específico.

**Resposta**: para games/handicap/sets no ATP, opponent adjustment adiciona
valor real e mensurável além do matchup simples (o matchup simples, sem
ajuste, chega a piorar a previsão). Isso é o oposto do resultado em aces,
e é reportado exatamente como observado — nenhuma das duas conclusões foi
forçada para bater com a outra.

## 6. Janelas mais robustas por mercado (item 6)

Fonte: `data/outputs/phase5/janelas_melhor_por_grupo.csv`. Critério: não
apenas a menor MAE agregada, mas a combinação de (rank de MAE média entre
folds) + (rank de desvio-padrão entre folds) + (rank de desvio-padrão entre
superfícies) — a janela com a menor soma de ranks vence.

| Janela | Nº de vezes selecionada como mais robusta (24 combinações mercado×tour×variante) |
|---|---|
| `last50` | 15 |
| `career` | 4 |
| `surface_career` | 4 |
| `last20` | 1 (apenas `history_mean` de aces WTA) |
| `last10` | 0 |
| `last365d` | 0 |
| `decay90d` | 0 |

`last50` domina claramente como a janela mais estável (bom equilíbrio entre
amostra suficiente e recência). `surface_career` e `career` aparecem quando
o mercado tem forte componente de superfície (aces/tiebreak no ATP) ou
quando o histórico completo já é estável o bastante (double faults ATP,
game_diff WTA isolated). **`decay90d` nunca foi a janela mais robusta em
nenhuma combinação** — consistente com o achado da Fase 4 de que o
calendário real do tênis (lacunas longas entre temporadas) penaliza o
decaimento exponencial curto. `last10`/`last365d` também nunca venceram —
amostra pequena demais ou muito diluída, respectivamente. Isso responde
diretamente ao item 6: a janela não foi escolhida pela métrica agregada
isolada, e o resultado (recência moderada, não recência extrema) confirma
que não se deve assumir a priori que "mais recente é sempre melhor".

## 7. Overdispersion — Poisson vs Negative Binomial (item 7)

Fonte: `data/outputs/phase5/overdispersion_resumo.csv` (agregado de 330
combinações fold×variante×janela).

| Tour | Mercado | % folds com overdispersion | Razão var/média | % combinações onde NegBin bate Poisson (Brier) | Brier médio Poisson | Brier médio NegBin |
|---|---|---|---|---|---|---|
| ATP | aces_player | 100% | 4,32× | 87% | 0,2347 | 0,2251 |
| ATP | total_aces_match | 100% | 5,52× | 87% | 0,2487 | 0,2326 |
| ATP | double_faults_player | 100% | 2,09× | 100% | 0,2515 | 0,2448 |
| WTA | aces_player | 100% | 2,88× | 68% | 0,2217 | 0,2198 |
| WTA | total_aces_match | 100% | 3,32× | 85% | 0,2398 | 0,2323 |
| WTA | double_faults_player | 100% | 2,03× | 100% | 0,2403 | 0,2372 |

**Overdispersion está presente em 100% dos folds, para todos os mercados de
contagem, nos dois tours** — a variância dos aces/double faults reais é de
2 a 5,5 vezes a média, muito acima do que um Poisson (que assume
variância = média) consegue representar. Consequência direta: o Negative
Binomial bate o Poisson no Brier Score em 68%–100% das combinações
fold×janela×variante, e nunca perde na média agregada por mercado/tour.

**Resposta**: sim, Negative Binomial é consistentemente superior ao Poisson
para aces (e para double faults) nos dois tours. Isso será relevante na
Fase 6+ para o cálculo de probabilidades de linhas Over/Under — usar
Poisson puro subestimaria sistematicamente a probabilidade das caudas
(muitos aces ou muito poucos).

## 8. Classificação objetiva (item 8)

Critérios aplicados em `src/selection/classify.py` (determinístico, sem
score subjetivo — ver árvore de decisão completa em
`src/selection/config.py`):

- **CANDIDATO**: venceu o baseline em 3/3 folds, todas vitórias fortes
  (≥1% cada), melhora relativa média ≥3%, cobertura suficiente em todos os
  folds, sem deterioração de superfície sinalizada.
- **EXPERIMENTAL**: venceu em 2/3 folds, OU venceu em 3/3 mas com
  deterioração de superfície sinalizada, OU venceu em 3/3 mas com melhora
  média abaixo de 3%.
- **PAUSAR**: venceu em ≤1/3 folds, ou melhora relativa média ≤0.

Tabela completa em `data/outputs/phase5/classificacao_mercados.csv` /
`tabela_final_atp.csv` / `tabela_final_wta.csv`.

## 9. Tabela final

### ATP

| Mercado | Melhor abordagem | vs baseline (melhora média) | Folds vencidos | Superfícies | Estabilidade (desvio entre folds) | Decisão |
|---|---|---|---|---|---|---|
| aces_player | matchup_surface_career | +19,7% | 3/3 | consistente (Hard/Clay/Grass) | baixa (σ=1,6pp) | **CANDIDATO** |
| total_aces_match | matchup_surface_career | +20,5% | 3/3 | consistente | baixa (σ=2,2pp) | **CANDIDATO** |
| double_faults_player | isolated_last50 | +7,0% | 3/3 | consistente | baixa (σ=1,4pp) | **CANDIDATO** |
| total_games | oppadj_last50 | +12,2% | 3/3 | consistente | baixa (σ=1,1pp) | **CANDIDATO** |
| total_sets | oppadj_last50 | +19,6% | 3/3 | consistente | muito baixa (σ=0,7pp) | **CANDIDATO** |
| game_diff | oppadj_last50 | +7,9% | 3/3 | **Grass −47% (n=1.192)** | baixa no agregado | **EXPERIMENTAL** |
| tiebreak (logística) | logistic_regression_career | +2,2% | 3/3 | consistente | baixa | **EXPERIMENTAL** (melhora <3%) |
| full_distance | oppadj_last50 | −4,4% | 0/3 | nunca vence | — | **PAUSAR** |

### WTA

| Mercado | Melhor abordagem | vs baseline (melhora média) | Folds vencidos | Superfícies | Estabilidade | Decisão |
|---|---|---|---|---|---|---|
| aces_player | matchup_last50 | +15,8% | 3/3 | consistente | muito baixa (σ=0,5pp) | **CANDIDATO** |
| total_aces_match | matchup_last50 | +15,6% | 3/3 | consistente | baixa (σ=1,1pp) | **CANDIDATO** |
| double_faults_player | isolated_last50 | +9,8% | 3/3 | consistente | muito baixa (σ=0,7pp) | **CANDIDATO** |
| game_diff | isolated_last50 | +8,6% | 3/3 | consistente | baixa (σ=0,8pp) | **CANDIDATO** |
| total_games | history_mean_career | −0,2% | 1/3 | naive já vence | — | **PAUSAR** |
| total_sets | oppadj_last50 | −4,9% | 0/3 | naive já vence | — | **PAUSAR** |
| tiebreak (logística) | logistic_regression_career | −0,6% | 0/3 | naive já vence | — | **PAUSAR** |
| full_distance | oppadj_last50 | −5,5% | 0/3 | naive já vence | — | **PAUSAR** |

## 10. Respostas às perguntas obrigatórias (item 10)

**Qual mercado ATP demonstra maior robustez?**
Pelo escore objetivo (melhora relativa média − desvio-padrão entre folds),
`total_sets` lidera (0,190), seguido de perto por `total_aces_match`
(0,183) e `aces_player` (0,181) — os três dentro de uma margem pequena.
Como `total_sets` tem escala muito comprimida (a maioria das partidas é
2 sets em Bo3), o mercado de maior robustez com relevância prática direta é
**`total_aces_match`/`aces_player`**.

**Qual mercado WTA demonstra maior robustez?**
`aces_player` (matchup_last50), escore 0,153, seguido de `total_aces_match`
(0,146). Os dois lideram com folga sobre `double_faults_player` (0,091) e
`game_diff` (0,078).

**Aces ATP deve avançar?**
Sim. `aces_player` no ATP é CANDIDATO claro: vence o baseline em 3/3 folds,
melhora relativa média de 19,7%, estável entre folds (σ=1,6pp) e sem
deterioração em nenhuma superfície.

**O perfil do devolvedor melhora aces de forma consistente?**
Majoritariamente sim. `matchup` bate `isolated` em Hard e Clay nos dois
tours e na maioria dos folds/janelas em geral. A única exceção sistemática
é Grass, nos dois tours, onde `isolated` é ligeiramente melhor — efeito
pequeno e de amostra menor, não suficiente para reverter a conclusão geral.

**Opponent adjustment adiciona valor além do Serve×Return simples?**
Depende do mercado — e a resposta não foi forçada a ser igual nos dois
casos: **para aces, não** (`oppadj` piora em 5 de 6 combinações
tour×superfície). **Para games/handicap/sets no ATP, sim** (`oppadj`
recupera e supera tanto `isolated` quanto `matchup`; o `matchup` sozinho
chega a ser pior que `isolated` nesse mercado).

**Negative Binomial é superior ao Poisson para aces?**
Sim, de forma consistente: overdispersion em 100% dos folds (variância
2,9×–5,5× a média), e NegBin vence o Poisson no Brier Score em 68%–100% das
combinações, nos dois tours.

**Quais mercados devem ser abandonados por enquanto?**
`total_games`, `total_sets` e `tiebreak` na WTA; `full_distance` nos dois
tours. Em nenhum desses casos algum modelo supera o baseline trivial de
forma consistente — em vários, o baseline nunca é superado em nenhum dos
3 folds.

**Quais 1–3 mercados devemos levar para a próxima fase?**
`aces_player`, `total_aces_match` e `double_faults_player` — os **únicos
três mercados classificados como CANDIDATO simultaneamente em ATP e WTA**,
com melhora consistente (3/3 folds, vitórias fortes em todos), baixa
variação entre folds e sem deterioração de superfície sinalizada em nenhum
dos dois tours. `total_games`, `total_sets` e `game_diff` do ATP também são
fortes, mas isolados a um único tour (WTA falha nos dois primeiros; ATP
`game_diff` tem a ressalva de Grass) — candidatos de segunda linha, não
descartados, mas não incluídos no núcleo dos 3 primeiros por não terem
paridade ATP/WTA.

## 11. Limitações desta fase

- A classificação depende inteiramente da qualidade da Fase 4; nenhum
  modelo novo foi testado aqui — mercados PAUSAR podem voltar a ser
  avaliados se novos baselines forem propostos futuramente (fora do escopo
  atual).
- Os limiares numéricos (3% de melhora mínima, 10% de deterioração de
  superfície, n≥150/300) são escolhas razoáveis e documentadas, mas
  arbitrárias — outra escolha de limiar poderia mover 1-2 mercados
  fronteiriços (`tiebreak` ATP, `game_diff` ATP) entre categorias
  adjacentes. Isso está registrado explicitamente em cada linha da tabela
  de classificação (coluna `motivo`).
- 2026 é um fold parcial (até 2026-05-25); seu peso na "melhora relativa
  média" é igual ao dos folds completos de 2024/2025, o que pode
  sub-representar sazonalidade do calendário (ex.: turnos de saibro/grama
  ainda não completos em 2026 no momento da coleta).
- `total_sets`/`game_diff`/`full_distance` dependem do modelo de sets de
  Markov da Fase 4 (assunções documentadas: saque-A-sempre-primeiro no set,
  sets i.i.d., probabilidade de tie-break proxied por
  `hold_A/(hold_A+hold_B)`); qualquer viés desse modelo se propaga
  diretamente para esta análise de robustez.

## 12. Conclusão técnica

Dos 8 mercados iniciais do projeto (CLAUDE.md §1), a Fase 5 determina, com
critérios pré-definidos e auditáveis, que **aces por jogador, total de
aces e double faults por jogador têm evidência estatística suficiente,
consistente e simultânea em ATP e WTA** para avançar. `total_games`,
`total_sets` e `game_diff` do ATP têm evidência forte mas restrita a um
tour. Os mercados de distância da partida (`total_sets`/`total_games`/
`tiebreak`/`full_distance` na WTA, e `full_distance` no ATP) não superam
nem o baseline mais simples possível e devem ser pausados nesta forma
atual — não porque o esforço de modelagem foi insuficiente, mas porque os
dados, testados de forma honesta, não sustentam a hipótese de que esses
modelos agregam previsibilidade real além da média histórica.

O uso do devolvedor (Serve×Return) ajuda aces de forma consistente; o
ajuste por força do adversário (opponent adjustment) ajuda games mas
atrapalha aces — dois resultados opostos, ambos mantidos exatamente como
observados, sem forçar uma narrativa única.

---

**Parando aqui conforme instrução. Fase 6 (seleção final dos mercados mais
previsíveis) não foi iniciada.**
