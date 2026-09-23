# 012 — ODD JUSTA E ODD MÍNIMA ACEITÁVEL (FASE 7)

## 0. Escopo

Esta fase converte a **probabilidade operacional** já definida e validada na Fase 6.1
(`docs/011_CALIBRACAO_PROBABILISTICA_FASE6_1.md`) em odd justa e em uma faixa de odds
mínimas aceitáveis, para os três mercados já selecionados nas Fases 5/6/6.1:

- `aces_player`
- `total_aces_match`
- `double_faults_player`

ATP e WTA sempre separados.

Esta fase **não** treina nenhum modelo novo, **não** recalibra nenhuma probabilidade, **não**
consulta casas de apostas, **não** faz scraping, **não** calcula stake e **não** cria interface.
Ela lê exclusivamente dois arquivos já produzidos:

- `data/outputs/phase6/previsoes_por_linha.parquet` — contexto de cada linha (superfície,
  tamanho de histórico, dificuldade da linha), calculado na Fase 6;
- `data/outputs/phase6_1/previsoes_calibradas.parquet` — `raw_probability`,
  `calibrated_probability`, método de calibração escolhido e tamanho da amostra do
  calibrador, calculados na Fase 6.1.

As duas tabelas têm exatamente as mesmas 1.036.994 linhas (contexto × linha `.5`), 1:1, o que
foi verificado antes de escrever o código (`merge(..., validate="one_to_one")` não falhou).

Código: `src/pricing/` (`config.py`, `odds.py`, `flags.py`, `build.py`).
CLI: `scripts/build_pricing_phase7.py`.
Testes: `tests/test_pricing.py` (20 testes, todos passando; 115/115 no total do projeto).
Saídas: `data/outputs/phase7/`.

---

## 1. Como a odd justa está sendo calculada?

Para cada linha `.5` e cada lado (Over/Under), a odd justa é o inverso direto da
**probabilidade operacional** — a probabilidade que a Fase 6.1 já decidiu ser a melhor
estimativa disponível para aquele mercado/tour (ver seção 2):

```
fair_odds = 1 / operational_probability
```

Para o Over, `operational_probability` é a coluna `calibrated_probability` da Fase 6.1
diretamente (que já é a probabilidade de Over da linha, calibrada quando o calibrador foi
aprovado, bruta quando não foi). Para o Under, aplicamos exatamente a fórmula da instrução:

```
under_probability = 1 - operational_probability
fair_odds_under = 1 / under_probability
```

Não recalibramos o lado Under de forma independente — ele é sempre o complemento aritmético
do Over, tanto para a probabilidade bruta quanto para a calibrada. Isso é consistente com o
que a Fase 6 já fazia (uma única distribuição de contagem gera P(Over) e P(Under) = 1 -
P(Over) para a mesma linha) e evita inventar um segundo processo de calibração que a Fase 6.1
não teve instrução de construir.

Probabilidades inválidas ou ausentes (`p <= 0`, `p >= 1`, `NaN`) não geram odd — a função
`odds.fair_odds` retorna `NaN` nesses casos em vez de dividir por zero ou por um número
negativo (verificado em `tests/test_pricing.py::TestFairOdds`).

**Exemplo verificado com o próprio caso da instrução**: p = 0,625 → odd justa = 1,60 (teste
`test_fair_odds_example_from_instructions`, resultado exato).

---

## 2. Qual a diferença entre odd justa e odd mínima aceitável?

- **Odd justa** (`fair_odds`) é o preço de equilíbrio matemático — a odd em que apostar teria
  valor esperado exatamente zero segundo a probabilidade do modelo. Não embute nenhuma margem
  de segurança.
- **Odd mínima aceitável** (`odd_minima`) é a odd mais baixa que ainda representaria uma
  vantagem estatística (edge) de pelo menos `e` sobre a probabilidade implícita da odd,
  segundo o critério probabilístico pedido na instrução:

```
p_implicita_maxima = p_modelo - e
odd_minima = 1 / p_implicita_maxima         (somente se p_modelo - e > 0)
```

