# 002 — FONTES DE DADOS

Status: Fase 0 concluída (pesquisa). Fase 1 (ingestão) concluída — ver `docs/005_RELATORIO_INGESTAO_FASE1.md`.
Fase 2 (normalização) concluída — ver `docs/006_RELATORIO_NORMALIZACAO_FASE2.md`.
Fase 3 (features Serve × Return point-in-time) concluída — ver `docs/007_RELATORIO_FEATURES_FASE3.md`.
Fase 4 (baselines estatísticos e avaliação walk-forward) concluída — ver `docs/008_RELATORIO_BASELINES_FASE4.md`.
Fase 5 (comparação de robustez e seleção técnica dos mercados) concluída — ver `docs/009_SELECAO_MERCADOS_FASE5.md`.
Fase 6 (distribuições probabilísticas e calibração) concluída — ver `docs/010_DISTRIBUICOES_PROBABILISTICAS_FASE6.md`.
Fase 6.1 (calibração das probabilidades out-of-sample) concluída — ver `docs/011_CALIBRACAO_PROBABILISTICA_FASE6_1.md`.
Fase 7 (odd justa e odd mínima aceitável) concluída — ver `docs/012_ODDS_JUSTAS_FASE7.md`.
Fase 8 (radar diário de partidas futuras) concluída — ver `docs/013_RADAR_DIARIO_FASE8.md`.
Fase 8.1 (atualização incremental da base histórica) concluída — nenhuma fonte adequada encontrada (base ainda termina em 2026-05-25) — ver `docs/014_ATUALIZACAO_INCREMENTAL_FASE8_1.md`.
Última atualização: 2026-09-22.

## ADENDO (2026-09-22, início da Fase 1) — repositórios originais do Sackmann saíram do ar

No início da Fase 1, ao tentar baixar os dados, descobrimos que os repositórios
`JeffSackmann/tennis_atp`, `JeffSackmann/tennis_wta` e `JeffSackmann/tennis_slam_pointbypoint`
**não existem mais publicamente no GitHub** (a conta do autor lista hoje apenas 1
repositório público, `tennis_MatchChartingProject`; `api.github.com/repos/JeffSackmann/tennis_atp`
retorna HTTP 404). Isso contraria a expectativa de estabilidade registrada na Fonte 1/2 abaixo.

