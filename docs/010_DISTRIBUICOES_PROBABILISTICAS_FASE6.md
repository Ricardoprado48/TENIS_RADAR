# Fase 6 — Distribuições Probabilísticas e Calibração

## 0. Escopo desta fase

Esta fase le exclusivamente:

- `data/outputs/phase4/predictions/*.parquet` — previsões pontuais (`lambda`) já calculadas na Fase 4, point-in-time, fora da amostra, por jogador/partida/fold;
- `data/outputs/phase4/metrics/count_distribution_metrics.csv` — parâmetro de dispersão da Negative Binomial (`negbin_r`) e média/variância do alvo real, já ajustados na Fase 4 usando **somente o fold de treino**;
- `data/outputs/phase5/classificacao_mercados.csv` — a "melhor abordagem" (variante × janela) já determinada objetivamente na Fase 5 para cada mercado/tour.

**Não foi treinado nenhum modelo novo.** Toda a Fase 6 consiste em transformar a previsão pontual + a dispersão já existentes em uma **distribuição de probabilidade avaliada em várias linhas `.5`**, em vez do único limiar (mediana do treino) que a Fase 4 usava para diagnosticar overdispersion. Não foram lidos `data/processed/` nem `data/raw/` em nenhum cálculo de modelo ou métrica (uma única leitura pontual de `data/processed/{tour}/players.parquet` foi feita só para colocar nomes de jogadores nos 6 exemplos da seção 12 — não influencia nenhum número).

Mercados desta fase: `aces_player`, `total_aces_match`, `double_faults_player` (ATP e WTA separados). Não foram calculadas odds, não foi coletada nenhuma casa de apostas, não foi criada interface, e a Fase 7 não foi iniciada.

Código: `src/probabilistic/` (`config.py`, `selection.py`, `distributions.py`, `dependency.py`, `calibration.py`, `build.py`) + `scripts/build_probabilistic_phase6.py`. Testes: `tests/test_probabilistic.py` (14 testes, ver seção 13). Saídas: `data/outputs/phase6/` (listadas na seção 14).

---

## 1. Objetivo e metodologia

Para cada jogador/partida fora da amostra, a previsão pontual `lambda` (já calculada na Fase 4) é usada como a **média** de duas distribuições candidatas:

- **Poisson(lambda)** — baseline comparativo, assume variância = média;
- **Negative Binomial(lambda, r)** — priorizada, conforme evidência da Fase 5 (100% dos folds com overdispersion, 2×–5,5× a variância esperada pelo Poisson). O parâmetro `r` **não é reajustado aqui**: é lido diretamente de `count_distribution_metrics.csv`, onde já foi estimado por método dos momentos usando somente dados de treino.

Uma grade de linhas `.5` é gerada automaticamente por mercado/tour/fold a partir dos quantis 1%–99% da própria distribuição ajustada no treino (`train_mean` + `negbin_r`, também de `count_distribution_metrics.csv`) — nunca de limites fixados a priori, e nunca do fold de teste. Para cada linha, `P(Over) = sf(linha)` e `P(Under) = 1 - P(Over)` (linhas `.5` nunca têm push, verificado no item 13).

---

## 2. Configuração por mercado (item 2)

Configuração "base" (Hard/Clay): a melhor abordagem já identificada na Fase 5.

| Tour | Mercado | Variante × janela (base) |
|---|---|---|
| ATP | aces_player | matchup × surface_career |
| ATP | double_faults_player | isolated × last50 |
| ATP | total_aces_match | matchup × surface_career |
| WTA | aces_player | matchup × last50 |
| WTA | double_faults_player | isolated × last50 |
| WTA | total_aces_match | matchup × last50 |

`double_faults_player` nunca teve uma variante Serve×Return na Fase 4 (a Fase 3 não modelou double faults como função do devolvedor) — usa sempre `isolated`, em Grass inclusive. Nenhuma configuração foi forçada a ser igual entre ATP/WTA nem entre superfícies; cada uma foi decidida separadamente pelos critérios abaixo.

## 3. Grass — sacador isolado vs. Serve × Return (item 3)

Comparação feita **só com dados de Grass**, na mesma janela já escolhida para o tour (para isolar a pergunta "o devolvedor ajuda em Grass?" da pergunta "qual janela usar?"), por MAE fora da amostra:

