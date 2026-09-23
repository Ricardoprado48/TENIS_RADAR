# 013 — RADAR DIÁRIO DE PARTIDAS FUTURAS (FASE 8)

## 0. Escopo

Esta fase recebe partidas ATP/WTA **ainda não disputadas**, associa cada jogador ao
`player_id` canônico já existente (Fase 2), reconstrói exatamente as mesmas features
point-in-time da Fase 3, aplica os mesmos baselines de taxa da Fase 4, as mesmas
distribuições/seleção de mercado da Fase 5/6, a mesma calibração da Fase 6.1 e as
mesmas fórmulas de odd justa/mínima da Fase 7 — **sem re-treinar, re-selecionar ou
re-decidir nada que já tinha sido decidido nas fases anteriores**. O único trabalho
genuinamente novo é: ingestão de partidas futuras, resolução de identidade de
jogador, e a "costura" ponta a ponta desses componentes já testados.

Mercados: `aces_player`, `total_aces_match`, `double_faults_player`, ATP e WTA
sempre separados (mesmos três mercados das Fases 5/6/6.1/7 — nenhum mercado novo
foi adicionado).

Código: `src/radar/` (`sources.py`, `identity.py`, `features_future.py`,
`rates_future.py`, `probabilities_future.py`, `calibration_future.py`,
`pricing_future.py`, `candidates.py`, `build.py`).
CLI: `scripts/build_daily_radar.py`.
Testes: `tests/test_radar.py` (13 testes; 128/128 no total do projeto).
Saídas: `data/outputs/phase8/`.

Não foi consultada nenhuma casa de apostas, não houve scraping de odds, não foi
calculado stake, nenhuma interface foi criada. Não se avançou para a Fase 9.

---

## 1. Fonte de partidas futuras (item 1)

### 1.1 Investigação de fontes estruturadas (prioridade pedida: estruturada pública →
HTTP simples → Tennis Abstract → Firecrawl → browser automation)

Antes de escrever qualquer código, testamos diretamente (via `curl`/HTTP simples, o
mesmo cliente que um script Python usaria) as fontes estruturadas mais prováveis:

| Fonte | Resultado | Motivo |
|---|---|---|
| ESPN (`site.api.espn.com/.../tennis/atp/scoreboard`) | HTTP 403 | Bloqueio de bot Akamai |
| ATP Tour (`atptour.com`) | HTTP 403 (via `curl`/`requests`) | Bloqueio de bot Akamai |
| Sofascore (`api.sofascore.com`) | HTTP 403 | Bloqueio de bot |
| WTA Tour (`wtatennis.com`) | HTTP 200, mas HTML vazio | SPA — conteúdo só existe depois de JavaScript rodar no navegador |
| Flashscore | HTTP 200, mas HTML vazio | Mesmo motivo (SPA) |
| `r.jina.ai` (proxy de leitura genérico) | Bloqueado com CAPTCHA da Akamai | O bloqueio é no destino, não no cliente |
| Wikipedia (API oficial) | HTTP 200, JSON estruturado | Acessível, mas o conteúdo (quadro/`draw`) de um torneio cujo sorteio saiu horas antes **ainda não estava editado** — não é confiável para "hoje" |
| `tennis-data.co.uk` | HTTP 200 | Tem odds históricas, mas **nenhuma estatística de saque/devolução** e os termos de uso **proíbem explicitamente coleta por bots/IA** (já registrado em `docs/002`, Fonte 6) — descartada |

Nenhuma fonte pública testada respondeu com dados estruturados de partidas futuras a
um cliente HTTP puro sem bloqueio de bot ou sem depender de execução de JavaScript.
Não há Firecrawl nem browser automation (Playwright) disponíveis neste ambiente de
execução, então essas duas opções (prioridades 4 e 5 da instrução) não puderam ser
testadas.