Como fallback documentado (CLAUDE.md §13 — "não criar dependência crítica de fonte frágil sem
documentar o risco"), a Fase 1 usou o mirror `Aneeshers/tennis-sackmann-archive`
(https://github.com/Aneeshers/tennis-sackmann-archive), que se declara uma cópia arquival dos
dados originais de Jeff Sackmann sob a mesma licença CC BY-NC-SA 4.0, com snapshot de um commit
upstream de 2026-06-25 (ou seja, momentos antes dos repositórios originais saírem do ar).
Detalhes completos, riscos e plano de contingência estão em
`docs/005_RELATORIO_INGESTAO_FASE1.md`.

## Objetivo

Documentar todas as fontes avaliadas para construção do dataset histórico, e recomendar quais usar na Fase 1 (ingestão).

## Prioridade adotada (conforme CLAUDE.md §12)

1. Dataset estruturado
2. CSV / Parquet
3. API oficial
4. HTTP simples
5. HTML
6. Firecrawl
7. Playwright / browser automation

---

## Fonte 1 — Jeff Sackmann `tennis_atp` (GitHub) — PRINCIPAL (ATP)

- **URL:** https://github.com/JeffSackmann/tennis_atp
- **ATP/WTA:** ATP (masculino).
- **Cobertura temporal:** resultados desde ~1968 (era aberta); estatísticas de partida (`MatchStats`) geralmente a partir de **1991** em nível tour, **2008** em Challengers, **2011** em qualifying tour-level. Atualizado até a temporada corrente (2026).
- **Estatísticas de saque/devolução:** sim, por partida (agregado, não ponto a ponto). Colunas típicas por jogador (vencedor `w_*` / perdedor `l_*`):
  `ace, df, svpt, 1stIn, 1stWon, 2ndWon, SvGms, bpSaved, bpFaced`.
  Permite derivar Ace%, 1st serve%, 1st/2nd serve points won%, hold%, break points saved% — exatamente as métricas por oportunidade exigidas em CLAUDE.md §5/§6.
  **Limitação:** não há devolução detalhada por lado de quadra nem por rally length; apenas agregados da partida.
- **Superfície:** coluna `surface` (Hard/Clay/Grass/Carpet).
- **Identificadores de jogador:** `player_id` numérico estável (arquivo `atp_players.csv` com nome, mão dominante, data de nascimento, país, altura) — resolve exigência de identidade canônica (CLAUDE.md §10).
- **Rankings:** arquivos `atp_rankings_*.csv` separados, com `ranking_date, rank, player_id, points` — permite ranking **point-in-time** correto (crítico para CLAUDE.md §3).
- **Formato:** CSV puro, um arquivo por temporada (`atp_matches_YYYY.csv`), mais arquivos de qualifying/challenger e de rankings. `matches_data_dictionary.txt` documenta todas as colunas.
- **Atualização:** contínua durante a temporada, mantida ativamente pelo autor.
- **Estabilidade:** alta — dataset de referência acadêmica, usado em dezenas de papers e no próprio site Tennis Abstract. Existem mirrors de arquivamento (ex.: `Aneeshers/tennis-sackmann-archive`) caso o repositório oficial saia do ar.
- **Licença:** **Creative Commons Attribution-NonCommercial-ShareAlike 4.0 (CC BY-NC-SA 4.0)**. Exige atribuição, uso não comercial, e compartilhamento sob a mesma licença de qualquer derivado. **Compatível com a fase atual de pesquisa (não comercial)**, mas é uma restrição a revisitar antes de qualquer uso comercial futuro do projeto.
- **Coleta recomendada:** clone do repositório Git ou download direto dos CSVs via HTTP. Não requer scraping.

## Fonte 2 — Jeff Sackmann `tennis_wta` (GitHub) — PRINCIPAL (WTA)

- **URL:** https://github.com/JeffSackmann/tennis_wta
- **ATP/WTA:** WTA (feminino).
- **Estrutura:** espelha exatamente a estrutura do `tennis_atp` (mesmos nomes de coluna, `wta_matches_YYYY.csv`, `wta_players.csv`, `wta_rankings_*.csv`).
- **Cobertura temporal:** desde 1968, com MatchStats de qualidade consistente principalmente a partir dos anos 2000s (cobertura de estatísticas de saque é historicamente mais esparsa que no ATP, especialmente antes de ~2000).
- **Licença:** mesma CC BY-NC-SA 4.0.
- **Observação:** o autor não faz merge de pull requests no dataset, mas aceita correções — ou seja, qualidade depende de curadoria comunitária lenta; podem existir gaps/erros pontuais.
- **Coleta recomendada:** igual ao ATP, clone/download HTTP direto.

## Fonte 3 — Jeff Sackmann `tennis_slam_pointbypoint` (GitHub) — COMPLEMENTAR

- **URL:** https://github.com/JeffSackmann/tennis_slam_pointbypoint
- **Conteúdo:** dados ponto a ponto (point-by-point) dos 4 Grand Slams, 2011–2024/2025, originalmente publicados pelo IBM Slamtracker (e depois Infosys MatchBeats, a partir de 2018 para AO/RG).
- **ATP/WTA:** ambos, singles (e alguns anos com duplas/mistas).
- **Formato:** um par de arquivos `*-matches.csv` e `*-points.csv` por Slam/ano.
- **Utilidade para o projeto:** único conjunto público com granularidade ponto a ponto (permitiria validar tie-break, dinâmica de saque ponto a ponto), mas **cobertura limitada a Grand Slams** — não serve como base geral para os 7 mercados.
- **Licença:** CC BY-NC-SA 4.0.
- **Coleta recomendada:** download HTTP direto dos CSVs.

## Fonte 4 — Jeff Sackmann `tennis_MatchChartingProject` (GitHub) — COMPLEMENTAR (alta granularidade, baixa cobertura)

- **URL:** https://github.com/JeffSackmann/tennis_MatchChartingProject
- **Conteúdo:** dados shot-by-shot (direção, profundidade, tipo de erro) de partidas carregadas manualmente por voluntários desde 2013.
- **Cobertura:** ~5.000+ partidas (ATP, WTA, ITF, Slams) — **fração muito pequena** do universo total de partidas profissionais; viés de seleção forte (voluntários tendem a chartar partidas de jogadores top / Slams).
- **Estatísticas:** as mais detalhadas disponíveis publicamente — inclui direção de saque, profundidade de devolução, rally length, que vão além do exigido nos mercados iniciais.
- **Formato:** CSV (`*-matches.csv`, `*-points.csv` por gênero/década, `*-stats-*.csv` agregados).
- **Licença:** CC BY-NC-SA 4.0.
- **Uso recomendado:** não como base primária (cobertura insuficiente), mas como fonte de **validação cruzada** de métricas derivadas do `tennis_atp`/`tennis_wta` em uma amostra de partidas.

## Fonte 5 — Tennis Abstract (tennisabstract.com) — COMPLEMENTAR / REFERÊNCIA

- **URL:** https://www.tennisabstract.com
- **Conteúdo:** site do mesmo Jeff Sackmann, publica Elo ratings (incluindo variantes: Elo por superfície, "yElo" de curto prazo), H2H, e páginas de estatísticas agregadas por jogador.
- **Formato:** **páginas HTML** (não há export CSV/API direto para todo o conteúdo do site) — na prática, os dados subjacentes já estão nos repositórios GitHub acima; o site é uma camada de visualização.
- **Estabilidade/licença:** sem termos de uso explícitos de scraping localizados; site pessoal, não afiliado a organizações oficiais.
- **Uso recomendado:** **não priorizar scraping deste site na Fase 1.** Os dados brutos equivalentes já vêm dos repositórios GitHub. Reconsiderar apenas se precisarmos especificamente das séries de Elo já calculadas (em vez de recalculá-las nós mesmos) — nesse caso, HTML parsing simples seria suficiente, sem necessidade de Playwright.

## Fonte 6 — tennis-data.co.uk — NÃO USAR COMO FONTE AUTOMATIZADA (risco de licença)

- **URL:** http://www.tennis-data.co.uk
- **Conteúdo:** resultados e odds históricas de casas de apostas. ATP desde 2000, WTA desde 2007. Odds desde 2001 (ATP) / 2007 (WTA).
- **Estatísticas de saque/devolução:** **NÃO possui** (nenhuma coluna de aces, double faults, first serve% etc. — apenas placar, ranking e odds).
- **Formato:** Excel (.xlsx/.xls), um arquivo por temporada, atualizado semanalmente.
- **Licença — ATENÇÃO:** os termos do site **proíbem explicitamente uso comercial e "uso por bots/scrapers/ferramentas de IA automatizadas"** ("not commercial or data training products using automated bots/scrapers/AI"). Isso é incompatível com download automatizado via agente de IA (como este projeto está sendo construído). **Não recomendado como dependência do pipeline**, mesmo sendo estruturalmente atraente.
- **Relevância para o projeto:** baixa na fase atual — não cobre nenhum dos mercados de saque/devolução do escopo; seria relevante apenas na Fase 8/9 (odds justas / odds de mercado), e mesmo assim exigiria coleta manual pelo usuário, não automatizada.

## Fonte 7 — Ultimate Tennis Statistics / tennis-crystal-ball (GitHub) — REFERÊNCIA, NÃO FONTE PRIMÁRIA

- **URL:** https://github.com/mcekovic/tennis-crystal-ball / https://www.ultimatetennisstatistics.com
- **Conteúdo:** não é uma fonte de dados própria — é uma aplicação (Java + PostgreSQL, licença Apache 2.0) que **consome o dataset do Jeff Sackmann** e o expõe com uma UI de estatísticas e previsões.
- **Utilidade:** útil como referência para conferir se nossos cálculos derivados (hold%, Elo, etc.) batem com uma implementação de terceiros já estabelecida — bom para validação, não para ingestão.

## Fonte 8 — TML-Database (Tennismylife) — CANDIDATA A GAP-FILLER (ATP, dados recentes)

- **URL:** https://github.com/Tennismylife/TML-Database
- **Conteúdo:** derivado do `tennis_atp` do Sackmann, mas com atualização **diária/quase em tempo real** e alegando preencher lacunas do dataset original.
- **ATP/WTA:** somente ATP.
- **Cobertura:** 1968–2026.
- **Licença:** também CC BY-NC-SA (não comercial), citando o trabalho original de Sackmann como base.
- **Uso recomendado:** possível fonte complementar para **fechar o gap de atualização** entre o fim de uma temporada nos dados do Sackmann e a partida mais recente, já que o repositório oficial do Sackmann não é atualizado em tempo real. Avaliar na Fase 1 se a defasagem do `tennis_atp` for um problema prático; não é crítica para o objetivo atual (construir base histórica).

## Fonte 9 — API oficial ATP / WTA

- **Situação:** **não existe API pública documentada** da ATP Tour nem da WTA para desenvolvedores externos. Acesso "estruturado" a dados oficiais recentes hoje depende de terceiros comerciais (ex. Tennis-API.com, Matchstat API) — serviços pagos, fora do escopo de "fonte gratuita" desta fase.
- **Conclusão:** descartar como fonte para a Fase 1. Reavaliar apenas se, nas fases seguintes, for necessário dado ao vivo/near-real-time e houver orçamento para uma API comercial — decisão fora do escopo atual (CLAUDE.md §24).

---

## Resumo comparativo

| Fonte | ATP/WTA | Anos | Serve/Return stats | Formato | Licença | Prioridade |
|---|---|---|---|---|---|---|
| tennis_atp (Sackmann) | ATP | ~1968–2026 (stats desde 1991) | Sim (agregado/partida) | CSV | CC BY-NC-SA 4.0 | **Principal** |
| tennis_wta (Sackmann) | WTA | ~1968–2026 (stats mais esparsas antes dos 2000s) | Sim (agregado/partida) | CSV | CC BY-NC-SA 4.0 | **Principal** |
| tennis_slam_pointbypoint | Ambos | 2011–2024/25, só Slams | Sim (ponto a ponto) | CSV | CC BY-NC-SA 4.0 | Complementar |
| tennis_MatchChartingProject | Ambos | 2013+, ~5.000 partidas | Sim (shot-by-shot) | CSV | CC BY-NC-SA 4.0 | Complementar/validação |
| Tennis Abstract (site) | Ambos | — | Elo derivado | HTML | não documentada | Referência, baixa prioridade |
| tennis-data.co.uk | Ambos | ATP 2000+, WTA 2007+ | **Não** | Excel | Proíbe coleta automatizada/IA | **Não usar automatizado** |
| Ultimate Tennis Statistics | Ambos | — | Deriva do Sackmann | App/DB | Apache 2.0 (app) | Referência de validação |
| TML-Database | ATP | 1968–2026, diário | Sim | CSV | CC BY-NC-SA | Gap-filler potencial |
| API oficial ATP/WTA | — | — | — | — | Inexistente publicamente | Descartada nesta fase |

---

## Pipeline mínimo de ingestão proposto (Fase 1)

Não implementado nesta fase — apenas proposta para aprovação.

1. **Download direto via HTTP** (sem scraping) dos repositórios GitHub:
   - `tennis_atp`: `atp_matches_{ano}.csv`, `atp_players.csv`, `atp_rankings_*.csv`.
   - `tennis_wta`: equivalentes.
   - Intervalo inicial sugerido: desde o primeiro ano com `MatchStats` consistentes (1991 ATP / avaliar cobertura real WTA) até a temporada atual.
2. Salvar cópia imutável em `data/raw/sackmann_atp/<ano>/` e `data/raw/sackmann_wta/<ano>/`, preservando nome original do arquivo + registrando `source_url`, `data de coleta` e `commit hash` do repositório no momento do download (CLAUDE.md §11).
3. **Não normalizar nada ainda** — Fase 1 é só ingestão bruta. Normalização de IDs/nomes/superfície fica para a Fase 2, conforme `docs/004_PLANO_DE_PESQUISA.md`.
4. Point-by-point (`tennis_slam_pointbypoint`) e Match Charting Project entram em `data/raw/` como conjuntos separados, claramente marcados como cobertura parcial (só Slams / só ~5k partidas), para não serem confundidos com a base completa.
5. TML-Database fica como candidato a fonte de atualização incremental — decisão adiada até verificarmos, na prática, o tamanho real do gap de atualização do `tennis_atp`.

## Lacunas de dados identificadas

- **WTA histórico antigo:** estatísticas de saque (`ace, df, svpt`, etc.) são mais esparsas/inconsistentes no `tennis_wta` antes dos anos 2000 — precisa ser medido empiricamente na Fase 1 (contar % de partidas com `NaN` em MatchStats por ano) antes de decidir a partir de qual temporada os dados WTA são confiáveis.
- **Devolução detalhada:** nenhuma fonte gratuita e estruturada tem devolução detalhada (ex. return points won por lado de quadra) fora do Match Charting Project, que cobre uma fração pequena e enviesada das partidas. Isso limita a precisão de métricas "opponent-adjusted" (CLAUDE.md §6/§7) na base ampla — só será possível com boa cobertura para o agregado `1stWon/2ndWon` do sacador vs. o inverso do adversário, não com granularidade de rally.
- **Atualização em tempo quase real:** `tennis_atp`/`tennis_wta` não são atualizados diariamente; pode haver defasagem de dias/semanas entre uma partida e sua disponibilização no CSV. Relevante só a partir da Fase 7 (previsões de partidas atuais), não agora.
- **Odds:** nenhuma fonte gratuita e automatizável de odds foi encontrada — `tennis-data.co.uk` tem os dados mas proíbe coleta automatizada. Isso é aceitável agora (CLAUDE.md §14 diz que odds não são requisito inicial), mas deve ser sinalizado como bloqueio futuro para a Fase 8/9: a coleta de odds provavelmente exigirá decisão explícita do usuário (fonte paga, ou coleta manual pontual) quando chegarmos lá.
- **Torneios ITF/Challenger:** cobertura de MatchStats em Challengers só a partir de 2008, e ITF/Futures não tem MatchStats detalhado. Não é bloqueio para o escopo atual (tour-level), mas limita expansão futura para níveis mais baixos.

## Recomendação para a Fase 1

Usar como fontes primárias, nesta ordem:

1. **`tennis_atp`** e **`tennis_wta`** (Jeff Sackmann, GitHub) — base histórica principal para os 7 mercados, via download HTTP direto dos CSVs. Cobrem exatamente as estatísticas por oportunidade exigidas em CLAUDE.md §5/§6, superfície, ranking point-in-time e `player_id` estável.
2. **`tennis_slam_pointbypoint`** como fonte complementar isolada, útil futuramente para validar modelos de tie-break em Slams (mercado 7).
3. **`tennis_MatchChartingProject`** como fonte de validação cruzada pontual, não como base — devido à cobertura parcial/enviesada.
4. **Não integrar** `tennis-data.co.uk` de forma automatizada nesta fase (conflito de licença com coleta por agente/bot). Reavaliar somente quando odds entrarem em escopo (Fase 8/9), e possivelmente como coleta manual do usuário.
5. **Não priorizar** scraping de Tennis Abstract (HTML) nem API oficial ATP/WTA (inexistente) na Fase 1.
6. Avaliar `TML-Database` apenas se, na prática, a defasagem de atualização do `tennis_atp` for um problema.

Aguardando aprovação para iniciar a Fase 1 (ingestão).