| Tour | Mercado | MAE isolated | MAE matchup | n (Grass) | Vencedor |
|---|---|---:|---:|---:|---|
| ATP | aces_player | **4,118** | 4,163 | 1.178 | isolated |
| ATP | total_aces_match | 6,910 | **6,855** | 1.120 | matchup |
| WTA | aces_player | **1,934** | 1,940 | 1.197 | isolated |
| WTA | total_aces_match | 3,123 | **3,088** | 1.190 | matchup |

Achado consistente: em **aces por jogador**, o modelo só-sacador vence em Grass nos dois tours — confirma a Fase 5 ("efeito do devolvedor pequeno/inconsistente em Grass"). Em **total de aces** (soma dos dois jogadores), matchup continua vencendo em Grass — o ajuste pelo devolvedor ajuda a estimar a *soma* melhor mesmo quando não ajuda a estimar cada jogador individualmente, provavelmente porque erros de sinal oposto nos dois jogadores se cancelam parcialmente na soma. A decisão final usada no restante da fase: **aces_player usa `isolated` em Grass e `matchup` em Hard/Clay, nos dois tours; total_aces_match usa `matchup` em todas as superfícies.**

---

## 4. Total de aces: soma independente vs. ajuste empírico (item 4)

**Correlação residual** entre os aces do jogador e do adversário na mesma partida (diagnóstico, não usado para ajustar nada):

| Tour | Correlação | n (linhas jogador-partida) |
|---|---:|---:|
| ATP | **0,30 – 0,33** (por fold) | ~13.800 |
| WTA | **0,14 – 0,17** (por fold) | ~12.900 |

Existe correlação positiva real e não-trivial, mais forte no ATP que no WTA — plausivelmente porque partidas com mais pontos de saque (jogos mais longos, superfícies mais rápidas) elevam aces dos dois jogadores ao mesmo tempo.

**Comparação de calibração** (Brier Score médio, linhas geradas automaticamente, dados de Hard/Clay — Grass já tratada separadamente na seção 3):

| Tour | Brier (independência) | Brier (empírico) | Ganho relativo do empírico |
|---|---:|---:|---:|
| ATP | 0,12396 | 0,12447 | **−0,4%** |
| WTA | 0,10826 | 0,10891 | **−0,6%** |

Apesar da correlação residual real, o ajuste empírico direto **não** melhora a calibração fora da amostra (na verdade piora ligeiramente) — abaixo do limiar de 3% usado na Fase 5 para justificar complexidade adicional (`src/selection/config.py MIN_MEAN_DELTA_REL`, reaproveitado aqui). **Decisão: usar a soma das distribuições individuais assumindo independência (abordagem mais simples)** para o total de aces em Hard/Clay, nos dois tours — item 4 pede explicitamente "usar a abordagem mais simples se a dependência não trouxer ganho material", e é exatamente o que os dados mostram.

---

## 5. Calibração geral (item 6)

Negative Binomial, todas as linhas, todos os folds:

| Tour | Mercado | n | Brier | Log Loss | ECE |
|---|---|---:|---:|---:|---:|
| ATP | aces_player | 187.740 | 0,1068 | 0,338 | **0,0348** |
| ATP | double_faults_player | 162.672 | 0,0962 | 0,309 | **0,0096** |
| ATP | total_aces_match | 184.996 | 0,1319 | 0,407 | **0,0368** |
| WTA | aces_player | 163.618 | 0,0935 | 0,297 | **0,0302** |
| WTA | double_faults_player | 163.696 | 0,1016 | 0,324 | **0,0150** |
| WTA | total_aces_match | 174.272 | 0,1114 | 0,349 | **0,0337** |

`double_faults_player` tem ECE 2–3× menor que os dois mercados de aces, nos dois tours — está claramente melhor calibrado (ver seção 6).

## 6. Calibração por faixa de probabilidade (item 7)

Curva de confiabilidade (probabilidade prevista vs. frequência real observada), ATP mostrado como exemplo — o mesmo padrão se repete no WTA:

| Faixa prevista | aces_player (previsto → real) | total_aces_match (previsto → real) | double_faults_player (previsto → real) |
|---|---|---|---|
| 0–10% | 3,8% → 2,6% | 4,2% → 3,3% | 2,7% → 2,6% |
| 30–40% | 34,7% → 42,6% | 34,7% → 42,3% | 35,0% → 35,6% |
| 50–60% | 54,3% → **72,1%** | 54,2% → **72,0%** | 54,9% → 58,2% |
| 70–80% | 74,0% → 89,5% | 73,1% → 84,8% | 75,4% → 79,7% |
| 90–100% | 91,5% → 100% (n=1) | — (sem dado) | 92,5% → 94,7% |

**Achado central:** `aces_player` e `total_aces_match` estão bem calibrados na faixa baixa (0–30%), mas ficam **sistematicamente subconfiantes** a partir de ~40% — quando o modelo diz "54% de chance de Over", a frequência real fica perto de 72%. `double_faults_player` não tem esse padrão: a probabilidade prevista acompanha a frequência real de perto em toda a faixa (maior desvio ~4 pontos percentuais, contra ~18 pontos nos mercados de aces). Isso é consistente com o ECE da seção 5 e é o achado mais importante desta fase para decidir prontidão (seção 12).

## 7. Calibração por dificuldade da linha (item 7)

Linhas classificadas por z-score `(linha − lambda) / desvio_padrão_do_modelo` em `muito_abaixo_da_média` / `próxima_da_média` / `muito_acima_da_média` (buckets fixados a priori em `src/probabilistic/config.py`). Nos três mercados, o Brier Score é 3–5× pior nas linhas "próximas da média" (onde o evento é genuinamente incerto, perto de 50/50) do que nas linhas "muito acima" (onde Over é quase certo e o modelo acerta por construção). Não há região em que o modelo colapse (nenhum bucket com Brier > 0,21) — a dificuldade extra é a esperada de qualquer previsão binária perto do limiar de decisão, não uma falha de calibração localizada.

---

## 8. Robustez (item 8)

**Por fold** — Negative Binomial bate Poisson em **100% das 18 combinações** tour×mercado×fold (`data/outputs/phase6/poisson_vs_negbin_por_fold.csv`). Brier estável entre 2024/2025/2026(parcial) em todos os mercados, sem deterioração no fold de 2026 (parcial).

**Por superfície** — Brier e ECE sistematicamente piores em Grass em todos os 6 combos tour×mercado (`calibracao_por_superficie.csv`), confirmando a amostra menor e mais instável já identificada na Fase 5. Exemplo: ATP total_aces_match — Brier 0,055 (Clay) vs. 0,164 (Hard) vs. **0,206 (Grass)**.

**Negative Binomial vs. Poisson por superfície**: NB vence em 16 das 18 combinações; empata/perde por margem desprezível em 2 (ATP double_faults_player em Grass: 0,1105 vs 0,1109; WTA aces_player em Grass: 0,1066 vs 0,1087) — coerente com Grass ter a amostra mais fraca para estimar overdispersion.

**Por tamanho de histórico** (`prior_matches_career`, buckets: `small_1_9`, `medium_10_49`, `large_50_plus`) — ver seção 11: mais histórico **não** implica automaticamente melhor Brier.

---

## 9. Negative Binomial vs. Poisson — visão consolidada (item 6 do enunciado)

| Tour | Mercado | Brier Poisson | Brier NegBin | % de linhas em que NegBin vence individualmente |
|---|---|---:|---:|---:|
| ATP | aces_player | 0,1091 | **0,1068** | 15,1% |
| ATP | double_faults_player | 0,0975 | **0,0962** | 15,1% |
| ATP | total_aces_match | 0,1396 | **0,1319** | 18,6% |
| WTA | aces_player | 0,0940 | **0,0935** | 14,7% |
| WTA | double_faults_player | 0,1024 | **0,1016** | 15,1% |
| WTA | total_aces_match | 0,1125 | **0,1114** | 16,8% |

**Negative Binomial vence em média (Brier agregado) em todos os 6 combos, mas vence individualmente por linha só em ~15–19% dos casos.** Não é uma contradição: quebrando por dificuldade da linha (seção 7), o Poisson vence muitas vezes por margem minúscula nas linhas onde os dois modelos concordam (perto da cauda, onde a variância extra do NegBin quase não muda a probabilidade), mas quando o Poisson erra — porque subestima a variância real — ele erra por muito mais, e o NegBin evita esse erro grande. O resultado líquido é NegBin sistematicamente melhor no agregado, apesar de vencer individualmente uma minoria das vezes.

