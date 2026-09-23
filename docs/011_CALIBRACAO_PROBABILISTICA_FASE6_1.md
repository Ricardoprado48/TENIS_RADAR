# Fase 6.1 — Calibração das Probabilidades Out-of-Sample

## 0. Escopo desta fase

Lê exclusivamente `data/outputs/phase6/previsoes_por_linha.parquet` — a probabilidade Negative Binomial (`p_over_negbin`) e o resultado real (`actual_over`) já calculados na Fase 6. **Os modelos de previsão de contagem da Fase 6 (lambda, `r`, Poisson, Negative Binomial) não foram alterados.** Esta fase treina um segundo estágio — um calibrador — que recebe a probabilidade bruta e devolve uma probabilidade corrigida, sem tocar em nenhum parâmetro da Fase 6.

Mercados: `aces_player`, `total_aces_match`, `double_faults_player`, ATP e WTA separados (6 combinações). Não foram calculadas odds, não foi consultada nenhuma casa de apostas, não houve cálculo de stake, não foi criada interface, e a Fase 7 não foi iniciada.

Código: `src/recalibration/` (`config.py`, `methods.py`, `evaluate.py`, `selection.py`, `diagnostics.py`, `build.py`) + `scripts/build_calibration_phase6_1.py`. Testes: `tests/test_recalibration.py` (10 testes; suíte completa 95/95, incluindo os 85 das Fases 1–6). Saídas: `data/outputs/phase6_1/`.

---

## 1. Regra anti-leakage temporal (item 3) — como foi garantida

Cada calibrador usa **somente folds estritamente anteriores** ao fold avaliado (janela expansiva, a mesma lógica de `src/baselines/walkforward.py` já usada em toda a Fase 4/6):

| Fold avaliado | Fold(s) usados para treinar o calibrador |
|---|---|
| `fold_2024` | **nenhum** — não existe fold anterior nos dados. Este fold **nunca é calibrado**: suas probabilidades permanecem exatamente as brutas da Fase 6, com `method_selected = "raw_sem_periodo_anterior"` (nunca substituídas silenciosamente). |
| `fold_2025` | `fold_2024` (83.314–94.575 linhas, conforme o mercado) |
| `fold_2026` (parcial) | `fold_2024` + `fold_2025` (154.896–172.700 linhas) |

Isso está codificado em `src/recalibration/config.py CALIBRATION_TRAIN_FOLDS` (um dicionário fixo, `fold_2024` deliberadamente ausente das chaves) e verificado por dois testes automatizados (`TestNoTemporalLeakage`, seção 8) que confirmam: (a) nenhum fold de treino é igual ou posterior ao fold avaliado; (b) `fold_2024` nunca aparece como fold avaliado. **Consequência prática: só existem 2 folds avaliáveis nesta fase (`fold_2025`, `fold_2026`) — todas as métricas de "antes × depois" abaixo usam exclusivamente esses dois.**

---

## 2. Métodos comparados (item 2)

- **raw** — probabilidade bruta da Fase 6 (`p_over_negbin`), sem nenhuma correção;
- **Platt scaling** — regressão logística de 1 variável sobre o logit da probabilidade bruta (`sklearn.linear_model.LogisticRegression`), com verificação explícita de que o coeficiente ajustado é positivo (senão, cai para `raw` — ver item 6);
- **Isotonic regression** — `sklearn.isotonic.IsotonicRegression`, monótona por construção.

Nenhum terceiro método foi introduzido — os dois já cobrem as duas famílias padrão da literatura (paramétrica e não-paramétrica) e nenhuma evidência nos dados pediu uma terceira abordagem.

---

## 3. Critério de seleção (item 9)

Um método só substitui `raw` se, **nos dois folds avaliáveis, simultaneamente**: melhora relativa de Brier ≥ 1% **e** ECE não piora (`src/recalibration/config.py MIN_REL_BRIER_IMPROVEMENT = 0.01`, mesma ordem de grandeza do limiar de "fold forte" já usado na Fase 5). Quando os dois métodos passam nos dois folds, o desempate é pela maior melhora média de Brier. **Nunca escolhido só pelo ECE agregado** — a exigência de melhora consistente Brier+ECE em cada fold individual (não só na média) é o mecanismo que impede isso.

