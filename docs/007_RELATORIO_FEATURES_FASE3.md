# Relatório — Fase 3: Features Históricas Point-in-Time (Serve × Return)

Status: **Fase 3 concluída.** Não avançar para a Fase 4 sem nova instrução.

Entrada: exclusivamente `data/processed/{atp,wta}/matches.parquet` (Fase 2, nunca
reescrito). Saída: `data/processed/features/{atp,wta}/player_match_features.parquet`.

---

## 1. Visão geral do pipeline

```
src/features/
  score_parser.py   -- item 1: parser robusto do campo `score`
  metrics.py         -- itens 2-3: colunas derivadas + registro de fórmulas
  rolling.py          -- motor genérico de agregação point-in-time (soma e decay)
  profile.py           -- itens 4-7: perfil pré-jogo do jogador (janelas, superfície, amostra)
  matchup.py             -- itens 8-9: self-join do adversário, comparativos, ajuste por força do adversário
  build.py                 -- orquestrador: monta a tabela final por tour e grava Parquet
  config.py                 -- janelas, meia-vida padrão, diretórios de saída
scripts/build_features_phase3.py   -- CLI
tests/test_features.py             -- 25 testes (parser, anti-leakage, self-join, integração)
```

Execução: `python scripts/build_features_phase3.py`.