Ou seja: a odd mínima aceitável não é "odd justa × (1 + margem)" — é a odd cuja probabilidade
implícita (`1/odd`) fica `e` pontos percentuais **abaixo** da probabilidade do modelo. Isso
produz uma folga em odds decimais que cresce de forma não linear (mais acentuada em
probabilidades baixas do que em probabilidades altas), diferente de uma margem multiplicativa
simples. Quando `p_modelo - e <= 0` (edge exigido maior que a própria probabilidade do
modelo), a odd mínima não é calculada (`NaN`) — não existe odd finita que satisfaça esse
requisito.

---

## 3. Como o edge mínimo altera o preço aceitável?

Comparamos cinco cenários de edge mínimo, sem escolher nenhum como padrão operacional (item
10 da instrução — essa escolha fica para uma fase futura, com dados de odds reais/paper
trading): **2%, 3%, 5%, 7,5% e 10%**.

Quanto maior o edge exigido, maior a odd mínima aceitável (testado e confirmado em
`test_minimum_odds_increases_with_required_edge`, e verificável em qualquer linha da tabela
`odds_minimas_por_edge.parquet`). Exemplo real do pipeline (ATP aces_player, Over 8,5,
fold_2025, probabilidade operacional 29,72% após calibração Platt — ver exemplo 2 na seção 8):

| Edge exigido | Odd mínima aceitável |
|---|---:|
| — (odd justa) | 3,36 |
| 2% | 3,61 |
| 3% | 3,74 |
| 5% | 4,04 |
| 7,5% | 4,50 |
| 10% | 5,07 |

O segundo exemplo reproduzido a partir de dados reais do pipeline (WTA aces_player, Over 2,5,
fold_2025, p=62,98%) bate, com arredondamento de centavos, com o próprio exemplo numérico dado
na instrução (p=63%, odd justa 1,59, mínimas 1,64/1,67/1,72/1,80/1,89) — usado como teste de
regressão em `test_minimum_odds_matches_instructions_example`.

---

## 4. Quais mercados/tours estão liberados?

Reaproveitando a classificação já publicada na Fase 6.1 (docs/011, seção 15), **5 das 6
combinações mercado×tour estão em PRONTO PARA ODDS**, sem nenhuma ressalva adicional nesta
fase:

- ATP `total_aces_match`
- ATP `double_faults_player`
- WTA `aces_player`
- WTA `total_aces_match`
- WTA `double_faults_player`

Para essas cinco, a probabilidade operacional (calibrada quando o calibrador foi aprovado, ou
bruta) tem ECE ≤ 0,03 no pior fold avaliável e nenhuma superfície com amostra adequada piora
em relação ao bruto — geramos odd justa e odd mínima normalmente, sem flag de restrição.

---

## 5. Quais possuem restrições?

Apenas **ATP `aces_player` em Grass** carrega a flag `restricted=True` (herdada diretamente da
classificação "USAR COM RESTRIÇÃO" da Fase 6.1): o ECE piora de 0,031 para 0,039
especificamente em Grass depois da calibração Platt (n=7.966 no fold avaliado), enquanto
Hard/Clay (~90% da amostra do mercado) não apresentam essa ressalva.

**A linha não é removida nem tem o preço ocultado** — continua recebendo odd justa e odds
mínimas normalmente, apenas com `restricted=True` e `restricted_motivo` preenchido, para que
qualquer consumidor futuro dessa tabela saiba que a calibração ali é menos confiável antes de
decidir usar o preço. Na base atual, 32.956 das 2.073.988 linhas de preço (1,6%) carregam essa
flag — todas nos contextos ATP/`aces_player`/Grass, dos dois lados (Over e Under).

Nenhuma combinação mercado×tour foi classificada como NÃO PRONTO (nenhuma tem ECE > 0,03 em
algum fold avaliável nem calibração ausente com probabilidade bruta ruim) — portanto nenhuma
foi bloqueada por completo nesta fase.

---

## 6. Como tratar probabilidades acima de 90%?