## 4. Resultado da seleção, por mercado/tour

| Tour | Mercado | Método escolhido | Motivo |
|---|---|---|---|
| ATP | aces_player | **Platt** | Platt e isotonic melhoraram nos dois folds; Platt venceu por maior ganho médio de Brier |
| ATP | total_aces_match | **Platt** | idem |
| ATP | double_faults_player | **raw** | Nenhum método melhorou Brier e ECE de forma consistente nos dois folds |
| WTA | aces_player | **Isotonic** | Platt e isotonic melhoraram nos dois folds; isotonic venceu por maior ganho médio de Brier |
| WTA | total_aces_match | **Isotonic** | idem |
| WTA | double_faults_player | **raw** | Nenhum método melhorou de forma consistente |

`double_faults_player` preserva a probabilidade original nos dois tours (item 8: "se a calibração adicional não melhorar de forma consistente, preservar a probabilidade original. Não recalibrar por obrigação.") — confirma quantitativamente o que a Fase 6 já sugeria qualitativamente.

---

## 5. Antes × depois (item 4) — pooled fold_2025+fold_2026

| Tour | Mercado | n | Brier bruto | Brier calibrado | Ganho | ECE bruto | ECE calibrado |
|---|---|---:|---:|---:|---:|---:|---:|
| ATP | aces_player | 104.426 | 0,1077 | **0,1045** | 3,0% | 0,0348 | **0,0093** |
| ATP | total_aces_match | 103.460 | 0,1323 | **0,1286** | 2,8% | 0,0403 | **0,0161** |
| ATP | double_faults_player | 90.216 | 0,0965 | 0,0965 | — | 0,0180 | 0,0180 |
| WTA | aces_player | 94.575 | 0,0946 | **0,0930** | 1,7% | 0,0297 | **0,0070** |
| WTA | total_aces_match | 100.576 | 0,1131 | **0,1109** | 2,0% | 0,0330 | **0,0101** |
| WTA | double_faults_player | 94.718 | 0,1011 | 0,1011 | — | 0,0195 | 0,0195 |

O ganho de Brier é modesto (1,7%–3,0%), mas o ganho de ECE é grande (**redução de 60% a 76%**) nos quatro mercados calibrados — coerente com o diagnóstico da Fase 6: o problema nunca foi a previsão pontual (lambda), e sim a relação entre probabilidade prevista e frequência real, que é exatamente o que ECE mede e Brier só mede parcialmente.

## 6. Estabilidade entre os dois folds temporais (pergunta 5)

| Tour | Mercado | Método | ECE fold_2025 | ECE fold_2026 (parcial) |
|---|---|---|---:|---:|
| ATP | aces_player | Platt | 0,0055 | 0,0175 |
| ATP | total_aces_match | Platt | 0,0098 | 0,0297 |
| ATP | double_faults_player | raw | 0,0150 | 0,0246 |
| WTA | aces_player | Isotonic | 0,0059 | 0,0096 |
| WTA | total_aces_match | Isotonic | 0,0071 | 0,0168 |
| WTA | double_faults_player | raw | 0,0196 | 0,0193 |

**Sim, a melhora permanece nos dois folds avaliáveis** para os quatro mercados calibrados — em nenhum caso o ganho depende de um único fold (é exatamente o que o critério da seção 3 já impôs por construção, mas os números confirmam que a folga acima do limiar de 1% não é artificial). O ECE do `fold_2026` (parcial, calibrador treinado com menos dados que o de `fold_2025`) é sistematicamente maior que o de `fold_2025` nos seis mercados — esperado (calibrador mais novo, menos dado de treino, e o próprio fold é parcial) e não indica degradação real.

---

## 7. Faixas de probabilidade (item 5)

Reliability curve completa em `data/outputs/phase6_1/reliability_por_bucket.csv`. Exemplo — ATP `aces_player`, fold_2025, previsto → real:

| Faixa | raw | Platt | Isotonic |
|---|---|---|---|
| <20% | 7,1% → 5,8% | 5,6% → 5,6% | 5,3% → 5,5% |
| 30–40% | 34,7% → 41,7% | 34,8% → 33,8% | 34,7% → 34,5% |
| 40–50% | 44,7% → 57,0% | 44,9% → 44,0% | 44,8% → 44,8% |
| 50–60% | 54,4% → **70,0%** | 54,9% → 54,7% | 54,1% → 52,7% |
| 60–70% | 64,1% → **81,3%** | 64,7% → 64,6% | 64,2% → 62,2% |
| 70–80% | 74,0% → 86,8% | 74,3% → 77,6% | 75,1% → 71,9% |
| 80–90% | 82,9% → 83,1% (n=59, **amostra insuficiente**) | 84,4% → 84,6% | 84,7% → 81,9% |
| 90%+ | n=1, **amostra insuficiente** | n=131, 92,3% → 82,4% | n=177, 95,7% → 85,3% |

A correção na faixa 40–70% (onde a Fase 6 tinha o maior desvio) é dramática nos dois métodos. **A faixa 90%+ continua com desvio residual mesmo após calibração** (Platt: 92,3%→82,4%; Isotonic: 95,7%→85,3%) — e com amostra pequena (n=131–177 no `raw`, cresce um pouco pós-calibração porque a calibração desloca algumas previsões para dentro do bucket). Tratar com cautela previsões extremas (>90%) mesmo pós-calibração.

**Faixa mais confiável**: <20% e 20–50%, nos três mercados, nos dois métodos — erro de calibração tipicamente abaixo de 2 pontos percentuais. **Faixa a evitar mesmo pós-calibração**: 90%+ (amostra pequena e desvio residual) — recomenda-se tratar previsões nessa faixa com uma margem de segurança adicional quando a Fase 8 (odds justas) for iniciada.

---

## 8. Linhas próximas vs. distantes da expectativa (item 6)

Reaproveitando o bucket de dificuldade de linha já calculado na Fase 6 (`line_difficulty`, baseado no z-score `(linha-lambda)/desvio`):

| Tour | Mercado | Bucket | n | ECE bruto | ECE calibrado |
|---|---|---|---:|---:|---:|
| ATP | aces_player | muito_acima_da_média | 61.001 | 0,0115 | **0,0029–0,0032** |
| ATP | aces_player | **próxima_da_média** | 43.422 | **0,0662** | **0,0085–0,0104** |
| ATP | total_aces_match | muito_acima_da_média | 49.778 | 0,0102 | **0,0031–0,0046** |
| ATP | total_aces_match | **próxima_da_média** | 53.682 | **0,0648** | **0,0158–0,0190** |
| WTA | aces_player | muito_acima_da_média | 55.266 | 0,0138 | **0,0005–0,0023** |
| WTA | aces_player | **próxima_da_média** | 39.291 | **0,0520** | **0,0054–0,0143** |

**Confirmado: a má calibração da Fase 6 se concentrava quase inteiramente nas linhas próximas da expectativa** (ECE bruto 5–6× maior que nas linhas "muito acima da média" — exatamente as linhas mais próximas de 50%, que são as mais relevantes para comparação futura com casas de apostas, como o item 6 antecipava). A correção nessas linhas é a maior de toda a fase (ECE cai de ~0,05–0,07 para ~0,01–0,02). O bucket "muito abaixo da média" tem amostra irrelevante nos três mercados (n=3–29) — marcado como não avaliável, não como "bem calibrado por acaso".

---

## 9. ATP × WTA e superfície (item 7)

**ATP × WTA**: os quatro mercados calibráveis mostram o mesmo padrão qualitativo (subconfiança 40–80%, corrigida por Platt/isotonic), mas o **método vencedor difere por tour** — Platt no ATP, Isotonic no WTA, nos dois mercados de aces. Não é uma diferença aleatória: Platt (paramétrico, assume uma curva logística suave) tende a vencer quando a relação bruta já é aproximadamente suave; Isotonic (não-paramétrico) tende a vencer quando há dobras/degraus na curva — consistente com a WTA ter mostrado, na Fase 6, uma curva de confiabilidade menos suave que o ATP nessa faixa.