**O que funcionou**: as páginas de `daily-schedule`/`draws` do site oficial da ATP
Tour e da WTA Tour responderam corretamente a uma ferramenta de busca/leitura web
assistida (não um cliente HTTP puro em Python) usada manualmente nesta sessão para
montar o arquivo bruto desta execução — provavelmente porque esse tipo de ferramenta
executa a página como um navegador real, o que contorna o bloqueio de bot que a
Akamai aplica a clientes HTTP simples. Isso não é reproduzível a partir de um script
Python rodando sozinho neste ambiente.

### 1.2 Decisão de arquitetura

Por isso, a ingestão desta fase (`src/radar/sources.py`) é feita a partir de um
**arquivo bruto local** (`data/raw/phase8/partidas_futuras_YYYYMMDD.csv`), com um
contrato de schema fixo — `source_url`, `collected_at`, `tour`, `tournament`,
`surface`, `match_date`, `match_time` (opcional), `round`, `player_a_raw`,
`player_b_raw` — que é **exatamente o schema que um cliente HTTP automatizado
preencheria** se/quando uma fonte ficar acessível sem bloqueio (ex.: uma API paga —
Fonte 9 do `docs/002` — ou acesso a Firecrawl/browser automation em outro ambiente).
`sources.load_raw_matches()` valida esse schema (tour precisa ser ATP/WTA, nenhuma
coluna obrigatória vazia) e preserva `source_url`/`collected_at` linha a linha
(CLAUDE.md §11), nunca inventados.

O arquivo usado nesta execução (`data/raw/phase8/partidas_futuras_20260922.csv`) foi
populado com **18 partidas reais**, coletadas manualmente das páginas oficiais ATP
Tour / WTA Tour no momento da execução desta fase (22/09/2026, URLs registradas por
linha) — 4 partidas de R32 do ATP Chengdu Open e do AITO Hangzhou Open (China, dia
23/09), 8 partidas de R16 do WTA Korea Open (Seoul, dia 23/09) e 6 partidas de R32 do
WTA Singapore Tennis Open (dia 22/09). Nenhum dado foi fabricado.

