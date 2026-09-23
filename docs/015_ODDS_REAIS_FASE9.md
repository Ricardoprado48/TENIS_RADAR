# 015 — COLETA PONTUAL DE ODDS E COMPARAÇÃO COM O RADAR (FASE 9)

## 0. Escopo

Esta fase registra uma odd observada em uma casa de apostas (Betano como
primeira casa, arquitetura genérica via campo `bookmaker`) para as linhas já
classificadas pela Fase 8 como `CANDIDATO PARA CONFERIR ODDS`, e a compara
com a probabilidade operacional, a odd justa e a odd mínima aceitável já
calculadas nas Fases 6.1/7/8 — **sem re-treinar, recalibrar, re-selecionar
mercado ou alterar qualquer probabilidade das fases anteriores**.

Código: `src/odds/` (`config.py`, `betano_source.py`, `matching.py`,
`pricing_compare.py`, `storage.py`, `build.py`).
CLI: `scripts/record_odds.py`.
Testes: `tests/test_odds.py` (23 testes; 172/172 no total do projeto — ver
seção 10).
Saídas: `data/outputs/phase9/`.

Não foi calculado stake, não houve aposta automática, nenhuma interface foi
criada, não se avançou para a Fase 10.

---

## 1. Betano: coleta automática (item 1 e 4)

Testamos, sem qualquer contorno de bloqueio (sem login, sem CAPTCHA, sem
proxy, sem reprodução de autenticação privada), exatamente na ordem de
prioridade pedida — HTTP público estruturado → HTML público → browser
automation (indisponível neste ambiente):

| URL | Método | Status | Resultado |
|---|---|---:|---|
| `betano.com/` | `curl` (HTTP puro) | 403 | bloqueio de bot |
| `betano.com/sport/tenis/` | `curl` (HTTP puro) | 403 | bloqueio de bot |
| `betano.com/api/sport/tennis` (endpoint hipotético) | `curl` (HTTP puro) | 403 | bloqueio de bot |
| `betano.com/sport/tenis/` | WebFetch (ferramenta de leitura assistida) | 403 | bloqueio de bot |
| `betano.bet.br/` (domínio BR) | `curl` (HTTP puro) | 403 | bloqueio de bot |
| `betano.bet.br/sport/tenis/` (domínio BR) | `curl` (HTTP puro) | 403 | bloqueio de bot |
| `betano.bet.br/sport/tenis/` (domínio BR) | WebFetch (ferramenta de leitura assistida) | 403 | bloqueio de bot |

**As 7 tentativas retornaram HTTP 403.** Note o contraste com a Fase 8
(docs/013, seção 1.1): lá, a mesma ferramenta de leitura assistida
conseguiu acessar as páginas de `draws`/`schedule` da ATP/WTA Tour mesmo
depois de `curl` puro ser bloqueado — aqui, a Betano bloqueia **também**
esse tipo de acesso, nos dois domínios testados (global e Brasil).

Busca adicional (`WebSearch`, 22/09/2026) não encontrou nenhuma API oficial
pública da Betano. Existem revendedores terceirizados (Apify, OpticOdds,
SharpAPI, Betstamp, OddsPapi, Parse.bot) que vendem acesso a odds da Betano
via API — mas todos fazem scraping por conta própria para produzir esse
dado, ou seja, usá-los seria delegar exatamente o contorno de bloqueio que
a instrução proíbe fazer diretamente. Nenhum foi adotado.

**Conclusão do item 4**: a coleta automática não é estável nem permitida
sem contornar o bloqueio de bot da Betano. A entrada manual é a solução
operacional oficial desta fase (não uma alternativa temporária).
Evidência completa, reproduzível: `data/raw/phase9_betano/source_investigation.{json,md}`
(`src/odds/betano_source.py::run_betano_investigation`).

---

## 2. Bookmaker genérico (item 2)

`bookmaker` é um campo de texto livre em toda a cadeia (`src/odds/config.py`
não define uma lista fechada de casas suportadas) — Betano é usada como
valor padrão da CLI (`--bookmaker`, default `"Betano"`), mas nada no
matching, na comparação ou no armazenamento assume que é a única casa
possível. Registrar uma odd de outra casa exige apenas passar
`--bookmaker "OutraCasa"`.

---

## 3. Entrada manual (item 3)

`scripts/record_odds.py` aceita três formas de entrada:

1. **Flags de linha de comando** (uma observação por chamada):
   ```
   python scripts/record_odds.py --bookmaker Betano --tour ATP \
     --market aces_player --player "Sebastian Baez" --line 7.5 \
     --over-odds 1.85 --under-odds 1.90 \
     --source-url "https://www.betano.bet.br/..."
   ```
2. **JSON** (`--input-json arquivo.json`): lista de objetos com os mesmos campos.
3. **CSV** (`--input-csv arquivo.csv`): mesmo schema, uma linha por observação.

Campos aceitos: `bookmaker`, `tour`, `market`, `player`, `opponent`
(opcional — preenchido automaticamente pelo casamento com o radar quando
não informado), `tournament` (idem), `line`, `over_odds`/`under_odds`
(pelo menos um obrigatório), `collected_at` (opcional — `now()` UTC quando
omitido), `source_method` (default `"manual"`), `source_url` (opcional).

Validação (`src/odds/build.py::validate_entry`) rejeita: `tour` fora de
`{ATP, WTA}`, `market` fora dos 3 mercados aprovados, odd decimal `<= 1.0`,
e a ausência de qualquer odd de lado. Erros não derrubam o lote inteiro —
cada entrada inválida é reportada individualmente (`errors` no resultado),
as demais continuam sendo processadas.

---

## 4. Escopo da consulta (item 5)

`src/odds/config.ALLOWED_MARKETS` reaproveita exatamente
`src.probabilistic.config.MARKETS` (Fase 6): `aces_player`,
`total_aces_match`, `double_faults_player` — os únicos 3 mercados que
existem na base (nenhuma linha de games/sets/tie-break é gerada em nenhuma
fase anterior, então não há o que consultar ali). O radar consultado é
`data/outputs/phase8/precos_por_linha.parquet` — a Fase 8.1 confirmou que a
base atualizada é byte-a-byte idêntica à Fase 8 original (0/1972 linhas
mudaram, docs/014 seção 8), então não há necessidade de duplicar/escolher
entre duas fontes.

---

## 5. Estrutura da odd observada (item 6)

`src/odds/config.OBSERVATION_COLUMNS` — exatamente os 13 campos pedidos:
`bookmaker`, `match_id`, `tour`, `tournament`, `player`, `opponent`,
`market`, `side`, `line`, `decimal_odds`, `collected_at`, `source_method`,
`source_url`. Persistidos em `data/outputs/phase9/odds_observed.parquet`,
sempre em modo *append* (`src/odds/storage.py::append_observations`): cada
chamada lê o parquet existente, concatena as novas linhas e regrava —
nenhuma linha antiga é removida ou alterada. O único caso em que uma nova
linha é descartada é reenvio **exato** (todas as 13 colunas idênticas,
inclusive `collected_at`) — duas leituras da mesma linha em horários
diferentes continuam duas observações distintas, porque `collected_at`
difere (item 11, ver seção 8).

---

## 6. Comparação (item 7)

`src/odds/pricing_compare.py` reaproveita, sem reimplementar, as funções da
Fase 7 (`src/pricing/odds.py`): `implied_probability = 1/decimal_odds`,
`model_edge = p_operacional - implied_probability`, e
`odd_mínima = 1/(p_operacional - e)` para os 5 cenários de edge já
definidos na Fase 7 (2%/3%/5%/7,5%/10%, `src/pricing/config.EDGE_LEVELS`,
não redefinidos aqui). Nenhuma dessas fórmulas foi alterada.

---

## 7. Over/Under e margem da casa (item 8)

Quando `over_odds` e `under_odds` são informados juntos na mesma chamada,
`src/odds/pricing_compare.overround_and_novig` calcula probabilidade
implícita de cada lado, `overround = p_over + p_under - 1` e as
probabilidades no-vig (`p / (p_over + p_under)` por lado) — como colunas
**adicionais** na tabela de comparação. O preço real (`decimal_odds`)
nunca é substituído pela versão no-vig em nenhuma tabela (verificado em
`tests/test_odds.py::TestNoVig.test_real_odds_never_replaced_by_novig`).

Exemplo real do pipeline (linha 5.5 de aces do Baez, ver seção 9): Over
3,95 / Under 1,30 → overround = 2,2%.

---

## 8. Classificação operacional (item 9)