---

## 10. Total de aces — grade de linhas e verificação Over+Under=1 (item 5)

Para cada linha `.5` gerada, `P(Over) + P(Under) = 1` por construção (`P(Under) = 1 - sf(linha)`), verificado numericamente para todos os mercados/tours/folds via `tests.test_probabilistic.TestLineProbabilitiesBounds.test_over_plus_under_equals_one_no_push` (tolerância 1e-9). Monotonicidade (`P(Over)` decrescente conforme a linha aumenta) verificada em `TestMonotonicity` para Poisson e Negative Binomial.

---

## 11. Incerteza e qualidade da amostra (item 9/10)

Cada linha/jogador/partida no arquivo de saída carrega `sample_bucket_career` (mesmos buckets já definidos na Fase 4: `cold_start`, `small_1_9`, `medium_10_49`, `large_50_plus`) e `prior_matches_career` — **sem alterar nenhuma probabilidade com base nesses indicadores nesta fase**, conforme pedido.

**Achado sobre cold start**: o bucket `cold_start` (zero partidas anteriores) **não aparece em nenhuma linha do arquivo de saída** — jogadores sem histórico não têm `lambda` calculável (features com `NaN`), então essas linhas são descartadas antes de qualquer probabilidade ser gerada. Isso é uma limitação real e documentada (item 10: "não ocultar baixa qualidade com preenchimento silencioso") — o pipeline atual simplesmente **não produz probabilidade nenhuma** para estreias absolutas, em vez de inventar um valor.

**Achado contraintuitivo**: mais histórico não significa automaticamente melhor calibração. Exemplo, ATP aces_player: Brier 0,0933 (`small_1_9`, n=10.094) vs. 0,1089 (`large_50_plus`, n=143.346). Isso não deve ser lido como "menos dados é melhor" — o bucket `large_50_plus` concentra jogadores de circuito estabelecido, que jogam mais partidas justamente por serem mais consistentes/fortes, e a distribuição de linhas testadas para eles cobre uma faixa mais larga (mais oportunidades de erro nas caudas). O ponto prático: tamanho de histórico sozinho não é um proxy direto e confiável de "confiança da previsão" — reforça a necessidade de indicadores objetivos e explícitos (como já feito aqui) em vez de assumir a relação.

---

## 12. Exemplos out-of-sample completos (item 13)

Seis exemplos reais, extraídos de `data/outputs/phase6/previsoes_por_linha.parquet` (Negative Binomial), cobrindo os dois tours e as três superfícies:

```
Learner Tien vs Tomas Machac (ATP, Hard, fold_2025)
Aces — Learner Tien
expectativa: 6,33 (histórico: 21 partidas)

Over 5,5: 47%
Over 6,5: 39%
Over 7,5: 32%
Over 8,5: 27%
Over 9,5: 22%

resultado real: 3 aces (o modelo superestimou)
```

```
Chun Hsin Tseng vs Christopher O'Connell (ATP, Hard, fold_2025)
Aces — Chun Hsin Tseng
expectativa: 4,28 (histórico: 40 partidas)

Over 5,5: 29%
Over 6,5: 22%
Over 7,5: 17%
Over 8,5: 13%
Over 9,5: 9%

resultado real: 0 aces (Under confirmado)
```

```
Iga Swiatek vs Danielle Collins (WTA, Clay, fold_2025)
Aces — Iga Swiatek
expectativa: 2,76 (histórico: 267 partidas)

Over 0,5: 79%
Over 1,5: 58%
Over 2,5: 42%
Over 3,5: 30%
Over 4,5: 21%

resultado real: 1 ace (Under confirmado)
```

```
Arianne Hartono vs Elisabetta Cocciaretto (WTA, Grass, fold_2025)
Aces — Arianne Hartono
expectativa: 2,00 (histórico: 19 partidas)

Over 0,5: 71%
Over 1,5: 48%
Over 2,5: 31%
Over 3,5: 19%
Over 4,5: 12%

resultado real: 1 ace (consistente com a região de maior incerteza, 0,5–1,5)
```