Isso é uma limitação real e documentada (CLAUDE.md §13: "não criar dependência
crítica de fonte frágil sem documentar o risco"), não contornada silenciosamente: o
comando `python scripts/build_daily_radar.py` funciona ponta a ponta a partir desse
arquivo, mas **não busca partidas sozinho pela rede** nesta versão.

---

## 2. Resolução de identidade (item 2)

`src/radar/identity.py` implementa 4 níveis, nunca associando silenciosamente quando
há dúvida (só resolve quando exatamente 1 candidato sobra em cada nível):

1. **`exact`** — nome completo normalizado (sem acento, minúsculo) bate com
   exatamente 1 `player_id` em `data/processed/{tour}/players.parquet`.
2. **`alias`** — formato abreviado típico de quadros de torneio ("J. Ostapenko"):
   inicial do primeiro nome + sobrenome, resolvido contra a base do tour, com
   exatamente 1 candidato.
3. **`fuzzy_review`** — nenhum match exato/alias, mas exatamente 1 nome completo do
   tour fica acima do limiar de similaridade (`difflib.SequenceMatcher`, biblioteca
   padrão do Python — nenhuma dependência nova foi adicionada). Gera previsão, mas
   fica sinalizado para revisão humana.
4. **`unresolved`** — nenhum candidato, ou mais de um candidato igualmente plausível
   em qualquer nível. **Nunca gera previsão** (item 2 da instrução).

### Resultado real desta execução

| Método | Partidas (jogador × lado) |
|---|---:|
| `exact` | 15 |
| `alias` | 16 |
| `unresolved` | 5 |

Das 18 partidas brutas, **13 ficaram `usable_for_prediction=True`** (os dois
jogadores resolvidos) e 5 foram descartadas por ter pelo menos um lado
`unresolved` — nenhuma previsão foi gerada para elas. O motivo de cada uma está em
`data/outputs/phase8/jogadores_nao_resolvidos.csv`:

| Nome bruto | Torneio | Motivo |
|---|---|---|
| A. Korneeva | Korea Open (Seoul) | sobrenome + inicial ambíguo: 2 candidatas |
| S. Park | Korea Open (Seoul) | sobrenome + inicial ambíguo: **11 candidatas** (sobrenome comum) |
| Y. Ku | Korea Open (Seoul) | sobrenome + inicial ambíguo: 2 candidatas |
| Y. Ma | Korea Open (Seoul) | sobrenome + inicial ambíguo: 3 candidatas |
| Xinyu Wang | Singapore Tennis Open | sobrenome + inicial ambíguo: 7 candidatas |

Isso é o comportamento esperado, não um bug: sobrenomes comuns (coreanos e chineses,
neste caso) legitimamente colidem entre várias jogadoras do circuito, e a regra do
item 2 ("nunca associação silenciosa") exige descartar em vez de adivinhar.

---

## 3. Features pré-jogo (item 3)

`src/radar/features_future.py` **não reimplementa** o motor point-in-time da Fase 3
— cada partida futura vira duas linhas sintéticas (Serve A × Return B e Serve B ×
Return A, CLAUDE.md §2), no mesmo schema da tabela de partidas da Fase 2, anexadas ao
final da tabela histórica real do tour (sempre depois de qualquer partida real, pela
ordenação `[tournament_date, tourney_id, match_id, result]`), e então
`src.features.profile.build_player_profile` +
`src.features.matchup.build_matchup_table` — **o mesmo código da Fase 3, sem
alteração** — são chamados na tabela completa. Como as janelas históricas usam
estritamente `shift(1)`/soma-até-a-linha-anterior por jogador, as duas linhas
sintéticas recebem exatamente o estado point-in-time real de cada jogador, e todas as
estatísticas da própria partida (`aces`, `double_faults`, ...) ficam `<NA>` — nunca
inventadas — porque a partida ainda não aconteceu.

**Prova de ausência de leakage** (`tests/test_radar.py::TestFeaturesNoLeakage`):
escolhemos uma partida real do dataset cujos dois jogadores nunca mais aparecem
depois dela (a última linha de cada um, em toda a tabela ATP), removemos só as 2
linhas dessa partida, reconstruímos a mesma partida como se fosse "futura" pelo
mecanismo desta fase, e comparamos as colunas `player_serve_ace_rate_career`,
`player_serve_ace_rate_last50`, `opponent_return_ace_allowed_rate_career`,
`prior_matches_career` e `player_serve_double_fault_rate_career` resultantes contra a
linha **real**, já gravada por produção em
`data/processed/features/atp/player_match_features.parquet`. As colunas batem
exatamente (diferença `< 1e-9`) — confirmando que o truque de linha sintética não
perde nem vaza nenhuma informação em relação ao motor de produção.

---

## 4. Mercados e restrições herdadas (item 4)

Os três mercados e a separação ATP/WTA são idênticos às Fases 5/6/6.1/7 — nenhum
novo mercado foi adicionado, nenhuma configuração foi re-decidida:

- `(variant, window)` por tour/mercado: reaproveita
  `src.probabilistic.selection.build_all_configs()` diretamente (mesma lógica de
  Grass vs. base já decidida na Fase 6).
- `negbin_r` / `train_mean`: lidos de
  `data/outputs/phase4/metrics/count_distribution_metrics.csv`, filtrados para
  `fold=fold_2026` (ver seção 11 — por que esse é o fold correto para "hoje").
- Método de calibração (`raw`/`platt`/`isotonic`) por tour/mercado: lido de
  `data/outputs/phase6_1/selecao_metodo_por_mercado.csv`, nunca re-decidido.
- Restrição ATP `aces_player`/Grass: reaproveita `src.pricing.flags.restricted_flag`
  **sem nenhuma alteração** — mesma regra, mesmo motivo textual, herdado da Fase 6.1.

Nenhuma das 13 partidas resolvidas desta execução é em Grass (todas são do "Asian
hard swing" de setembro/2026), então a restrição não aparece na tabela real desta
rodada — mas o mecanismo é idêntico ao da Fase 7 e continua testado
(`tests/test_radar.py::TestRestrictionApplied`, que injeta uma partida sintética
ATP/`aces_player`/Grass e confirma `restricted=True` e preço mantido, não ocultado).

---

## 5. Linhas e preços (item 5)

Exemplo real completo — **ATP `aces_player`, Chengdu Open, R32, Jenson Brooksby vs.
Sebastian Baez** (Platt scaling, fold vigente = fold_2026):

**Jenson Brooksby — aces (histórico: 106 partidas anteriores, `large_50_plus`)**

| Linha | P(Over) | P(Under) | Odd justa O | Odd justa U |
|---:|---:|---:|---:|---:|
| 5,5 | 44,11% | 55,89% | 2,27 | 1,79 |
| 6,5 | 33,12% | 66,88% | 3,02 | 1,50 |
| 7,5 | 24,19% | 75,81% | 4,13 | 1,32 |
| 8,5 | 17,32% | 82,68% | 5,77 | 1,21 |
| 9,5 | 12,22% | 87,78% | 8,18 | 1,14 |

Odds mínimas aceitáveis (linha 8,5, Over, p=17,32%) por edge exigido, usando
exatamente a fórmula da Fase 7 (`odd_mínima = 1/(p_modelo - e)`):

| Edge exigido | Odd mínima aceitável |
|---|---:|
| — (odd justa) | 5,77 |
| 2% | 6,53 |
| 3% | 6,98 |
| 5% | 8,12 |
| 7,5% | 10,19 |
| 10% | 13,67 |

As cinco faixas de edge (2%/3%/5%/7,5%/10%) foram geradas para todas as
12 linhas × 2 lados × 3 mercados × 13 partidas usáveis — nenhum edge foi escolhido
como padrão operacional (item 10: essa escolha fica para quando houver dados reais
de odds).

---

## 6. Qualidade da previsão (item 6)

Toda linha carrega, além de probabilidade/odd: `prior_matches_career`,
`sample_bucket_career`, `surface`, `method_selected` (status de calibração),
`restricted`/`restricted_motivo`, `extreme_probability`, `insufficient_history`,
`resolution_method_player`/`resolution_method_opponent` (qualidade da resolução de
identidade).

**Exemplo real de aviso de baixa amostra**: Kyrian Jacquet (adversário de Aleksandar
Vukic, AITO Hangzhou Open) tem apenas **7 partidas anteriores** no dataset —
`sample_bucket_career = small_1_9`, flag `insufficient_history = True` em todas as
suas linhas. O preço continua sendo gerado normalmente (ex.: linha 8,5 aces, Over,
p=65,40%, odd justa 1,53), mas **nenhuma dessas linhas vira candidata no radar
resumido** (seção 7) — a flag é visível, não oculta, e o critério de baixa amostra
exclui essas linhas do "vale a pena conferir odds" sem impedir que o preço exista.

Resumo de flags nesta execução (1.972 linhas de preço, jogador × linha × lado):

| Flag | Contagem |
|---|---:|
| `insufficient_history` | 480 (jogadores com 1–9 partidas anteriores) |
| `extreme_probability` (≥90%) | 499 (25,3% das linhas — concentrada nas linhas mais extremas de cada grade) |
| `restricted` | 0 (nenhuma partida em Grass nesta rodada) |
| `cold_start` | 0 (nenhum jogador com 0 partidas anteriores nesta rodada) |

---

## 7. Radar resumido (item 7)

**Nunca chamado de "value bet"** — o rótulo usado é `CANDIDATO PARA CONFERIR ODDS`,
atribuído por linha quando **todos** os critérios abaixo são verdadeiros (fixados a
priori, não ajustados nos dados desta execução):

1. histórico suficiente (`sample_bucket_career` em `{medium_10_49, large_50_plus}`);
2. mercado liberado (`restricted == False`);
3. calibração disponível (`negbin_r`/`método` existiam para aquele
   tour/mercado/variante/janela no fold vigente);
4. probabilidade não trivial (`extreme_probability == False`);
5. identidade confiável (os dois jogadores resolvidos por `exact` ou `alias` — nunca
   `fuzzy_review`, mesmo que a linha tenha preço).

### Radar real — 22/09/2026 (`data/outputs/phase8/radar_diario_resumo.csv`)

Das 13 partidas usáveis, **todas as 13** tiveram pelo menos uma linha classificada
como `CANDIDATO PARA CONFERIR ODDS` nesta rodada (ordenadas por número de linhas
candidatas):

| Torneio | Jogador A | Jogador B | Linhas candidatas |
|---|---|---|---:|
| AITO Hangzhou Open | Valentin Royer | Adam Walton | 141 |
| Korea Open (Seoul) | Jelena Ostapenko | Taylah Preston | 126 |
| Singapore Tennis Open | Fiona Ferro | Talia Gibson | 120 |
| Korea Open (Seoul) | Kamilla Rakhimova | Katie Volynets | 112 |
| Singapore Tennis Open | Rebecca Sramkova | Maja Chwalinska | 109 |
| Chengdu Open | Sebastian Baez | Jenson Brooksby | 102 |
| ... | ... | ... | ... |
| Chengdu Open | Vit Kopriva | Jia Hu | 39 (só 2 mercados — double faults não gerou linhas suficientes) |

Nenhuma odd real foi consultada para produzir esta lista — os critérios são
inteiramente estatísticos/documentados, como pedido no item 7.

---

## 8. Saídas (item 8)

Todas em `data/outputs/phase8/` (parquet + CSV quando fizer sentido para inspeção):

- `partidas_futuras_brutas.{parquet,csv}` — as 18 partidas exatamente como
  ingeridas, com `source_url`/`collected_at` por linha.
- `partidas_resolvidas.{parquet,csv}` — as 18 partidas com `player_id_a/b`,
  `resolution_method_a/b`, `is_duplicate`, `usable_for_prediction`.
- `jogadores_nao_resolvidos.csv` — log dos 5 jogadores não resolvidos, com motivo.
- `previsoes_por_partida.parquet` — 986 linhas (jogador × partida futura × mercado ×
  linha `.5`): `lambda`, `negbin_r`, `raw_probability`, variante/janela usada.
- `precos_por_linha.parquet` (+ `.csv`) — 1.972 linhas (× 2 lados): probabilidade
  operacional, odd justa, todas as flags de qualidade/restrição, `is_candidate`.
- `odds_minimas_por_edge.parquet` (+ `.csv`) — 9.860 linhas (master × 5 cenários de
  edge): odd mínima aceitável por edge.
- `radar_diario_resumo.csv` — 13 linhas, uma por partida usável, com contagem de
  linhas candidatas.
- `phase8_summary.json` — resumo agregado da execução, incluindo o relatório de
  defasagem de dados (seção 10).

---

## 9. Testes (item 10)

`tests/test_radar.py`, 13 testes, todos cobrindo um item explícito da instrução:

| Teste | Cobre |
|---|---|
| `TestIdentityResolution` (5 testes) | `exact`/`alias`/`fuzzy_review`/`unresolved`, incluindo ambiguidade |
| `TestFeaturesNoLeakage` | ausência de leakage (reconstrução idêntica à Fase 3, ver seção 3) |
| `TestUnknownPlayerNoPrediction` | jogador desconhecido não gera previsão |
| `TestSurfaceAndTournamentPreserved` | torneio/superfície preservados na linha sintética + Serve A×Return B |
| `TestDuplicateMatches` | partidas repetidas (mesma dupla, ordem invertida) detectadas |
| `TestIdempotentExecution` | rodar o pipeline duas vezes produz `precos_por_linha.parquet` byte-a-byte idêntico |
| `TestRestrictionApplied` | ATP `aces_player`/Grass sintético → `restricted=True`, preço mantido |
| `TestConsistencyWithPhase7` | calibrador reajustado nesta fase reproduz **exatamente** (`atol=1e-12`) a `calibrated_probability` real da Fase 6.1 para os 6 tour/mercado × fold_2026 |

Suite completa do projeto: **128/128 testes passando** (115 das Fases 0-7 + 13
novos), sem nenhuma regressão.

---

## 10. Limitações (documentadas, não escondidas)

- **Defasagem de dados**: a base histórica (`data/processed/{atp,wta}/matches.parquet`)
  tem sua última partida em **25/05/2026**; as partidas futuras desta execução são de
  22-23/09/2026 — um hiato de **~120 dias sem partidas ingeridas**. Isso significa que
  o estado point-in-time de cada jogador reflete a forma dele até maio/2026, não a
  forma real de setembro. Isso não foi corrigido nesta fase (reingestão é escopo da
  Fase 1, não desta) — reportado em `phase8_summary.json.data_staleness` e aqui, em
  vez de omitido.
- **Ingestão não é um cliente HTTP automatizado** (ver seção 1): esta versão depende
  de um arquivo bruto pré-populado, não de uma chamada de rede feita pelo próprio
  script. `scripts/build_daily_radar.py` roda ponta a ponta a partir desse arquivo.
- **`best_of` da partida futura**: deixado `<NA>` (não inventado) — não afeta nenhuma
  fórmula de previsão desta fase (não é usado em `features`/`rate_models`), mas
  significa que a tabela de saída não distingue melhor-de-3/melhor-de-5.
  `player_rank`/`opponent_rank` da partida futura também ficam `<NA>` pelo mesmo
  motivo (não consultamos rankings point-in-time nesta fase).
- **Heurística de alias** (`sobrenome + inicial`) pode ficar ambígua para sobrenomes
  comuns (5 dos 18 casos desta execução) — comportamento correto (descarta em vez de
  adivinhar), mas significa cobertura incompleta em torneios com jogadoras/jogadores
  de sobrenomes muito frequentes.
- Nenhuma odd real foi usada. `implied_probability`/`edge` (Fase 7,
  `src.pricing.odds`) continuam disponíveis e testados, mas não foram chamados com
  dados reais nesta fase.

---

## 11. Por que `fold_2026` é o fold correto para "hoje" (consistência com a Fase 7)

Hoje (22/09/2026) cai dentro da janela de teste do `fold_2026`
(`src/baselines/config.py`: teste 01/01/2026–31/12/2026, treino = tudo `<=
2025-12-31`). Por isso, tanto o `negbin_r` quanto o calibrador (Platt/Isotonic)
aplicados às partidas futuras desta fase são **exatamente os mesmos que a Fase
4/6.1 já calcularam para esse fold** — sem vazamento, porque nenhum deles usa dado
posterior a 2025-12-31.

Como o modelo de calibração ajustado pela Fase 6.1 não é persistido em disco (só a
probabilidade calibrada resultante, para as linhas que já existiam), esta fase
reajusta o calibrador (`src/radar/calibration_future.py`) com os mesmos dados de
treino (`fold_2024 + fold_2025`) e o mesmo método já decidido (nunca re-decidido).
Verificamos que isso reproduz **exatamente** a `calibrated_probability` gravada pela
Fase 6.1 para todas as linhas reais de `fold_2026` (entre ~28.300 e ~32.800 linhas
por tour/mercado, conforme o mercado) de cada um dos 6 tour/mercado (diferença máxima
= 0,0 em ponto flutuante duplo) — prova de que a Fase 8 não introduziu nenhuma
divergência silenciosa na regra de calibração.

---

**Parando aqui conforme instrução. Não foram consultadas casas de apostas, não houve
scraping de odds, não houve cálculo de stake, nenhuma aposta automática foi criada,
nenhuma interface foi criada, e não se avançou para a Fase 9. Aguardando nova
instrução.**