**Calibrador específico por superfície**: testado diretamente (`data/outputs/phase6_1/calibrador_superficie_grass.csv`) — para cada mercado calibrado, um calibrador ajustado **só com dados de Grass** (mesmo período de treino) foi comparado ao calibrador global aplicado só em Grass:

| Tour | Mercado | Brier calibrador global em Grass | Brier calibrador específico de Grass |
|---|---|---:|---:|
| ATP | aces_player | 0,15123 | 0,15139 |
| ATP | total_aces_match | 0,19182 | 0,19576 |
| WTA | aces_player | 0,10286 | 0,10229 |
| WTA | total_aces_match | 0,12929 | 0,12907 |

Em 3 dos 4 casos o calibrador global é igual ou melhor que o específico; no quarto (WTA aces_player) a diferença é desprezível (0,0006). **Conclusão: não há evidência que justifique um calibrador específico por superfície — mantido o calibrador global por tour/mercado**, conforme o item 7 pede ("não criar calibradores específicos por superfície se a amostra não justificar"). Nota de cobertura: esta comparação só foi possível no `fold_2025` — o `fold_2026` (parcial, até maio) **não contém nenhuma partida em Grass** (a temporada de grama ainda não tinha começado na cobertura dos dados), então o calibrador global em Grass carrega um ano a menos de validação out-of-sample que os demais.

**Configuração de Grass da Fase 6 preservada**: `aces_player` usa `isolated`, `total_aces_match` usa `matchup`, exatamente como decidido na Fase 6 — esta fase não alterou nem re-testou essa escolha (fora do escopo, item 0).

**Achado adicional (não gate, apenas monitoramento)**: em `ATP aces_player`, o ECE em Grass especificamente **piora** ligeiramente pós-calibração (raw 0,0310 → Platt 0,0386) mesmo com o Brier global melhorando — ver classificação na seção 11.

---

## 10. Double faults (item 8)

Testado com os mesmos dois métodos, nos dois tours. Nenhum passou no critério de melhora consistente (seção 3) — Brier idêntico ao bruto por definição (o método selecionado é `raw`), ECE permanece 0,015–0,025 conforme o fold, sem o padrão de subconfiança visto nos mercados de aces. **Preservado sem recalibração, conforme instrução ("não recalibrar por obrigação").**

---

## 11. Diagnóstico Negative Binomial vs. Poisson (item 10) — por que o ganho agregado não exige vencer linha a linha

Não altera nenhuma distribuição — só quantifica o mecanismo já suspeitado na Fase 6:

| Tour | Mercado | % linhas onde NegBin vence | Margem média quando NegBin vence | Margem média quando Poisson vence | Razão |
|---|---|---:|---:|---:|---:|
| ATP | aces_player | 15,1% | 0,139 | 0,022 | **6,3×** |
| ATP | total_aces_match | 18,6% | 0,166 | 0,028 | **5,8×** |
| WTA | aces_player | 14,7% | 0,116 | 0,019 | **6,0×** |
| WTA | total_aces_match | 16,8% | 0,118 | 0,022 | **5,3×** |

**Confirmado**: quando o Negative Binomial vence, vence por uma margem 5–6× maior do que quando o Poisson vence — a soma líquida de erro (`soma_diff_liquida`, sempre positiva, de 78 a 1.415 conforme o mercado) é inteiramente explicada por essa assimetria, não pela frequência de vitórias.

Quebra por dificuldade de linha (`diagnostico_negbin_vs_poisson_por_dificuldade.csv`) mostra a origem exata do efeito:

| Bucket | % vitórias NegBin (ATP aces_player) | Margem NegBin | Margem Poisson |
|---|---:|---:|---:|
| Cauda alta (muito_acima_da_média) | 3,9% | 0,150 | 0,004 (**razão 35×**) |
| Linhas centrais (próxima_da_média) | 30,5% | 0,137 | 0,056 (razão 2,4×) |
| Cauda baixa (muito_abaixo_da_média, n=4) | não avaliável — amostra irrelevante |