Toda linha (de qualquer lado, Over ou Under) cuja probabilidade operacional seja `>= 90%`
recebe a flag `extreme_probability=True` — mas **continua recebendo preço normalmente**, sem
nenhum ajuste automático. A instrução é explícita em não tratar essas previsões como
"automaticamente superiores": probabilidade alta não significa necessariamente boa relação
risco/retorno, e a Fase 6.1 documentou que a faixa 90%+ é justamente onde a calibração é mais
difícil de verificar por escassez relativa de observações e onde o desvio residual pós-
calibração é maior (docs/011, seção 8). A flag serve para que qualquer critério de seleção
futuro possa aplicar cautela extra ali — por exemplo, exigir edge mínimo maior — sem que essa
decisão seja tomada nesta fase.

Na base atual, 506.785 das 2.073.988 linhas de preço já desdobradas por lado (linha × lado,
24,4%) têm probabilidade operacional `>= 90%` naquele lado especificamente — a grande maioria
no lado Under de linhas muito baixas ou no lado Over de linhas muito altas (extremos da
distribuição, esperado por construção do grid de linhas).

---

## 7. Como tratar Grass ATP em aces?

Ver seção 5: a flag `restricted` é aplicada a toda linha de `aces_player`/ATP/Grass, com o
motivo textual documentado na própria linha (`restricted_motivo`), citando a evidência exata
da Fase 6.1 (ECE 0,031→0,039). O preço continua sendo gerado — a restrição é uma flag de
cautela operacional, não uma exclusão. Nenhum outro mercado ou tour herda essa restrição em
Grass: `total_aces_match` prefere `matchup` em Grass e não teve ressalva de calibração
documentada; `double_faults_player` nunca teve uma variante Serve×Return modelada e também não
teve ressalva.

---

## 8. Como futura odd observada será comparada com o modelo?

Implementamos dois utilitários prontos para uso futuro (não usados com odds reais nesta fase —
apenas testados com exemplos unitários controlados, conforme instrução):

```python
implied_probability = 1 / decimal_odds     # src/pricing/odds.py: implied_probability()
edge = operational_probability - implied_probability   # src/pricing/odds.py: edge()
```

`implied_probability` retorna `NaN` para odds inválidas (`<= 1.0`, `NaN`, negativas).
`edge` é simplesmente a diferença — positivo quando o modelo acha a probabilidade real maior
do que a odd observada implica (potencial value), negativo caso contrário. Quando a Fase 8/9
trouxer odds reais, o fluxo será: odd observada → `implied_probability` → comparar com
`operational_probability` já salva em `precos_por_linha.parquet` → `edge`. Nenhuma odd real foi
consultada ou usada nesta fase.

---

## 9. Flags de qualidade — resumo

| Flag | Significado | Efeito no preço |
|---|---|---|
| `cold_start` | `sample_bucket_career == "cold_start"` (nenhuma partida anterior do jogador) | **Não gera odd justa nem odd mínima** (`NaN` forçado) |
| `insufficient_history` | `sample_bucket_career == "small_1_9"` (1 a 9 partidas anteriores) | Gera preço normalmente, com flag visível |
| `calibrator_insufficient_sample` | Amostra de treino do calibrador (Fase 6.1) abaixo de 500 observações, para um método que não seja raw | Gera preço normalmente, com flag visível |
| `extreme_probability` | Probabilidade operacional `>= 90%` naquele lado | Gera preço normalmente, com flag visível |
| `restricted` | ATP `aces_player` em Grass (ver seção 5) | Gera preço normalmente, com flag e motivo visíveis |

**Achado relevante sobre `cold_start`**: na base de 1.036.994 linhas produzidas pela Fase 6,
**nenhuma** tem `sample_bucket_career == "cold_start"` (distribuição real:
`large_50_plus`=769.766, `medium_10_49`=198.537, `small_1_9`=68.691, `cold_start`=0). Isso não
é uma falha desta fase: os modelos de taxa da Fase 4 (`src/baselines/rate_models.py`) já
exigem pelo menos uma partida anterior do jogador para gerar qualquer `lambda` previsto — um
jogador sem nenhum histórico simplesmente não recebe uma linha na Fase 6, então nunca chega até
aqui. O mecanismo "cold start não gera odd justa" foi implementado e testado (`fl.cold_start_flag`
+ `test_cold_start_rows_get_no_fair_odds_in_pipeline`, com dados sintéticos) e funcionará
corretamente caso esse caso apareça em dados futuros; ele simplesmente não ocorre nos dados
históricos atuais, o que é reportado aqui em vez de omitido.