`src/odds/pricing_compare.classify_status` nunca usa os termos proibidos
("aposta garantida"/"certa"/"lucro garantido") — devolve um dos 6 rótulos
objetivos: `ABAIXO_DO_LIMITE`, `ATINGE_EDGE_2`, `ATINGE_EDGE_3`,
`ATINGE_EDGE_5`, `ATINGE_EDGE_7_5`, `ATINGE_EDGE_10` (o maior edge atingido).
Testado com o exemplo numérico da própria instrução (p=63%, odd 1,80 →
`ATINGE_EDGE_5`, porque 1,80 ≥ 1,7241 [mínima 5%] mas < 1,8018 [mínima
7,5%] — `tests/test_odds.py::TestMinimumOddsComparison`).

---

## 9. Defasagem estatística (item 10) e exemplo real ponta a ponta

Toda comparação carrega `historical_data_cutoff`, `data_staleness_days` e
um texto de aviso explícito (`src/odds/pricing_compare.staleness_warning`),
nunca omitidos. Exemplo real gerado nesta execução — **odds ILUSTRATIVAS
digitadas manualmente** (a Betano está bloqueada, seção 1; nenhum valor
abaixo veio de uma coleta real, registrado explicitamente para não violar
CLAUDE.md §23) via `data/raw/phase9_manual_example/entradas_ilustrativas.csv`:

```
sebastian baez x jenson brooksby

Sebastian Baez -- aces_player linha 5.5 (over)

Modelo: 24.5%
Odd justa: 4.09

Betano: 3.95

Edge vs preco: -0.8 p.p.
Classificacao: ABAIXO_DO_LIMITE
Edge minimo 2%: NAO ATINGIDO / 3%: NAO ATINGIDO / 5%: NAO ATINGIDO / 7.5%: NAO ATINGIDO / 10%: NAO ATINGIDO

Dados historicos atualizados ate: 2026-05-25
Defasagem: 120 dias
Overround: 2.2%
```

E um caso que atinge edge (mesma partida, `total_aces_match`, linha 13,5,
odd ilustrativa 6,20 contra odd justa 5,48):

```
Modelo: 18.2%      Odd justa: 5.48      Betano: 6.20
Edge vs preco: +2.1 p.p.      Classificacao: ATINGE_EDGE_2
```

E um caso de linha fora da grade do modelo (linha 4,5 de aces — a grade do
Baez começa em 5,5):

```
Sebastian Baez -- aces_player linha 4.5 (over)
  Betano: 4.5
  NAO CASADO com o radar atual: linha 4.5 (over) nao existe na grade do
  modelo para este jogador/mercado -- linhas disponiveis: [5.5, 6.5, ..., 18.5]
  (observacao gravada mesmo assim -- item 6, nunca perdida)
```

Nenhum desses 3 casos foi tratado como alta confiança apenas por ter edge
grande — o aviso de defasagem (120 dias) acompanha todas as comparações
casadas.

---

## 10. Snapshots (item 11) e testes (item 14)

`storage.rebuild_snapshots_history` indexa `odds_observed.parquet` por
`(bookmaker, match_id, market, player, side, line)`, ordenado no tempo, com
`snapshot_seq` e `line_move_from_previous` — verificado com duas
observações da mesma linha em horários diferentes (14h @ 1,75 → 16h @
1,88): ambas preservadas, `snapshot_seq = [1, 2]`,
`line_move_from_previous = [NaN, +0,13]`
(`tests/test_odds.py::TestMultipleSnapshots`).

`tests/test_odds.py`, 23 testes, cobrindo todos os itens pedidos:

| Teste | Item coberto |
|---|---|
| `TestOddsToProbability` (2) | conversão odd → probabilidade |
| `TestOverUnder` (1) | Over/Under juntos |
| `TestOverround` (2) | overround |
| `TestNoVig` (2) | no-vig, preço real nunca substituído |
| `TestMinimumOddsComparison` (3) | comparação com odd mínima / restrições da Fase 7 |
| `TestMultipleSnapshots` (1) | snapshots múltiplos |
| `TestTimestamps` (2) | timestamps (default e explícito) |
| `TestDuplication` (1) | duplicação (reenvio exato não duplica) |
| `TestNonexistentMarket` (3) | mercados/tours inexistentes, odd ausente |
| `TestLineDifferentFromModel` (2) | linha da casa ≠ linha do modelo, jogador não encontrado |
| `TestRestrictionApplied` (1) | restrição ATP `aces_player`/Grass herdada da Fase 7 |
| `TestStalenessWarning` (2) | warning de dados defasados |
| `TestManualEntryEndToEndWithRealRadar` (1) | pipeline completo contra o radar real da Fase 8 |