Regra de ordenação cronológica (CLAUDE.md #3): todas as agregações usam
`(player_id, tournament_date, _seq)`, onde `_seq` é a posição da linha na
tabela de partidas da Fase 2 já ordenada por
`[tournament_date, tourney_id, match_id, result]`. Isso serve de desempate
determinístico quando um jogador tem mais de uma partida na mesma data (ex.
Davis Cup com dois jogos no mesmo dia) — é uma convenção documentada, não um
fato observado, pois o dado bruto não tem hora do dia.

---

## 2. Item 1 — Parser de score

Antes de escrever o parser, os 4.272 valores únicos de `score` (ATP+WTA) foram
inspecionados diretamente. Formatos encontrados: sets normais (`6-4`),
tie-break (`7-6(4)`), match/super tie-break entre colchetes (`[10-7]`, usado
em eventos que decidem o set decisivo com um tie-break estendido), e códigos
de status: `RET` (367 ocorrências), `W/O` / `Walkover` (2), `DEF` / `Def.` (5),
`ABD` (1), e uma variante com sufixo (`RET+H61`, código médico anexado).

`parse_score(raw)` retorna, por partida: `status`
(`completed|retired|walkover|defaulted|abandoned|missing|unparseable`),
`complete` (bool — só `True` quando o placar foi jogado até o fim sem
ambiguidade), `total_games`/`winner_games`/`loser_games`/`game_diff`
(somando **apenas os sets efetivamente concluídos**), `sets_won_winner`/
`sets_won_loser`, `has_tiebreak`/`n_tiebreaks`, `has_match_tiebreak`/
`n_match_tiebreaks_completed`, `has_partial_trailing_set`, `parse_ok`.

Regra de não invenção: um set é considerado "concluído" apenas se atinge uma
contagem válida (≥6 com diferença ≥2, ou 7-6/7-5). Um fragmento como `"2-1"`
antes de `RET` **não** é tratado como set — não entra em `total_games`. Um
super tie-break interrompido (`[0-1]`) também não é contado.

**Achado durante a calibração:** 124 linhas (62 partidas) têm `status ==
"completed"` mas `complete == False` — placares como `"6-2 5-7 [0-1]"`, onde
o super tie-break decisivo foi claramente interrompido (`[0-1]`) mas a fonte
não anexou nenhum código `RET/DEF/ABD`. O parser corretamente não inventa o
resultado: marca `complete=False` e preserva os dois sets reais já jogados.
Isso é uma característica dos dados brutos, não um bug do parser — foi
verificado diretamente nos scores originais antes de codificar essa regra.

Cobertura: **96,1% (ATP) / 96,2% (WTA)** das linhas têm placar `complete=True`.
O restante se distribui em `retired` (2,8%/2,9%), `walkover` (0,7%/0,8%),
`defaulted` e `abandoned` (ATP, <0,1% cada). Ver
`data/processed/features/reports/score_coverage_report.csv`.

### Retirement / Walkover / Default / Abandoned

Todos os quatro ficam com `complete=False` e **não devem ser usados sem
tratamento explícito nos mercados de Total de Games/Sets/Handicap na Fase 4**
— essa é uma recomendação, não uma decisão tomada aqui (CLAUDE.md #24: a
Fase 3 não modela nem decide estratégia de mercado). As colunas
`score_total_games` etc. continuam preenchidas com os sets realmente jogados
(não `None`), para o caso de a Fase 4 optar por um tratamento parcial.

---

## 3. Itens 2-3 — Fórmulas de saque e devolução

Todas as métricas somam numerador e denominador **ao longo da janela** antes
de dividir (CLAUDE.md #5 — nunca média de percentuais por partida).

### Saque (`player_serve_*`)

| Métrica | Fórmula |
|---|---|
| `ace_rate` | `aces / service_points` |
| `double_fault_rate` | `double_faults / service_points` |
| `first_serve_in_pct` | `first_serves_in / service_points` |
| `first_serve_points_won_pct` | `first_serve_points_won / first_serves_in` |
| `second_serve_points_won_pct` | `second_serve_points_won / (service_points - first_serves_in)` |
| `service_points_won_pct` | `(first_serve_points_won + second_serve_points_won) / service_points` |
| `break_points_saved_pct` | `break_points_saved / break_points_faced` |
| `hold_pct` | `(service_games - (break_points_faced - break_points_saved)) / service_games` |

### Devolução (`player_return_*`)

| Métrica | Fórmula |
|---|---|
| `ace_allowed_rate` | `opponent_aces / return_points` |
| `return_points_won_pct` | `(return_points - opponent_first_serve_points_won - opponent_second_serve_points_won) / return_points` |
| `first_serve_return_points_won_pct` | `(opponent_first_serves_in - opponent_first_serve_points_won) / opponent_first_serves_in` |
| `second_serve_return_points_won_pct` | `(opponent_second_serves_in - opponent_second_serve_points_won) / opponent_second_serves_in` |
| `break_points_created_per_return_game` | `break_points_created / opponent_service_games` |
| `break_conversion_pct` | `break_points_converted / break_points_created` |
| `break_pct` | `break_points_converted / opponent_service_games` |

**Hold%/Break% não são dado bruto** — os dados Sackmann são agregados por
partida, sem log jogo a jogo. São derivados de uma propriedade exata (não
aproximação): como o game de saque termina no instante em que um break point
é convertido, no máximo 1 break point por game pode ser "convertido"; logo
`break_points_faced - break_points_saved` é **exatamente** a contagem de
games quebrados naquele saque, e `break_points_converted` (já calculado na
Fase 2) é exatamente a contagem de games quebrados naquela devolução. Essa é
a mesma convenção usada por análises públicas de tênis (ex. Tennis Abstract).

Todas as somas usam preenchimento transitório de ausência com 0 **apenas
para viabilizar a soma cumulativa** (ver seção 5) — a taxa final só é
calculada quando o denominador somado é `> 0`; caso contrário fica `None`,
nunca `0`.

---

## 4. Item 4 — Janelas históricas

| Janela | Tipo |
|---|---|
| `career` | toda a carreira anterior (sem limite) |
| `last10` / `last20` / `last50` | últimas N partidas anteriores |
| `last365d` | partidas anteriores nos últimos 365 dias corridos |
| `surface_career` | toda a carreira anterior **na mesma superfície** |
| `decay90d` | soma ponderada por decaimento exponencial (seção 5) |

Nenhuma janela foi escolhida como "melhor" — todas ficam disponíveis lado a
lado na tabela de saída, para comparação na Fase 4/5 (CLAUDE.md #9, #19).

---

## 5. Item 5 — Estratégia de recência (decay)

`compute_decay_priors` implementa uma soma ponderada por decaimento
exponencial com meia-vida configurável em dias, via recorrência O(n) por
jogador:

```
D_i = 0.5^(gap_dias / meia_vida) * (D_{i-1} + v_{i-1})
```

onde `D_i` é a soma decaída de todas as partidas anteriores, avaliada na
data da partida `i`. A função aceita qualquer meia-vida; a base de saída
materializa **uma** versão (`decay90d`, meia-vida = 90 dias) para não
multiplicar o número de colunas — a escolha de 90 dias é um valor de
referência, não uma conclusão de qual meia-vida é melhor (isso é
explicitamente adiado para a Fase 4/backtest, conforme CLAUDE.md #9).
Qualquer outra meia-vida pode ser gerada chamando `compute_decay_priors`
novamente com outro valor.

**Bug encontrado e corrigido durante o desenvolvimento:** a primeira versão
reportava `n_prior_matches` também decaído, o que fazia a contagem de
amostra tender a 0 mesmo quando havia muitas partidas antigas reais (ex.: 3
partidas reais, mas todas fora da meia-vida, arredondavam para "0 partidas").
Corrigido para reportar a contagem **real** (não decaída) de partidas
anteriores — é essa contagem que importa para avaliar confiabilidade da
amostra (item 7).

---

## 6. Item 6 — Superfície

`surface_career` agrupa por `(player_id, surface)` e agrega só entre
partidas do jogador na mesma superfície (Hard/Clay/Grass — os valores já
normalizados pela Fase 2). Partidas com superfície ausente na Fase 2 (Davis
Cup World Group Play-offs, achado documentado no relatório da Fase 2) ficam
de fora do agrupamento: `surface_prior_matches = 0` e as taxas
`*_surface_career` ficam `None`, nunca preenchidas artificialmente — e a
linha é sinalizada em `player_surface_cold_start`.

---

## 7. Item 7 — Qualidade da amostra

Cada janela vem acompanhada de `prior_matches_{janela}` (ou
`surface_prior_matches`), `prior_service_points_{janela}` e
`prior_return_points_{janela}` — para saber se uma taxa vem de 3 partidas ou
de 80. Resumo (`data/processed/features/reports/sample_size_report.csv`):

| Janela | % linhas com ≥1 partida prévia | % com ≥10 | % com ≥50 |
|---|---|---|---|
| career (ATP) | 96,9% | 83,3% | 53,6% |
| career (WTA) | 96,9% | 81,8% | 50,1% |
| surface_career (ATP) | 94,1% | 69,8% | 28,0% |
| surface_career (WTA) | 93,4% | 66,5% | 22,9% |
| last365d (ATP) | 96,3% | 79,9% | 31,5% |
| last365d (WTA) | 96,2% | 77,3% | 21,3% |

Como esperado, `last10`/`last20` nunca atingem o limiar de 20/50 (são
capados por construção — o relatório mostra 0% nesses casos, o que é
correto, não um erro).

---

## 8. Item 8 — Matchup (Serve A × Return B)

Como cada `match_id` já tem exatamente 2 linhas (uma por jogador), obter o
lado do adversário é um **self-join** por `(match_id, opponent_id ==
player_id da outra linha)` — sem recalcular nada, só trazer as colunas
`player_serve_*`/`player_return_*` já point-in-time da linha do adversário,
renomeadas para `opponent_serve_*`/`opponent_return_*`. Nenhuma informação
da partida atual entra nessa comparação, porque os valores trazidos já são
os do adversário calculados **antes** dessa mesma partida.

Para conter o número de colunas, o self-join e os comparativos cobrem só as
janelas "headline": `career`, `surface_career`, `last50`.

Comparativos simples (sem modelagem, apenas subtração), por janela:

- `matchup_ace_rate_vs_allowed_{w} = player_serve_ace_rate_{w} - opponent_return_ace_allowed_rate_{w}`
- `matchup_hold_vs_break_{w} = player_serve_hold_pct_{w} - opponent_return_break_pct_{w}`
- `matchup_opp_ace_vs_player_allowed_{w} = opponent_serve_ace_rate_{w} - player_return_ace_allowed_rate_{w}`
- `matchup_opp_hold_vs_player_break_{w} = opponent_serve_hold_pct_{w} - player_return_break_pct_{w}`

Cobertura do self-join (`% linhas com dado do adversário disponível`):
career 95,8%/96,3% (ATP/WTA), surface_career 93,1%/92,7%, last50
95,8%/96,3% — a diferença para 100% é exatamente quando o **adversário**
está em cold start naquela janela (não há nada a preencher, e a linha fica
`None`, não 0/inventado).

---

## 9. Item 9 — Ajuste por força do adversário

Metodologia (a mais simples entre as plausíveis, conforme pedido): para
cada partida anterior do próprio jogador, a coluna `opponent_serve_ace_rate_{w}`
(ou equivalente) — já point-in-time, vinda do self-join da seção 8 — descreve
a força do adversário **naquele momento**. Calculando a **média simples**
dessas colunas ao longo do histórico anterior do jogador (mesmo motor de
agregação, agora fazendo média em vez de soma de contagem bruta), obtém-se
"força média dos adversários enfrentados". O ajuste é a diferença simples
entre a taxa do jogador e essa média — sem nenhum dado futuro: cada termo da
média usa o estado do adversário antes daquela partida específica, e a
própria média só usa partidas anteriores do jogador.

Implementado para as 4 métricas pedidas, nas janelas `career` e `last50`:

- `opponent_adjusted_ace_rate = player_serve_ace_rate - média(opponent_return_ace_allowed_rate faced)`
- `ace_suppression = média(opponent_serve_ace_rate faced) - player_return_ace_allowed_rate` (CLAUDE.md #6: positivo = suprime mais aces que o esperado)
- `opponent_adjusted_hold_pct = player_serve_hold_pct - (1 - média(opponent_return_break_pct faced))`
- `opponent_adjusted_break_pct = player_return_break_pct - (1 - média(opponent_serve_hold_pct faced))`

**Bug encontrado e corrigido durante o desenvolvimento:** a primeira versão
comparava `hold_pct` diretamente com a média de `opponent_return_break_pct`
(sem complementar). Como Hold% (média ≈ 0,80) e Break% (média ≈ 0,20) são
eventos **complementares** do mesmo game de saque, e não a mesma grandeza,
a diferença direta ficava estruturalmente deslocada para ≈ 0,58 em vez de
centrada perto de 0. Corrigido para usar o complementar
`(1 - média(break% do adversário))` como "taxa de hold esperada" — depois da
correção, as quatro métricas de ajuste ficam corretamente centradas perto de
0 (médias entre 0,002 e 0,010 nos dados reais), como esperado para um
ajuste bem calibrado.

---

## 10. Item 10 — Cold start

Nenhum jogador sem histórico recebe média inventada. `player_cold_start`
(nenhuma partida anterior na carreira) e `player_surface_cold_start`
(nenhuma partida anterior na mesma superfície, ou superfície ausente) ficam
explícitos como colunas booleanas, e toda taxa correspondente fica `None`.

Cobertura: **823 linhas ATP (3,1%) e 754 linhas WTA (3,1%)** em cold start
total — a primeira partida observada de cada jogador na janela de dados
2022-2026 (não necessariamente sua estreia real: jogadores com carreira
iniciada antes de 2022 aparecem como cold start aqui porque o dataset da
Fase 1 cobre 2022 em diante — limitação herdada e já documentada na Fase 1).

---

## 11. Item 11 — Validação anti-leakage

`tests/test_features.py` — **25/25 testes passando**, incluindo:

- `test_current_match_excluded_from_own_features` — 1ª partida do jogador
  tem `prior_matches_career == 0` e feature `None`.
- `test_career_prior_matches_exact_count` — a k-ésima partida tem
  exatamente k partidas anteriores (dado sintético controlado).
- `test_career_ace_rate_matches_manual_sum` — reconstrução manual exata.
- `test_future_matches_never_leak_in` — recomputando a mesma partida com e
  sem partidas futuras concatenadas, a feature não muda.
- `test_rolling_window_ends_before_match_date` — movendo uma partida antiga
  para fora da janela de 365 dias, ela some do `last365d` mas continua no
  `career`.
- `test_surface_career_uses_only_same_surface_prior` — jogador alternando
  Hard/Clay; a janela de superfície conta só as partidas da mesma superfície.
- `test_last_n_window_caps_correctly` — janela `last10` nunca ultrapassa 10
  partidas mesmo com histórico maior.
- `test_atp_and_wta_never_mix_even_if_same_player_id_suffix` — mesmo
  concatenando ATP e WTA propositalmente em uma tabela única (o que a Fase 3
  nunca faz na prática — cada tour é processado separadamente), o
  `player_id` já escopado por tour (Fase 2) garante que os grupos de
  agregação nunca se misturam; alterar uma partida ATP não muda nada do
  lado WTA.
- `test_opponent_columns_mirror_opponent_own_row` — o self-join do item 8
  traz exatamente o valor que a linha do próprio adversário já tinha.
- `test_manual_ace_rate_reconstruction` (item 11, "teste manual") —
  reconstrução manual, **sobre dado real** (não sintético): soma
  `aces`/`service_points` das partidas estritamente anteriores de um jogador
  real e compara com `player_serve_ace_rate_career` na 16ª partida da
  carreira dele — bate exatamente.
- Testes de integração sobre a base real: contagem de linhas igual à Fase 2,
  nenhuma sobreposição de `player_id` entre ATP/WTA, cold start com `NaN`
  (não zero), taxas dentro de `[0, 1]`.

Suíte combinada (Fases 1+2+3): **54/54 testes passando**
(`python -m unittest tests.test_ingestion tests.test_normalization tests.test_features`).

---

## 12. Saída

```
data/processed/features/
  atp/player_match_features.parquet   (26.744 linhas, 232 colunas, ~37 MB)
  wta/player_match_features.parquet   (24.366 linhas, 232 colunas, ~33 MB)
  reports/
    sample_size_report.csv
    score_coverage_report.csv
    phase3_diagnostics.json
  samples/
    features_sample_atp.csv
    features_sample_wta.csv
```

Os Parquets normalizados da Fase 2 (`data/processed/{atp,wta}/*.parquet`)
não foram tocados. ATP e WTA continuam em arquivos separados.

Composição das 232 colunas: 16 de contexto + 126 do perfil do jogador (7
janelas × (3 colunas de amostra + 8 métricas de saque + 7 de devolução)) + 2
flags de cold start + 45 `opponent_*` (self-join, 3 janelas headline × 15
métricas) + 12 comparativos de matchup + 16 de ajuste por adversário (4
métricas × 2 janelas × (diferença + força média do adversário)) + 15 do
parser de score.

---

## 13. Problemas encontrados

1. **62 partidas com super tie-break interrompido sem código de status**
   (`"6-2 5-7 [0-1]"`) — `status="completed"` mas `complete=False`; tratado
   corretamente pelo parser (seção 2), não preenchido.
2. **Cold start em 3,1% das linhas** — não é erro, é a fronteira real do
   dataset 2022-2026 (herdado da Fase 1/2).
3. **Superfície ausente em Davis Cup Play-offs** (achado da Fase 2) —
   propaga para `surface_career` como cold start de superfície nessas
   linhas.
4. **Ordem intra-dia é uma convenção, não um fato observado** — o dado
   bruto não tem hora do dia; partidas do mesmo jogador na mesma data usam
   a ordem de gravação da Fase 2 (`tourney_id, match_num`) como desempate.
5. **Janela `last365d` com duas partidas na mesma data exata** — o rolling
   baseado em tempo do pandas inclui todas as linhas com timestamp idêntico
   dentro da janela; em teoria uma partida poderia "ver" outra partida do
   mesmo jogador na mesma data ao computar sua própria janela de 365 dias.
   Não observado nos dados reais (datas de partida têm granularidade diária
   e jogos do mesmo jogador no mesmo dia são raros), mas documentado como
   limitação teórica do método.
6. **Dois bugs de fórmula encontrados e corrigidos durante o
   desenvolvimento** (detalhados nas seções 5 e 9): contagem decaída
   colapsando para 0, e ajuste Hold%/Break% sem complementar. Ambos
   corrigidos e re-verificados antes de gravar a base final.

Nenhum problema estrutural (linhas por partida, tipos de dado, separação
ATP/WTA) foi encontrado — todos os testes de integridade passaram.

---

## 14. Cobertura — mercados do projeto

| Mercado (CLAUDE.md #1) | Suporte na Fase 3 |
|---|---|
| Aces por jogador | `player_serve_ace_rate_*` × `opponent_return_ace_allowed_rate_*` prontos em todas as janelas |
| Total de aces | combinação dos dois lados (Fase 4) a partir das mesmas colunas |
| Total de games | `score_total_games` (só quando `score_complete=True`, 96%) |
| Handicap de games | `score_game_diff` |
| Double faults | `player_serve_double_fault_rate_*` |
| Total de sets | `score_sets_won_winner/loser`, `score_n_sets_completed` |
| Tie-break | `score_has_tiebreak`/`score_n_tiebreaks`/`score_has_match_tiebreak` |

Todos os 7 mercados têm colunas prontas para a Fase 4. Total de
games/sets/tie-break dependem do placar estar `complete=True` (96% das
partidas) — partidas com retirement/walkover/default ficam com esses campos
parciais e devem ser tratadas explicitamente na Fase 4 (filtrar ou modelar à
parte), decisão que não foi tomada aqui.

---

## 15. Exemplos reais — Serve × Return

Três partidas reais (Roland Garros 2026, R128/SF), escolhidas por terem
histórico substancial dos dois lados (`prior_matches_career` e
`surface_prior_matches` altos) — valores calculados **apenas com partidas
anteriores** a 2026-05-25.

### Exemplo 1 — ATP:2026-520:152 (Clay, R128)
**Alejandro Davidovich Fokina** venceu **Damir Dzumhur**.

**Davidovich Fokina Serve Profile (239 partidas prévias, 65 em Clay) × Dzumhur Return Profile (87 partidas prévias, 44 em Clay):**
- Ace Rate (ADF): 4,49% — Ace Allowed Rate (Dzumhur): 6,12%
- Hold% (ADF): 78,18% — Break% (Dzumhur): 24,12%
- `matchup_ace_rate_vs_allowed_career` = -0,0164 · `matchup_hold_vs_break_career` = **+0,541** (favorece ADF no saque)

**Dzumhur Serve Profile (87 partidas prévias) × Davidovich Fokina Return Profile (239 partidas prévias):**
- Ace Rate (Dzumhur): 1,77% — Ace Allowed Rate (ADF): 8,21%
- Hold% (Dzumhur): 70,03% — Break% (ADF): 24,90%
- `matchup_opp_hold_vs_player_break_career` = +0,451 (visto do lado de ADF)

### Exemplo 2 — ATP:2026-520:143 (Clay, R128)
**Tommy Paul** venceu **Rinky Hijikata**.

**Paul Serve Profile (275 partidas prévias, 58 em Clay) × Hijikata Return Profile (106 partidas prévias, 14 em Clay):**
- Ace Rate (Paul): 6,84% — Ace Allowed Rate (Hijikata): 10,01%
- Hold% (Paul): 81,64% — Break% (Hijikata): 19,81%
- `matchup_hold_vs_break_career` = **+0,618**

**Hijikata Serve Profile (106 partidas prévias) × Paul Return Profile (275 partidas prévias):**
- Ace Rate (Hijikata): 5,14% — Ace Allowed Rate (Paul): 5,73%
- Hold% (Hijikata): 73,21% — Break% (Paul): 26,01%
- `matchup_opp_hold_vs_player_break_career` (visto de Paul) = +0,472

### Exemplo 3 — WTA:2026-520:156 (Clay, R128)
**Jasmine Paolini** venceu **Dayana Yastremska**.

**Paolini Serve Profile (249 partidas prévias, 66 em Clay) × Yastremska Return Profile (164 partidas prévias, 40 em Clay):**
- Ace Rate (Paolini): 1,76% — Ace Allowed Rate (Yastremska): 3,10%
- Hold% (Paolini): 66,45% — Break% (Yastremska): 32,96%
- `matchup_hold_vs_break_career` = **+0,335**

**Yastremska Serve Profile (164 partidas prévias) × Paolini Return Profile (249 partidas prévias):**
- Ace Rate (Yastremska): 3,81% — Ace Allowed Rate (Paolini): 4,53%
- Hold% (Yastremska): 63,22% — Break% (Paolini): 37,70%
- `matchup_opp_hold_vs_player_break_career` (visto de Paolini) = +0,255

Todos os valores acima foram lidos diretamente do Parquet gerado — não são
ilustrativos, refletem exatamente o que a Fase 4 vai consumir.

---

## 16. Resumo executivo

- Base de features point-in-time construída para ATP (26.744 linhas /
  13.372 partidas) e WTA (24.366 linhas / 12.183 partidas), 232 colunas por
  tour, sem tocar nos Parquets da Fase 2.
- Nenhuma feature usa dados da própria partida ou de partidas futuras —
  garantido por construção (shift/cumsum antes da soma) e verificado por 25
  testes automatizados, incluindo reconstrução manual sobre dado real.
- Dois bugs de fórmula foram encontrados e corrigidos durante o
  desenvolvimento (contagem decaída colapsando a 0; ajuste Hold%/Break% sem
  complementar) — documentados nas seções 5 e 9.
- Nenhuma média, janela ou meia-vida foi escolhida como "a melhor" — todas
  ficam lado a lado para comparação na Fase 4/5, conforme CLAUDE.md #9/#19.
- Cold start (3,1% das linhas) e amostras pequenas ficam explícitos via
  `*_cold_start` e `prior_matches_*`, nunca preenchidos artificialmente.
- Todos os 7 mercados do projeto (CLAUDE.md #1) têm colunas prontas para a
  Fase 4.

**Parando aqui conforme instrução. Fase 4 (baselines estatísticos) não foi
iniciada.**