```
Qinwen Zheng vs Donna Vekic (WTA, Hard, fold_2024)
Aces — Qinwen Zheng
expectativa: 5,14 (histórico: 143 partidas)

Over 0,5: 89%
Over 1,5: 76%
Over 2,5: 64%
Over 3,5: 53%
Over 4,5: 44%
Over 5,5: 36%
Over 6,5: 29%
Over 7,5: 24%
Over 8,5: 19%
Over 9,5: 16%

resultado real: 10 aces (Over em todas as linhas — exatamente o padrão de
subconfiança da faixa 40-70% discutido na seção 6: o modelo deu só 44% para
Over 4,5, e o resultado real ficou bem acima de todas as linhas testadas)
```

```
Anastasia Tikhonova vs Despina Papamichail (WTA, Clay, fold_2026 parcial)
Aces — Anastasia Tikhonova
expectativa: 1,11 (histórico: 6 partidas — small_1_9)

Over 0,5: 56%
Over 1,5: 29%
Over 2,5: 14%
Over 3,5: 7%

resultado real: 2 aces (Over 1,5 confirmado; histórico pequeno — usar com cautela)
```

---

## 13. Validação automatizada (item 11)

`tests/test_probabilistic.py`, 14 testes — todos verificados junto com a suíte completa (85/85 testes, incluindo os 71 das Fases 1–4):

- probabilidades sempre em `[0, 1]` (Poisson e Negative Binomial);
- `P(Over) + P(Under) = 1` para linhas `.5` (sem push), tolerância 1e-9;
- monotonicidade: `P(Over)` nunca aumenta quando a linha aumenta;
- grade de linhas: sempre ordenada, sempre termina em `.5`, sempre dentro do teto de segurança (`MAX_LINES_PER_GROUP`), grade Negative Binomial nunca mais estreita que a Poisson equivalente (cauda mais pesada);
- buckets de dificuldade de linha correspondem à região esperada (muito abaixo / próxima / muito acima da média);
- casos extremos: `lambda = 0` (probabilidade de Over exatamente 0), `lambda` muito grande (probabilidade de Over ≈ 1, sem overflow), dispersão `r` muito pequena (sem `NaN`/`inf`);
- soma independente de duas variáveis preserva média (soma dos lambdas) e variância (soma das variâncias) exatamente, por construção;
- quando não há overdispersion (`r=None`), a soma independente retorna `NaN` corretamente em vez de um `r` inválido;
- nenhum dado futuro: os folds usados pela Fase 6 são literalmente os mesmos objetos de `src/baselines/config.py FOLDS` (nunca redefinidos), com teste de regressão que garante que os intervalos de teste permanecem cronológicos e sem sobreposição.

---

## 14. Saídas geradas (item 12)

Todas em `data/outputs/phase6/`:

- `previsoes_por_linha.parquet` — tabela completa por linha/jogador/partida (1.036.994 linhas): contexto, `lambda`, `negbin_r`, linha, resultado real, `P(Over)`/`P(Under)` Poisson e Negative Binomial, bucket de dificuldade de linha, bucket de histórico;
- `configuracao_por_mercado.csv` — variante/janela escolhida por mercado, base e Grass, com o MAE de cada lado da comparação;
- `calibracao_por_mercado.csv`, `calibracao_por_fold.csv`, `calibracao_por_superficie.csv`, `calibracao_por_historico.csv`, `calibracao_por_dificuldade_linha.csv` — Brier/Log Loss/ECE segmentados;
- `reliability_curve.csv` — curva de confiabilidade por bucket de probabilidade prevista;
- `poisson_vs_negbin.csv`, `poisson_vs_negbin_por_fold.csv`, `poisson_vs_negbin_por_superficie.csv` — comparação direta;
- `total_aces_correlacao_residual.csv`, `total_aces_independencia_vs_empirico.csv`, `total_aces_decisao_dependencia.csv` — item 4;
- `exemplos_previsoes.csv` — amostra bruta de partidas para inspeção;
- `phase6_summary.json` — resumo executável.

---

## 15. Respostas às perguntas obrigatórias

**1. Negative Binomial continua superior ao Poisson quando avaliamos probabilidades de linhas?**
Sim, no agregado (Brier menor em 6/6 combinações tour×mercado, e em 18/18 combinações por fold), embora vença observação-a-observação só em ~15–19% dos casos (seção 9) — a vitória agregada vem de evitar erros grandes na cauda, não de vencer na maioria das linhas.