`calibrator_insufficient_sample` também é zero na base atual pelo mesmo motivo estrutural: o
menor treino de calibrador observado (fold_2025 com apenas `fold_2024` como treino) já tem
milhares de linhas por mercado/tour, muito acima do limiar de 500 — mas a flag existe e foi
testada para o caso em que isso mude.

---

## 10. Monotonicidade (item 7)

Verificamos, para cada `(tour, market, fold, surface, match_id, player_id)` com pelo menos 2
linhas, se a probabilidade de Over cai estritamente conforme a linha sobe (o que implica a odd
justa de Over subindo, e o inverso para Under, por construção — `under = 1 - over`).

**Resultado sobre dados reais do pipeline: 100% dos 77.806 grupos verificados são monotônicos**,
em todos os 6 mercado×tour (ver `data/outputs/phase7/verificacao_monotonicidade_resumo.csv`).
Isso já era esperado: a Fase 6 gera a grade de linhas a partir de uma única distribuição de
contagem por contexto (Poisson/NegBin, monotônica por construção), e tanto Platt scaling
quanto isotonic regression (Fase 6.1) são funções monótonas não decrescentes da probabilidade
bruta — logo preservam a ordem entre linhas do mesmo contexto. Testes sintéticos adicionais
(`TestLineMonotonicity` em `tests/test_pricing.py`) cobrem o caso isoladamente.

---

## 11. Exemplos reais do pipeline

Todos os números abaixo vêm de `data/outputs/phase7/precos_por_linha.parquet` e
`odds_minimas_por_edge.parquet` — nenhum valor foi inventado.

### Exemplo 1 — ATP aces_player, Hard, sem calibração (fold_2024, sem período anterior)
Partida `ATP:2024-0336:271`, jogador `ATP-200325`.

| Linha | Lado | Prob. operacional | Odd justa |
|---:|---|---:|---:|
| 8,5 | Over | 23,26% | 4,30 |
| 8,5 | Under | 76,74% | 1,30 |
| 12,5 | Over | 9,80% | 10,20 |
| 12,5 | Under | 90,20% (`extreme_probability`) | 1,11 |

`method_selected = raw_sem_periodo_anterior` — fold_2024 nunca é calibrado (Fase 6.1, regra
anti-leakage), então a probabilidade operacional aqui é a bruta da Fase 6.

### Exemplo 2 — ATP aces_player, Hard, com calibração Platt (fold_2025)
Partida `ATP:2025-0301:360`, jogador `ATP-210460`, linha 8,5, Over.

- `raw_probability` = 26,12%
- `calibrated_probability` (Platt) = 29,72%
- **Probabilidade operacional: 29,72%**
- **Odd justa: 3,36**

Odd mínima:
- edge 2% → 3,61
- edge 3% → 3,74
- edge 5% → 4,04
- edge 7,5% → 4,50
- edge 10% → 5,07

Este exemplo mostra o efeito prático da Fase 6.1: o modelo era sistematicamente
subconfiante nessa faixa, e a calibração eleva a probabilidade (e reduz a odd justa) em
relação ao valor bruto.

### Exemplo 3 — WTA aces_player, Hard, com calibração Isotonic (fold_2025)
Partida `WTA:2025-1050:270`, jogadora `WTA-210722`, linha 2,5, Over.

- `raw_probability` = 50,49%
- `calibrated_probability` (Isotonic) = 62,98%
- **Probabilidade operacional: 62,98%**
- **Odd justa: 1,59**

Odd mínima:
- edge 2% → 1,64
- edge 3% → 1,67
- edge 5% → 1,72
- edge 7,5% → 1,80
- edge 10% → 1,89