Suite completa do projeto: **172/172 testes passando** (149 das Fases 0-8.1
+ 23 novos), sem nenhuma regressão.

---

## 11. Saídas (item 12)

Todas em `data/outputs/phase9/`:

- `odds_observed.parquet` — ledger append-only de toda observação registrada.
- `comparison_with_model.parquet` — uma linha por observação, com
  `implied_probability`, `model_edge`, `status`, `odd_minima_*`,
  contexto do radar (quando casado) e defasagem.
- `snapshots_history.parquet` — mesma série, indexada por linha/lado com
  `snapshot_seq`/`line_move_from_previous`, para análise futura de
  movimentação de linha/CLV.
- `daily_odds_check.csv` — visão do estado atual (observação mais recente
  por bookmaker/partida/mercado/jogador/linha/lado); **esta, sim, é
  regenerada a cada execução** (não é um ledger).

Evidência da investigação da Betano: `data/raw/phase9_betano/source_investigation.{json,md}`.
Exemplo de entrada em lote usado nesta execução:
`data/raw/phase9_manual_example/entradas_ilustrativas.csv`.

---

## 12. Respostas finais

**1. Foi possível obter odds automaticamente da Betano?**
Não. As 7 tentativas de acesso público (HTTP puro e ferramenta de leitura
assistida, nos dois domínios testados) retornaram HTTP 403. Não existe API
oficial pública. Revendedores terceirizados existem, mas dependem do mesmo
scraping/contorno de bloqueio que a instrução proíbe fazer diretamente, e
por isso não foram usados (seção 1).

**2. Se não, a entrada manual está operacional?**
Sim — `scripts/record_odds.py` funciona ponta a ponta (CLI, JSON e CSV),
demonstrado nesta execução com um lote real de 4 entradas (5 linhas
resultantes, seção 9), incluindo casos casados, não casados e um que
atinge edge.

**3. Quais dos mercados aprovados aparecem atualmente na Betano?**
Não é possível responder objetivamente — como o acesso à Betano está
bloqueado (pergunta 1), nenhum conteúdo real da casa foi lido nesta
execução. Isso exigiria um operador humano abrindo o site/app manualmente
e digitando o que vê via `scripts/record_odds.py`; nenhum mercado foi
"assumido" como presente ou ausente.

**4. As linhas da Betano coincidem com as linhas produzidas pelo modelo?**
Também não verificável sem acesso real à Betano (pergunta 3). O mecanismo
de comparação está pronto e testado para os dois casos: linha coincidente
(casa e casa, seção 9, primeiro exemplo) e linha divergente (seção 9,
terceiro exemplo — `matched=False`, motivo explícito, observação
preservada mesmo assim).

**5. O sistema compara corretamente qualquer linha `.5` disponível?**
Sim — testado contra a grade real de 14 linhas de `aces_player` (5,5 a
18,5) e a grade de `total_aces_match`/`double_faults_player` do radar real
da Fase 8, além de casos sintéticos de ambiguidade
(`tests/test_odds.py::TestLineDifferentFromModel`,
`TestManualEntryEndToEndWithRealRadar`).

**6. Os snapshots estão sendo preservados?**
Sim — demonstrado com duas observações da mesma linha em horários
diferentes, ambas mantidas, com sequência e variação de odd calculadas
corretamente (seção 10). Reenvio exato (mesmo valor, mesmo timestamp) é a
única situação deduplicada.

**7. A Fase 9 está pronta para um forward test?**
Parcialmente. O mecanismo (casar odd × radar, calcular edge/status,
preservar snapshots, avisar defasagem) está pronto e testado ponta a ponta
contra o radar real da Fase 8. O que falta é puramente operacional, não de
código: como a Betano bloqueia qualquer acesso automatizado (pergunta 1),
um forward test real depende de um operador humano digitando as odds que vê
no site/app a cada rodada via `scripts/record_odds.py` — não há coleta
automática diária possível nesta arquitetura sem contornar o bloqueio, o
que a instrução proíbe.

---

**Parando aqui conforme instrução. Não foi calculado stake, não houve
aposta automática, nenhuma interface foi criada, não se avançou para a
Fase 10. Aguardando nova instrução.**