**2. As probabilidades de aces estão bem calibradas?**
Parcialmente. Bem calibradas abaixo de ~30% de probabilidade prevista; **sistematicamente subconfiantes entre ~40–80%** (previsão de 54% correspondendo a frequência real de ~72%, seção 6). `total_aces_match` tem o mesmo padrão. Isso é uma limitação real que deveria ser corrigida (ex.: recalibração isotônica) antes de qualquer uso operacional — não foi feita aqui, por estar fora do escopo desta fase.

**3. Em quais faixas de probabilidade o modelo é mais confiável?**
0–30% (erro de calibração pequeno, poucos pontos percentuais) nos três mercados. Acima de 40%, `double_faults_player` continua confiável; os dois mercados de aces não.

**4. Grass deve usar Serve × Return ou somente perfil do sacador?**
Depende do mercado, não é uma resposta única: `aces_player` deve usar **somente o sacador** em Grass (isolated vence em MAE nos dois tours); `total_aces_match` deve continuar usando **Serve × Return** (matchup vence em MAE nos dois tours) — ver seção 3.

**5. Total de aces pode ser obtido pela soma independente ou precisa de ajuste?**
Soma independente é suficiente e recomendada (mais simples, calibração igual ou ligeiramente melhor que o ajuste empírico direto, seção 4), apesar de existir correlação residual real (~0,30 ATP, ~0,15 WTA) entre os aces dos dois jogadores — a correlação existe mas não é grande o suficiente para justificar o ajuste extra nas linhas testadas.

**6. Double faults possui calibração suficiente para continuar?**
Sim — é o mercado com melhor calibração dos três (ECE 0,010–0,015, contra 0,030–0,037 dos mercados de aces), sem o padrão de subconfiança visto em aces (seção 5/6).

**7. Existem diferenças relevantes ATP × WTA?**
Sim, duas: (a) WTA calibra melhor que ATP em aces_player e total_aces_match (Brier ~15–20% menor); (b) a correlação residual entre aces dos dois jogadores é bem mais forte no ATP (~0,30–0,33) que no WTA (~0,14–0,17) — mesmo assim, em ambos os tours a soma independente já é suficiente (pergunta 5).

**8. Quais mercados estão prontos para produzir probabilidades em partidas futuras?**
`double_faults_player` é o mais pronto (melhor calibração, sem viés sistemático por faixa). `aces_player` e `total_aces_match` têm previsibilidade real (Brier bom, NegBin > Poisson, robustez por fold) mas precisam de correção de calibração na faixa 40–80% antes de uso operacional — a distribuição e a robustez estão prontas, a calibração ainda não.

---

## 16. Limitações

1. Cold start (zero histórico) não produz nenhuma probabilidade — não é um preenchimento silencioso, mas também não é uma solução (não avaliado nesta fase).
2. A subconfiança de aces_player/total_aces_match na faixa 40–80% não foi corrigida (recalibração isotônica/Platt seria o próximo passo natural, fora do escopo).
3. Grass segue com a amostra mais fraca dos três (n ~1.100–1.200 por mercado/tour/fold), tornando a escolha isolated-vs-matchup em Grass mais sensível a ruído do que em Hard/Clay.
4. A comparação de independência (item 4) usou apenas dados de Hard/Clay, já que a configuração de Grass do próprio total_aces_match coincidiu com a base — não foi testada uma grade de linhas específica de Grass para essa comparação.
5. `r` (Negative Binomial) é constante por fold/tour/mercado/variante — não varia por superfície nem por jogador; overdispersion pode ser heterogênea dentro do fold (não investigado aqui).

---

## 17. Conclusão

A infraestrutura de distribuição de probabilidade (Negative Binomial priorizada, Poisson como baseline, linhas `.5` geradas automaticamente, calibração medida por fold/superfície/histórico/faixa de probabilidade) está implementada, testada (85/85 testes) e documentada para os três mercados selecionados na Fase 5. `double_faults_player` está pronto para a próxima etapa sem ressalvas. `aces_player` e `total_aces_match` têm modelo e robustez adequados, mas calibração ainda insuficiente na faixa de probabilidade média-alta — a decisão de avançar ou primeiro corrigir a calibração é uma escolha de produto, não uma questão técnica em aberto.

**Parando aqui conforme instrução. Fase 7 (previsões de partidas atuais) não foi iniciada.**