(Este exemplo reproduz, com dados reais do pipeline, praticamente os mesmos números do
exemplo ilustrativo da própria instrução da Fase 7 — usado como teste de regressão.)

### Exemplo 4 — ATP total_aces_match, com calibração Platt (fold_2025)
Partida `ATP:2025-0301:360`, linha 18,5, Over.

- `raw_probability` = 35,38%
- `calibrated_probability` (Platt) = 42,55%
- **Probabilidade operacional: 42,55%**
- **Odd justa: 2,35**

### Exemplo 5 — ATP double_faults_player, sem recalibração (fold_2026, PRONTO PARA ODDS)
Partida `ATP:2026-0339:347`, jogador `ATP-206909`, linha 1,5.

| Lado | Prob. operacional | Odd justa |
|---|---:|---:|
| Over | 28,55% | 3,50 |
| Under | 71,45% | 1,40 |

`method_selected = raw` — a Fase 6.1 não encontrou ganho consistente de calibração para
double faults em nenhum tour, então a probabilidade bruta é preservada como operacional
(nunca recalibrada "por obrigação").

### Exemplo 6 — ATP aces_player em Grass, RESTRICTED (fold_2025)
Partida `ATP:2025-0321:359`, jogador `ATP-111460`, linha 8,5, Over.

- `raw_probability` = 70,17%
- `calibrated_probability` (Platt) = 85,11%
- **Probabilidade operacional: 85,11%**
- **Odd justa: 1,17**
- `restricted = True` — motivo: "ECE piora de 0,031 para 0,039 após calibração Platt
  especificamente em Grass (n=7.966 no fold avaliado); Hard/Clay (~90% da amostra) sem
  ressalva."

Este é o caso mais importante para uso operacional cauteloso: o salto de 70% (bruto) para 85%
(calibrado) é grande, e justamente neste segmento (ATP/`aces_player`/Grass) a Fase 6.1
documentou que a calibração piora — não melhora — a concordância entre probabilidade prevista
e frequência real. A flag `restricted` existe exatamente para sinalizar isso antes de qualquer
uso do preço.

---

## 12. Saídas

Todas em `data/outputs/phase7/`:

- `precos_por_linha.parquet` (2.073.988 linhas — 1.036.994 linhas × 2 lados): tabela mestre com
  contexto, `raw_probability`, `calibrated_probability`, `operational_probability`, `fair_odds`
  e todas as flags de qualidade/restrição por linha/lado.
- `odds_minimas_por_edge.parquet` (10.369.940 linhas — master × 5 cenários de edge): odd mínima
  aceitável para cada um dos 5 níveis de edge testados.
- `verificacao_monotonicidade.csv` / `_resumo.csv`: verificação de monotonicidade por grupo e
  resumo agregado por mercado/tour.
- `resumo_flags.csv`: contagem de cada flag por mercado/tour/lado.
- `exemplos_precos.csv` / `exemplos_odds_minimas_por_edge.csv`: amostra de ~10 grupos
  (partida/jogador) com todas as linhas, para inspeção manual.
- `phase7_summary.json`: resumo agregado (contagens, classificação herdada da Fase 6.1,
  cenários de edge, resumo de monotonicidade, contagem de flags).

---

## 13. Limitações e o que fica para depois

- O edge mínimo operacional **não foi escolhido** nesta fase (item 10 da instrução) — as cinco
  faixas foram geradas para comparação futura com dados reais de odds/paper trading.
- Nenhuma odd real foi consultada (Betano ou qualquer outra casa) — `implied_probability` e
  `edge` foram validados apenas com exemplos unitários sintéticos.
- Nenhum cálculo de stake, banca ou gestão de risco foi feito.
- Nenhuma interface foi criada.
- A restrição de ATP `aces_player`/Grass é herdada tal como documentada na Fase 6.1 — esta
  fase não reavaliou a calibração em si, apenas propagou a flag e o motivo.

---

**Parando aqui conforme instrução. Não foram consultadas casas de apostas, não houve scraping,
não houve cálculo de stake, nenhuma interface foi criada. Aguardando nova instrução.**