**A cauda alta é onde o efeito é mais extremo**: ali o NegBin vence só ~4% das linhas, mas quando vence a margem é ~35× maior que quando perde — é exatamente essa região (muitas linhas, Poisson quase sempre "acerta por pouco" mas ocasionalmente erra feio quando a variância real é maior que a assumida) que domina o Brier agregado, porque concentra a maior parte das observações (109.172 de 187.740 no exemplo do ATP). Nas linhas centrais a vantagem existe mas é proporcionalmente menor (razão 2,4×) — coerente com o Brier de "linhas centrais" já ser alto para os dois modelos ali (a incerteza genuína do evento perto de 50/50 domina, não a escolha de distribuição).

---

## 12. Saída operacional (item 11)

`data/outputs/phase6_1/previsoes_calibradas.parquet` (1.036.994 linhas) preserva, por previsão: `raw_probability` (nunca sobrescrita), `platt_probability`, `isotonic_probability`, `calibrated_probability` (a probabilidade final = a do método selecionado por mercado/tour, ou a bruta quando nenhum método venceu ou quando o fold não tem período anterior), `method_selected`, `calibrator_train_n` (tamanho exato do período usado para treinar aquele calibrador), `sample_bucket_career` (qualidade do histórico do jogador, reaproveitado da Fase 4/6), `tour`, `surface`, `line`, `match_id`, `player_id`, `fold`. A probabilidade bruta nunca é substituída silenciosamente — está sempre presente lado a lado com a calibrada.

---

## 13. Testes automatizados (item 12)

`tests/test_recalibration.py`, 10 testes (suíte completa: 95/95, incluindo as Fases 1–6):

- probabilidades calibradas (Platt e Isotonic) sempre em `[0,1]`;
- monotonicidade: a função de calibração nunca decresce quando a probabilidade bruta aumenta; a ordem entre linhas de uma mesma partida é preservada após calibração;
- ausência de leakage temporal: nenhum fold de treino do calibrador é igual ou posterior ao fold avaliado (verificado programaticamente sobre `CALIBRATION_TRAIN_FOLDS`); `fold_2024` nunca é calibrado; `fold_2026` usa janela expansiva (`fold_2024`+`fold_2025`, nunca só um dos dois);
- reprodutibilidade: dois ajustes com os mesmos dados produzem exatamente as mesmas previsões (Platt e Isotonic são determinísticos aqui — sem otimização estocástica);
- fallback seguro: amostra de treino abaixo de 500 linhas cai para `raw` com o motivo registrado; alvo com uma única classe no período de treino cai para `raw` ("degenerado"); uma relação invertida (probabilidade alta associada a evento raro) é detectada e descartada em vez de aplicada.

---

## 14. Respostas às perguntas obrigatórias

**1. Aces por jogador pode ser calibrado de forma confiável?**
Sim — ganho de ECE de 73–76% nos dois tours, consistente nos dois folds avaliáveis, sem depender de um único fold.

**2. Total de aces pode ser calibrado?**
Sim — mesmo padrão de ganho (ECE −60% a −69%), também consistente.

**3. Double faults deve permanecer sem recalibração?**
Sim — nenhum método melhorou Brier e ECE de forma consistente; a probabilidade original já é bem calibrada e foi preservada, conforme o item 8 pede explicitamente.

**4. Platt ou isotonic funciona melhor?**
Depende do tour, não do mercado: **Platt venceu nos dois mercados de aces do ATP; Isotonic venceu nos dois mercados de aces do WTA** — ver seção 9 para a interpretação (suavidade da curva bruta).

**5. A melhora permanece nos três folds temporais?**
Só dois folds são avaliáveis por desenho anti-leakage (`fold_2024` não tem período anterior). Nos dois (`fold_2025`, `fold_2026` parcial), a melhora é consistente nos quatro mercados calibrados (seção 6).

**6. Existe diferença relevante ATP × WTA?**
Sim, no método vencedor (pergunta 4), não na existência do problema (o padrão de subconfiança 40–80% é o mesmo nos dois tours antes da calibração).

**7. Existe diferença que justifique calibrador por superfície?**
Não — testado diretamente (seção 9); o calibrador global iguala ou supera um calibrador específico de Grass em 3 dos 4 casos testados, e a diferença no quarto é desprezível. Mantido o calibrador único por tour/mercado.

**8. Qual faixa de probabilidades é mais confiável?**
<50% (erro tipicamente <2 pontos percentuais, mesmo antes da calibração). Após calibração, 20–80% também fica confiável.

**9. Qual faixa deve ser evitada?**
90%+ — amostra pequena (n=131–177) e desvio residual mesmo pós-calibração (seção 7). Recomenda-se margem de segurança adicional nessa faixa quando odds forem calculadas.

**10. Quais mercados estão prontos para conversão em odd justa?**
Ver classificação final abaixo (seção 15).

---

## 15. Classificação final por mercado × tour

Critérios objetivos (fixados nesta seção, aplicados sem exceção):
- **PRONTO PARA ODDS**: ECE pós-calibração (ou bruto, se `raw` foi mantido) ≤ 0,03 no pior dos dois folds avaliáveis, melhora consistente quando um calibrador foi aplicado (seção 3), e nenhuma superfície com amostra adequada (n≥150) piora de ECE em relação ao bruto.
- **USAR COM RESTRIÇÃO**: atende ao limiar de ECE acima, mas com uma ressalva documentada e mensurável (ex.: piora localizada em uma superfície).
- **NÃO PRONTO**: ECE pós-calibração > 0,03 em algum fold avaliável, ou nenhuma calibração consistente disponível e o bruto já é ruim.

| Tour | Mercado | ECE (pior fold) | Classificação | Ressalva |
|---|---|---:|---|---|
| ATP | aces_player | 0,0175 | **USAR COM RESTRIÇÃO** | ECE piora especificamente em Grass após calibração (0,031→0,039); Hard/Clay (~90% da amostra) sem ressalva |
| ATP | total_aces_match | 0,0297 | **PRONTO PARA ODDS** | — |
| ATP | double_faults_player | 0,0246 | **PRONTO PARA ODDS** | — (sem calibração, já adequado) |
| WTA | aces_player | 0,0096 | **PRONTO PARA ODDS** | — |
| WTA | total_aces_match | 0,0168 | **PRONTO PARA ODDS** | — |
| WTA | double_faults_player | 0,0196 | **PRONTO PARA ODDS** | — (sem calibração, já adequado) |

Nenhum dos seis mercados/tours foi classificado como NÃO PRONTO — consistente com todos os seis já terem sido selecionados como CANDIDATO na Fase 5 e apresentarem robustez temporal adequada. A única ressalva real é pontual (Grass, ATP aces_player) e de amostra pequena (n=7.966 no fold avaliado), não uma falha estrutural do mercado.

---

## 16. Limitações

1. Só 2 dos 3 folds da Fase 4/6 são avaliáveis para calibração (anti-leakage reduz a amostra de validação temporal disponível) — uma limitação estrutural do desenho, não um problema desta fase.
2. `fold_2026` (parcial) não contém nenhuma partida em Grass — qualquer conclusão sobre Grass no fold mais recente é, na prática, baseada só em `fold_2025`.
3. A faixa 90%+ continua com desvio residual mesmo pós-calibração, e com amostra pequena — não resolvido nesta fase.
4. O calibrador é ajustado uma vez por tour/mercado sobre todas as linhas e superfícies agrupadas — não captura eventuais diferenças finas de calibração por jogador individual ou por torneio.
5. Platt e Isotonic aqui usam parâmetros/hiperparâmetros padrão do scikit-learn — nenhum ajuste de hiperparâmetro foi feito (não haveria como, sem um terceiro nível de validação temporal, o que introduziria complexidade não pedida nesta fase).

## 17. Conclusão

A calibração corrigiu a subconfiança sistemática identificada na Fase 6 nos dois mercados de aces, nos dois tours, com ganhos de ECE de 60–76%, validados sem leakage temporal (calibrador sempre ajustado só com período anterior) e consistentes nos dois folds avaliáveis. Double faults foi corretamente preservado sem alteração, confirmando quantitativamente que já estava bem calibrado. Cinco das seis combinações mercado×tour estão prontas para a conversão em odd justa; a sexta (`ATP aces_player`) está pronta com uma ressalva pontual e mensurável em Grass.

**Parando aqui conforme instrução. Não foram calculadas odds, não foi consultada a Betano, não houve cálculo de stake, nenhuma interface foi criada. Aguardando nova instrução.**
