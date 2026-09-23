# 018 — ARQUITETURA DA PWA (FASE 12 — PROJETO, SEM IMPLEMENTAÇÃO)

## 0. Escopo desta tarefa

Este documento é **só arquitetura e planejamento**. Nenhuma linha de código de
produto foi escrita nesta tarefa. Em particular, nada abaixo:

- reescreve o motor estatístico (`src/ingestion` … `src/forward`);
- altera modelos, probabilidades, calibração, thresholds, regras
  operacionais (`src/decision`) ou o forward test (`src/forward`);
- altera qualquer saída histórica em `data/outputs/`;
- cria automação de aposta ou integra uma casa de apostas automaticamente;
- tenta contornar o bloqueio anti-bot da Betano (já documentado como
  dead-end na memória do projeto e em `docs/015` seção 1).

A PWA é uma **camada de interface e operação** sobre o radar já existente
(Fases 0–11). Todo cálculo de probabilidade, odd justa, edge e classificação
continua vivendo em `src/`; a API só chama essas funções e formata o
resultado.

---

## 1. Auditoria da arquitetura atual

### 1.1 O que já existe e como as fases se encaixam

```
Fase 0-2  ingestão + normalização        -> data/processed/{atp,wta}/matches.parquet, players.parquet
Fase 3    features Serve x Return        -> data/processed/features/{atp,wta}/player_match_features.parquet
Fase 4-6  baselines/distribuições/seleção-> data/outputs/phase4..6
Fase 6.1  calibração                     -> data/outputs/phase6_1/selecao_metodo_por_mercado.csv
Fase 7    odds justas                    -> src/pricing (fórmulas, não persiste radar diário)
Fase 8    RADAR DIÁRIO (partidas futuras)-> data/outputs/phase8/precos_por_linha.parquet  <- fonte nº1 da PWA
Fase 8.1  atualização incremental        -> data/outputs/phase8_1 (radar recalculado com base nova, quando houver)
Fase 9    odds observadas (manual)       -> data/outputs/phase9/{odds_observed,comparison_with_model,daily_odds_check}
Fase 10   regras operacionais            -> data/outputs/phase10/opportunities_evaluated.parquet
Fase 11   forward test                   -> data/outputs/phase11/{forward_predictions,odds_snapshots,results,settlements,...}
```

Cada fase só lê a saída congelada da fase anterior — nunca recalcula nada
já decidido (essa é a regra que este documento também vai seguir: **a API
só lê e chama `src/`, nunca reimplementa fórmula**).

### 1.2 Pontos relevantes para a PWA (achados da auditoria)

| Achado | Onde | Implicação para a PWA |
|---|---|---|
| **Não existe fonte de calendário/agenda de torneios com data+hora+fuso.** `sources.load_raw_matches` (`src/radar/sources.py`) exige só `match_date` (data pura, sem hora nem timezone) — `REQUIRED_RAW_COLUMNS` em `src/radar/config.py` não tem `match_time`/`event_timezone`. | `src/radar/config.py`, `src/radar/sources.py` | A tela CALENDÁRIO (seção 6.1) precisa de uma fonte de dados **nova**, decoupled do arquivo que alimenta o motor estatístico — ver seção 5. |
| **`match_id` do radar é efêmero.** `f"FUTURE:{tour}:{raw_match_seq}"` (`src/radar/build.py::_match_context`), onde `raw_match_seq` é só o índice de linha do CSV bruto daquele dia. Ele não é estável entre execuções diferentes do radar (um novo `partidas_futuras_YYYYMMDD.csv` reindexa tudo). | `src/radar/build.py` | A API precisa de uma **chave natural estável** (tour + torneio + rodada + jogador A + jogador B + data) para casar calendário ↔ radar ↔ odds ↔ forward test entre execuções — ver seção 4.4 (risco R1). |
| **Betano não é acessível por automação** (HTTP 403 em cliente puro; Swiper de abas não responde a clique automatizado mesmo com Playwright). | `docs/015` seção 1; memória `bookmaker-access-dead-ends` | Confirma que "usuário tira print, sistema lê" (item 8/9 do pedido) é a única via legítima — nenhuma tentativa de navegação automática na Betano deve entrar na PWA. |
| **Pipeline de odds manuais já é robusto e testado ponta a ponta.** `scripts/record_odds.py` → `src/odds/build.py` → `src/decision/build.py` → `src/forward/build.py`, 241/241 testes (Fase 0–11). | `src/odds`, `src/decision`, `src/forward` | A API não precisa (e não deve) reimplementar casamento de linha, cálculo de edge ou classificação — só invocar essas funções com os dados já extraídos do print. |
| **Rótulos bilíngues PT/EN já existem** (`src/forward/labels.py`, usado em `daily_report`/`cumulative_dashboard`). | `src/forward/labels.py` | É lógica de **apresentação**, não de negócio — a PWA pode ter seu próprio dicionário de labels em `web/` sem violar "não copiar lógica para `api/`" (a regra vale para fórmulas/decisões, não para strings de UI). Ver seção 4.3. |
| **`stake_policy` é sempre `NOT_IMPLEMENTED`** (`src/decision/config.STAKE_POLICY_NOT_IMPLEMENTED`) e nenhum termo proibido (`FORBIDDEN_TERMS`) é usado em nenhuma explicação. | `src/decision/config.py` | A PWA deve **preservar** esse contrato: nunca inventar um valor de stake na tela, nunca usar linguagem de "aposta garantida" mesmo como texto decorativo. |
| **Todos os ledgers são append-only e imutáveis** (odds, oportunidades, previsões do forward test). | `src/odds/storage.py`, `src/forward/predictions.py`, etc. | Os endpoints de escrita da API (upload de print, confirmação, avaliação) devem ser **finos**: só delegam para essas funções de append já testadas, nunca escrevem parquet diretamente. |
| **`requirements.txt` ainda não tem FastAPI/uvicorn.** | `requirements.txt` | Vão ser adicionados no LOTE A, junto de `python-multipart` (upload de arquivo) e `Pillow` (validação de imagem) — sem adicionar nada que não seja estritamente necessário (CLAUDE.md §20). |
| **`daily_forward_workflow.py` já orquestra a rotina diária inteira** (`morning`/`odds`/`settle`/`report`) chamando só `src.radar.build` e `src.forward.build`. | `scripts/daily_forward_workflow.py` | A camada de serviços da API (seção 3.3) é, na prática, uma versão HTTP fina desse mesmo orquestrador — reduz risco de a API divergir da CLI. |

### 1.3 Conclusão da auditoria

A estrutura estatística está pronta e é suficiente para alimentar a PWA tal
como está. O trabalho genuinamente novo desta fase é:

1. uma camada de calendário/agenda (não existe hoje);
2. uma camada HTTP fina sobre `src/` (não existe hoje);
3. um front-end (não existe hoje);
4. um parser de print (não existe hoje, mas o fluxo de dados que ele
   alimenta — `record_odds.py`/`evaluate_opportunities.py` — já existe e é
   testado).

Nada nas Fases 0–11 precisa mudar para isso funcionar.

---

## 2. Proposta final de arquitetura

A estrutura sugerida pelo usuário já faz sentido e é adotada **sem
alteração** — é o padrão mínimo necessário (backend fino + frontend +
motor existente intocado), sem microsserviços, sem broker de mensagens, sem
banco de dados novo (os parquets/CSVs de `data/` continuam sendo a fonte de
verdade; ver seção 9 sobre por que não introduzir Supabase/Postgres agora,
conforme CLAUDE.md §20).

```
TENNIS_RADAR/
│
├── api/                        # FastAPI — camada HTTP fina sobre src/
│   ├── main.py                 # cria o app, CORS (só localhost), monta routers
│   ├── deps.py                 # dependências comuns (paths de dados, settings)
│   ├── routes/
│   │   ├── calendar.py         # GET /api/calendar
│   │   ├── radar.py            # GET /api/radar/today
│   │   ├── matches.py          # GET /api/matches/{match_key}
│   │   ├── screenshots.py      # POST /api/screenshots, POST /api/screenshots/{id}/confirm
│   │   ├── odds.py             # POST /api/odds/evaluate
│   │   ├── forward.py          # GET /api/forward/summary, /api/forward/details
│   │   └── settings.py         # GET/PUT /api/settings
│   ├── services/                # orquestração fina — chama src/, nunca reimplementa
│   │   ├── calendar_service.py
│   │   ├── radar_service.py
│   │   ├── screenshot_service.py
│   │   ├── odds_service.py
│   │   └── forward_service.py
│   └── schemas/                 # Pydantic — contratos de request/response (seção 8)
│       ├── calendar.py
│       ├── radar.py
│       ├── screenshots.py
│       ├── odds.py
│       └── forward.py
│
├── web/                         # React + TypeScript + Vite + Tailwind, PWA
│   ├── src/
│   │   ├── pages/                # as 7 telas da seção 6
│   │   ├── components/
│   │   ├── api/                  # cliente HTTP tipado (espelha api/schemas)
│   │   ├── i18n/                  # labels PT/EN (independente de src/forward/labels.py)
│   │   └── lib/timezone.ts        # conversão de fuso no cliente (Intl/date-fns-tz)
│   ├── public/
│   │   ├── manifest.json
│   │   └── icons/
│   ├── vite.config.ts            # plugin PWA (vite-plugin-pwa), proxy /api -> localhost:8000
│   └── package.json
│
├── src/                         # INTOCADO — motor estatístico (Fases 0-11)
│   └── screenshot_parser/        # ÚNICO módulo novo dentro de src/ (ver seção 7)
│       ├── config.py
│       ├── mapping.py            # regras Betano "X+" -> "Over (X-1).5" (item da instrução)
│       ├── validation.py         # regras de coerência (seção 7.4)
│       └── extractor.py          # interface Extractor + ManualExtractor (seção 7.3)
│
├── scripts/                     # INTOCADO (mais scripts/dev, seção 12, no LOTE I)
├── data/
│   ├── raw/
│   │   ├── calendar/                    # NOVO — agenda com data/hora/fuso (seção 5)
│   │   ├── bookmaker_screenshots/       # NOVO — imagem original, nunca apagada (item da instrução)
│   │   └── bookmaker_extracted/         # NOVO — JSON extraído + validado, auditoria
│   └── outputs/                 # INTOCADO
└── docs/
    └── 018_PWA_ARQUITETURA.md   # este documento
```

**Por que não seguir com algo diferente do sugerido**: a alternativa mais
comum seria "colocar tudo num app Next.js full-stack" — descartada porque
misturaria a camada Python (onde `src/` já vive, testado, 241 testes) com
a camada de UI, forçando reescrever o motor em outra linguagem ou criar uma
ponte estranha. FastAPI + React separados, com Vite fazendo proxy para a
API em dev, é o caminho de menor fricção e menor acoplamento.

---

## 3. Fluxo completo da aplicação

### 3.1 Fluxo ponta a ponta (mapeado item a item do pedido)

```
1. GET /api/calendar?from=hoje&to=+3d
       -> calendar_service monta a agenda (seção 5), já convertida para
          America/Sao_Paulo
2-3. tela CALENDÁRIO mostra hoje/amanhã/+3 dias, com filtros ATP/WTA/torneio
4. GET /api/radar/today
       -> radar_service lê data/outputs/phase8/precos_por_linha.parquet
          (ou roda src.radar.build.run() se `?refresh=true` — ver seção 3.3)
5. tela RADAR DO DIA junta calendário + radar pela chave natural (seção 4.4)
   e separa VALE CONFERIR / OBSERVAR / DESCARTADOS
6. usuário abre a Betano manualmente (fora da PWA, sem link algorítmico
   automatizado — só um link estático de busca, se necessário)
7. usuário tira print das abas Aces / Games Mais-Menos
8. tela ENVIAR PRINT: POST /api/screenshots (multipart) grava a imagem
   original em data/raw/bookmaker_screenshots/ (nunca apagada)
9. screenshot_service chama src.screenshot_parser.extractor (seção 7) para
   propor mercado/jogador/linha/lado/odd
10. src.screenshot_parser.mapping normaliza "6+" -> "Over 5.5" etc.
11. src.screenshot_parser.validation roda as checagens da seção 7.4;
    se algo for inconsistente, a resposta já vem marcada
    needs_confirmation=true (nunca grava automaticamente)
12. tela RESULTADO... na verdade a confirmação acontece ainda na tela
    ENVIAR PRINT/LEITURA DO PRINT — usuário corrige se precisar
13. POST /api/screenshots/{id}/confirm grava o JSON final em
    data/raw/bookmaker_extracted/ (auditoria) e SÓ ENTÃO chama
    scripts.record_odds equivalente (src.odds.build.run) -> Fase 9
14. POST /api/odds/evaluate roda src.decision.build (Fase 10) sobre a nova
    observação e devolve a classificação
15. tela RESULTADO DA ANÁLISE mostra probabilidade / odd justa / odd mínima
    / odd da Betano / classificação (linguagem simples, seção 6.6)
16. usuário decide salvar no Forward Test -> POST /api/forward/register
    (chama src.forward.build.register_day(), que só registra o que já foi
    classificado — nunca recalcula)
17. tela FORWARD TEST consome GET /api/forward/summary (resumo simples) e
    GET /api/forward/details (Brier/Log Loss/CLV/Paper ROI, só na aba
    "Detalhes técnicos")
```

### 3.2 O que a PWA NUNCA faz (herdado das fases anteriores, reafirmado aqui)

- Nunca abre a Betano em iframe/webview/automação dentro da PWA.
- Nunca calcula probabilidade/odd justa/edge no frontend nem em `api/` —
  sempre delega para `src/`.
- Nunca escreve "aposta garantida"/"lucro certo"/"aposta segura" em nenhuma
  tela (mesmo texto decorativo/marketing da própria PWA).
- Nunca grava uma leitura de print automaticamente sem confirmação humana
  quando a validação (seção 7.4) sinalizar inconsistência.
- Nunca sobrescreve dado bruto (`data/raw/`) — só acrescenta.

### 3.3 Onde entra `refresh`/execução do pipeline

A PWA **não roda o pipeline em background sozinha** (nada de scheduler
automático nesta fase — seria antecipar operação/automação, fora do
escopo). Os únicos gatilhos de execução do motor são ações explícitas do
usuário na UI, mapeadas 1:1 para os mesmos comandos que já existem na CLI:

| Ação na UI | Chama (via `api/services/`) | Equivalente CLI já existente |
|---|---|---|
| Botão "Atualizar radar do dia" | `src.radar.build.run()` | `scripts/build_daily_radar.py` |
| Confirmar leitura de print | `src.odds.build.run(entries=[...])` | `scripts/record_odds.py` |
| Ver resultado da análise | `src.decision.build.run()` (ou reavaliação pontual) | `scripts/evaluate_opportunities.py` |
| Salvar no Forward Test | `src.forward.build.register_day()` | `scripts/forward_register.py` |
| Registrar resultado real (tela Forward Test, ação manual futura) | `src.forward.build.record_match_result()` + `settle_day()` | `scripts/forward_settle.py` |

Isso significa que a API é, por design, um invólucro fino em torno do que
`scripts/daily_forward_workflow.py` já faz — reduz o risco de a PWA e a CLI
divergirem em comportamento.

---

## 4. Contratos frontend/backend — decisões estruturais

### 4.1 Identificação de partida: `match_key` (natural) vs `match_id` (do radar)

Como descrito na auditoria (seção 1.2), `match_id` do radar
(`FUTURE:{tour}:{seq}`) não é estável entre execuções. A API introduz um
identificador **derivado, não persistido no motor**, usado só para navegação
na PWA:

```
match_key = slugify(f"{tour}:{tournament}:{round}:{player_a_norm}:{player_b_norm}:{match_date}")
```

`match_key` nunca é gravado em `data/outputs/` (não é uma mudança no motor)
— é calculado em `api/services/` a partir dos campos já existentes tanto no
calendário quanto no radar, e usado só como chave de rota
(`GET /api/matches/{match_key}`) e de junção entre as fontes. O `match_id`
real do radar continua sendo usado internamente sempre que a API precisa
chamar `src/` (ex.: registrar odds, que já usa `match_id`/`player`/`line`
como chave — Fase 9).

### 4.2 Fuso horário: nunca offset fixo, sempre IANA

Todo campo de data/hora de partida trafega em **3 formas** (nunca uma
conversão manual com offset):

```json
{
  "event_datetime_original": "2026-09-23T14:00:00",
  "event_timezone": "Asia/Shanghai",
  "event_datetime_utc": "2026-09-23T06:00:00Z",
  "event_datetime_sao_paulo": "2026-09-23T03:00:00-03:00"
}
```

Cálculo: backend usa `zoneinfo` (stdlib Python ≥3.9, já disponível — nenhuma
dependência nova) para gerar `event_datetime_utc`/`event_datetime_sao_paulo`
a partir de `event_datetime_original` + `event_timezone`. O frontend nunca
recalcula fuso — só formata `event_datetime_sao_paulo` (e opcionalmente
`event_datetime_original` lado a lado) com `Intl.DateTimeFormat`.

### 4.3 Labels/i18n não duplicam lógica de negócio

`src/forward/labels.py` (Fase 11) já mapeia códigos como `CANDIDATO_FRACO`
ou `aces_player` para texto PT/EN — isso é usado pelos relatórios de texto
da CLI (`daily_report`/`cumulative_dashboard`). A API **não** reaproveita
esse módulo para montar HTML/JSON de tela: ela expõe os **códigos brutos**
(`classification: "CANDIDATO_FRACO"`, `market: "aces_player"`), e o
frontend mantém seu próprio dicionário de apresentação
(`web/src/i18n/labels.ts`). Isso evita acoplar o frontend a um módulo
Python, e evita que a API vire um lugar de "lógica de texto" — os dois
dicionários podem divergir levemente sem quebrar nada, porque nenhum dos
dois decide classificação, só a exibe.

### 4.4 Regra de ouro dos contratos

Nenhum schema de resposta da API inventa um campo calculado que não exista
em `src/`. Se um valor não existe (ex.: `player_rank` é `<NA>` na Fase 8,
seção 10 do docs/013), o contrato expõe `null` explicitamente — a PWA
mostra "não disponível", nunca omite silenciosamente nem calcula um
substituto.

---

## 5. Estratégia de calendário e fuso horário

### 5.1 O problema real (achado da auditoria, seção 1.2)

Hoje o radar (Fase 8) só recebe `match_date` (uma data, sem hora nem fuso)
via `data/raw/phase8/partidas_futuras_*.csv`. Isso é suficiente para o
motor estatístico (que não usa hora do jogo em nenhuma fórmula), mas
insuficiente para a tela CALENDÁRIO, que precisa de hora local do torneio +
conversão para `America/Sao_Paulo`.

### 5.2 Decisão: fonte de calendário separada, nunca dentro do motor

Em vez de estender `REQUIRED_RAW_COLUMNS` do radar (o que tocaria em código
do motor estatístico — proibido nesta tarefa), a PWA introduz uma fonte
**paralela e desacoplada**:

```
data/raw/calendar/agenda_YYYYMMDD.csv
```

Colunas: `tour, tournament, round, player_a_raw, player_b_raw, surface,
event_datetime_original, event_timezone, source_url, collected_at`.

`CalendarProvider` (interface, `api/services/calendar_service.py` chamando
uma implementação nova — ver decisão de módulo abaixo) expõe:

```python
class CalendarProvider(Protocol):
    def list_tournaments(self, date_from: date, date_to: date) -> list[Tournament]: ...
    def list_matches(self, date_from: date, date_to: date) -> list[MatchSchedule]: ...
    def get_match(self, match_key: str) -> MatchSchedule | None: ...
```

Implementação inicial: **`ManualFileCalendarProvider`**, lê
`data/raw/calendar/agenda_*.csv` (preenchido manualmente, mesma disciplina
já usada em `data/raw/phase8/partidas_futuras_*.csv` — CLAUDE.md §12: fonte
estruturada local antes de qualquer scraping). Uma segunda implementação
(`PublicSourceCalendarProvider`, fase futura, não desta tarefa) poderia ler
de uma fonte pública quando uma ficar disponível sem bloqueio — a interface
já deixa esse ponto de extensão pronto, sem forçar a decisão agora
(CLAUDE.md §12/§20: não bloquear a PWA por falta de API, não overengineer
a interface além do necessário).

**Onde este código mora**: como é leitura/normalização de dado bruto (não
UI, não framework HTTP), fica em `src/calendar/` (`providers.py`,
`manual_provider.py`, `config.py`), espelhando o padrão de módulo já usado
em `src/radar`/`src/odds`. `api/services/calendar_service.py` só instancia
o provider e adapta para os schemas Pydantic.

### 5.3 Junção calendário ↔ radar

A junção usa a **chave natural** da seção 4.1 (`tour + tournament + round +
player_a_norm + player_b_norm + match_date`), nunca o `match_id` efêmero do
radar. `player_a_norm`/`player_b_norm` reaproveitam a mesma normalização de
nome já usada em `src/radar/identity.py` (sem duplicar a lógica — chamada
diretamente).

### 5.4 Status da partida

`status` (`futuro` / `próximo` / `iniciado` / `encerrado`) é derivado no
backend a partir de `event_datetime_utc` vs. `now()` — nunca calculado no
frontend (para não depender do relógio do dispositivo do usuário estar
certo, e para manter uma única fonte de verdade testável).

---

## 6. Telas e componentes

Nenhuma tela além das 7 pedidas + Configurações é criada.

### 6.1 CALENDÁRIO

- Fonte: `GET /api/calendar`.
- Filtros client-side sobre a resposta já paginada por data (ATP/WTA,
  torneio, "somente selecionados pelo radar" cruza com
  `GET /api/radar/today` pelo `match_key`).
- Cada card mostra os dois horários (original do torneio + São Paulo) lado
  a lado — nunca só um, para o usuário conseguir conferir.

### 6.2 RADAR DO DIA

- Fonte: `GET /api/radar/today`, já teoricamente enriquecida com
  `match_key` (seção 4.1) para permitir navegação para o Detalhe.
- 3 seções (VALE CONFERIR ODDS / OBSERVAR / DESCARTADOS) — mapeamento
  direto de `is_candidate`/`is_radar_candidate` (Fase 8, `src/radar/candidates.py`).
  "DESCARTADOS" nesta tela é sobre **seleção de mercado do radar** (Fase 8),
  não sobre a classificação operacional de odds (Fase 10, que só existe
  depois que uma odd é registrada) — os dois usos da palavra "descartar"
  não devem ser confundidos na UI; texto de apoio deixa isso explícito.
- "Motivo da seleção" = `candidate_blockers` (quando vazio, motivo é
  "atende todos os critérios"; quando não, lista os critérios que faltaram
  — linguagem já simples o suficiente para mostrar quase literalmente).

### 6.3 DETALHE DA PARTIDA

- Fonte: `GET /api/matches/{match_key}`.
- Mercados: só os 3 realmente modelados (`aces_player`, `total_aces_match`,
  `double_faults_player`) — nada de "Games Mais/Menos" aparecer como se o
  modelo tivesse probabilidade para ele (ver seção 6.3.1).

**6.3.1 — Games Mais/Menos ainda não é modelado.** O pedido do usuário
lista "Games Mais/Menos / Total Games Over/Under" como mercado da tela de
Detalhe e também pede que o parser saiba ler essa aba (seção 7). Isso é
consistente: **a coleta é permitida e útil desde já** (alimenta
`data/raw/bookmaker_extracted/` para auditoria/uso futuro, e a memória do
projeto documenta o `parse_games` já escrito em
`scripts/collect_betano_two_tabs.py`, reaproveitável), mas **a comparação
com o radar não existe** para esse mercado (`total_games` não está em
`ALLOWED_MARKETS` de nenhuma fase 5–10 — só existe quando os dados
sustentarem esse mercado, CLAUDE.md §1/§19). A tela deve mostrar
literalmente algo como "Mercado ainda não modelado pelo radar — leitura
registrada para auditoria" em vez de inventar uma probabilidade. Isso é uma
decisão explícita, não um bug a corrigir depois.

### 6.4 ENVIAR PRINT

- Drag-and-drop, colar (evento `paste` do clipboard), ou seleção de
  arquivo — PNG/JPG/WEBP.
- Campos de contexto (partida via busca/autocomplete sobre
  `GET /api/radar/today`, tipo de aba) são preenchidos antes do upload
  sempre que possível, para o parser (seção 7) já saber o que procurar —
  mas **nunca são obrigatórios** (o pedido do usuário also cobre
  `opponent`/`tournament` opcionais, já suportado por `record_odds.py`).

### 6.5 LEITURA DO PRINT (mostrada dentro do fluxo de Enviar Print — item 5 do pedido)

- Mostra a imagem enviada lado a lado com os campos extraídos, editáveis.
- Se `needs_confirmation=true` (seção 7.4), todos os campos aparecem
  destacados com "CONFIRME ESTA LEITURA" — nenhum campo é salvo até o
  usuário confirmar/corrigir e apertar "Confirmar".

### 6.6 RESULTADO DA ANÁLISE

- Fonte: `POST /api/odds/evaluate` (chamado automaticamente após
  confirmação do print, ou manualmente para uma odd digitada direto).
- Layout: probabilidade, odd justa, odd mínima (do menor edge configurado
  — hoje o piso por mercado, `src/decision/config.MARKET_MIN_EDGE_LABEL`),
  odd da casa, classificação em destaque — exatamente como os exemplos do
  pedido do usuário.
- Classificação exibida usa os 5 estados da Fase 10
  (`DESCARTAR`/`OBSERVAR`/`CANDIDATO_FRACO`/`CANDIDATO`/`CANDIDATO_FORTE`),
  traduzidos para "PASSOU DO LIMITE"/"NÃO PASSOU DO LIMITE" **apenas como
  agrupamento visual simples** (`CANDIDATO*` → "PASSOU DO LIMITE";
  `OBSERVAR`/`DESCARTAR` → "NÃO PASSOU DO LIMITE"), sem esconder o estado
  técnico exato (disponível num "ver detalhes").
- Nunca usa termos da lista proibida (`src/decision/config.FORBIDDEN_TERMS`)
  em nenhum texto de UI, nem em textos de marketing/ajuda da própria PWA.

### 6.7 FORWARD TEST

- Resumo simples: `GET /api/forward/summary` (contagens por classificação/
  settlement — mapeamento direto de `daily_report`/`cumulative_dashboard`
  já existentes, mas como JSON estruturado em vez de texto).
- "Detalhes técnicos" (Brier/Log Loss/CLV/Paper ROI): `GET /api/forward/details`,
  numa aba/seção separada e sempre com o `N` da amostra ao lado (herdando a
  regra do docs/017 seção 15: "nenhum número desta fase deve circular sem o
  N ao lado").

### 6.8 CONFIGURAÇÕES

- `timezone` (default `America/Sao_Paulo`), `bookmaker_padrao` (default
  `Betano` — mas livre, já que `bookmaker` é campo genérico desde a Fase 9),
  `diretorio_de_dados` (leitura, aponta pra `data/`, não editável em campo
  livre nesta fase — só informativo, para não permitir apontar a PWA para
  um diretório fora do projeto sem querer), `modo_escuro_claro`,
  `mostrar_detalhes_tecnicos` (boolean, controla visibilidade da seção
  6.7 "Detalhes técnicos" e de qualquer bloco técnico em outras telas).
- Persistência: arquivo local (`data/config/pwa_settings.json`) — não
  precisa de banco de dados para 6 campos (CLAUDE.md §20).

---

## 7. Estratégia de leitura de print (`screenshot_parser`)

### 7.1 Por que um módulo isolado, e onde ele mora

Pedido explícito do usuário: "criar uma camada isolada: screenshot_parser".
Fica em `src/screenshot_parser/` (não em `api/`) porque:

- é lógica de normalização/validação de dado, do mesmo tipo do que já
  existe em `src/odds/matching.py` — não é lógica de framework web;
- assim pode ser testado com `pytest` exatamente como todo o resto do
  projeto (`tests/test_screenshot_parser.py`, seguindo o padrão dos outros
  13 arquivos de teste), sem precisar subir a API;
- `api/services/screenshot_service.py` só chama esse módulo e faz a ponte
  HTTP (upload multipart, resposta JSON).

### 7.2 Responsabilidades (exatamente as 4 pedidas)

```
src/screenshot_parser/
  extractor.py    -- recebe imagem, devolve valores brutos candidatos
  mapping.py      -- normaliza rótulo da casa ("6+") -> linha do modelo (Over 5.5)
  validation.py   -- roda as checagens da seção 7.4; nunca deixa passar
                     sem validação
  audit.py        -- grava imagem original + JSON extraído + metadados,
                     nunca apaga a imagem original
```

### 7.3 Extração: interface plugável, começando pelo caminho mais simples

O pedido cobre "uma camada de leitura de imagem" sem exigir um provedor de
IA específico. Seguindo CLAUDE.md §20/§21 (não adicionar ferramenta só
porque está disponível; simplicidade primeiro) e a experiência real desta
sessão (o parser textual de `collect_betano_two_tabs.py` funciona, mas o
copiar-colar da página não traz os valores numéricos — só a leitura visual
funcionou), a extração é desenhada como uma interface pequena com **duas
implementações possíveis**, escolhida na Fase de implementação (LOTE F, não
decidido nesta tarefa):

```python
class Extractor(Protocol):
    def extract(self, image_path: Path, hints: ExtractionHints) -> list[RawReading]: ...
```

| Implementação | Como funciona | Quando usar |
|---|---|---|
| `ManualExtractor` (recomendada para o LOTE F inicial) | A tela mostra a imagem ampliada e o usuário digita os valores que vê num formulário curto (mercado já vem pré-selecionado do contexto da tela Enviar Print); o "parser" aqui é só a normalização/validação (seções 7.2-7.4), não OCR. | MVP — zero dependência nova, zero custo, zero risco de erro de leitura automática silencioso. |
| `VisionExtractor` (opcional, fase futura) | Chama um modelo de visão (ex.: via API) para propor os valores, que o usuário ainda confirma/corrige na mesma tela (nunca grava sem confirmação — item da instrução). | Só se o volume de prints tornar a digitação manual um gargalo real — decisão a tomar com dados de uso, não antecipada aqui. |

Isso responde à pergunta "como a PWA vai ler o print" sem comprometer o
projeto com uma dependência de IA paga antes de saber se é necessária — e
sem contradizer a "mágica" já demonstrada nesta sessão (leitura visual por
IA), que fica disponível como upgrade de implementação, não como requisito
do LOTE F.

### 7.4 Validação (regras exatas do pedido, antes de liberar para o radar)

`validation.py::validate_reading(readings: list[RawReading]) -> ValidationResult`:

**Aces (por jogador e total):**
- linhas `X+` devem ser estritamente crescentes dentro da mesma leitura;
- odds devem, em geral, crescer conforme a linha aumenta (Over) — violação
  gera aviso, não bloqueio automático (mercados reais ocasionalmente têm
  ruído de arredondamento de casa de apostas);
- jogador citado precisa bater com um dos dois jogadores da partida
  selecionada (`player_a`/`player_b` do contexto da tela);
- nenhuma odd `<= 1.00`.

**Games:**
- linhas coerentes (mesma linha para Over e Under do mesmo par);
- Over e Under sempre emparelhados na mesma linha;
- odds válidas (`> 1.00`).

Qualquer violação (exceto as marcadas como "aviso") resulta em
`needs_confirmation=true` na resposta de `POST /api/screenshots` — a API
**nunca** chama `src.odds.build.run()` automaticamente nesse caso; espera o
`POST /api/screenshots/{id}/confirm` explícito do usuário, com os valores
já corrigidos se necessário (exatamente o comportamento de
"CONFIRME ESTA LEITURA" pedido).

### 7.5 Mapeamento Betano → linha do modelo (regra exata do pedido)

```python
# mapping.py
def betano_to_model_line(display: str, market: str) -> float:
    """'6+' -> 5.5, '10+' -> 9.5, etc. -- Betano usa "no mínimo N", o
    modelo usa "Over N-0.5". Regra única, testável isoladamente."""
```

Tabela de exemplo do pedido (aces por jogador, total de aces) e o caso de
Games (`"Mais de 22.5"` → `Over 22.5`, já na mesma convenção — sem
transformação de "N+" necessária) ficam cobertos pelo mesmo módulo, com
testes por mercado.

### 7.6 Auditoria (exatamente como pedido)

```
data/raw/bookmaker_screenshots/{screenshot_id}.{png|jpg|webp}   # original, nunca apagado
data/raw/bookmaker_extracted/{screenshot_id}.json                # leitura final confirmada
```

Cada JSON de auditoria grava: `screenshot_id`, `bookmaker`, `match_key`,
`market`, `readings` (bruto + normalizado), `extraction_method`
(`"manual"` ou o nome do extractor de visão usado), `validation_result`,
`confirmed_by_user_at`, `timestamp`. Nunca é reescrito — uma nova leitura
do mesmo print (reenvio) gera um novo `screenshot_id`.

---

## 8. Contratos de dados (schemas Pydantic)

Todos em `api/schemas/`, um arquivo por domínio. Campos `Optional`/`None`
explícitos onde o dado pode legitimamente não existir hoje (Fase 8 seção
10: `best_of`, `player_rank` ficam `<NA>`).

```python
# api/schemas/calendar.py
class Tournament(BaseModel):
    tour: Literal["ATP", "WTA"]
    tournament: str
    surface: Literal["Hard", "Clay", "Grass"]
    country: str | None = None

class MatchSchedule(BaseModel):
    match_key: str
    tour: Literal["ATP", "WTA"]
    tournament: str
    round: str
    surface: Literal["Hard", "Clay", "Grass"]
    player_a: str
    player_b: str
    event_datetime_original: datetime
    event_timezone: str                     # IANA, ex. "Asia/Shanghai"
    event_datetime_utc: datetime
    event_datetime_sao_paulo: datetime
    status: Literal["futuro", "proximo", "iniciado", "encerrado"]
    source_url: str | None = None
    collected_at: datetime

# api/schemas/radar.py
class RadarLine(BaseModel):
    match_key: str
    match_id: str                           # id efêmero do radar, uso interno
    tour: Literal["ATP", "WTA"]
    market: Literal["aces_player", "total_aces_match", "double_faults_player"]
    player_name: str | None = None          # None em total_aces_match
    line: float
    side: Literal["over", "under"]
    operational_probability: float
    fair_odds: float
    odd_minima_por_edge: dict[str, float]   # {"2pct": ..., "3pct": ..., ...}
    is_candidate: bool
    candidate_blockers: list[str]
    sample_bucket_career: str
    restricted: bool
    restricted_motivo: str | None = None
    extreme_probability: bool
    resolution_method_player: str | None = None
    resolution_method_opponent: str | None = None

class RadarCandidate(BaseModel):
    match_key: str
    tour: Literal["ATP", "WTA"]
    tournament: str
    player_a: str
    player_b: str
    n_markets_with_candidates: int
    n_candidate_lines_total: int
    is_radar_candidate: bool

# api/schemas/screenshots.py
class ScreenshotUpload(BaseModel):
    screenshot_id: str
    match_key: str | None = None
    tab_type: Literal["aces", "games_over_under"]
    stored_path: str                        # data/raw/bookmaker_screenshots/...

class ExtractedMarket(BaseModel):
    market: Literal["aces_player", "total_aces_match", "double_faults_player", "total_games"]
    player: str | None = None               # None em mercados de partida
    bookmaker_display: str                  # "6+", "Mais de 22.5", texto bruto
    model_line: float | None = None         # None quando mercado nao modelado (total_games)
    side: Literal["over", "under"]
    decimal_odds: float
    needs_confirmation: bool
    validation_warnings: list[str]

class ConfirmedMarket(ExtractedMarket):
    confirmed_by_user_at: datetime
    extraction_method: str                  # "manual" | nome do extractor de visao

# api/schemas/odds.py
class OddsEvaluation(BaseModel):
    match_key: str
    market: str
    player: str | None = None
    line: float
    side: Literal["over", "under"]
    operational_probability: float
    fair_odds: float
    odd_minima: float                       # do piso de edge do mercado (Fase 10)
    bookmaker: str
    decimal_odds: float
    model_edge: float
    status: str                             # rotulo de edge da Fase 9 (ABAIXO_DO_LIMITE..)
    classification: str                     # os 5 estados da Fase 10
    reasons: list[str]
    alerts: list[str]
    stake_policy: Literal["NOT_IMPLEMENTED"]
    data_staleness_days: int
    historical_data_cutoff: date

# api/schemas/forward.py
class ForwardSummary(BaseModel):
    n_predictions_total: int
    n_by_classification: dict[str, int]
    n_settled: int
    n_pending: int

class ForwardDetails(BaseModel):
    n: int                                  # amostra -- sempre junto de qualquer metrica
    brier_score: float | None = None
    log_loss: float | None = None
    clv_pct_mean: float | None = None
    paper_roi: float | None = None
    sample_size_checkpoints: dict[int, bool]
```

---

## 9. Endpoints (mínimos, conforme pedido)

| Método | Rota | Serviço chamado | Observação |
|---|---|---|---|
| `GET` | `/api/calendar` | `calendar_service.list_matches` | query params `date_from`, `date_to`, `tour`, `tournament` |
| `GET` | `/api/radar/today` | `radar_service.today` (lê `precos_por_linha.parquet`; `?refresh=true` roda `src.radar.build.run()`) | |
| `GET` | `/api/matches/{match_key}` | `radar_service.match_detail` + `calendar_service.get_match` | junta as duas fontes pela chave natural |
| `POST` | `/api/screenshots` | `screenshot_service.upload` (multipart) | grava original, roda extractor + validation |
| `POST` | `/api/screenshots/{id}/confirm` | `screenshot_service.confirm` | grava JSON de auditoria + chama `src.odds.build.run()` |
| `POST` | `/api/odds/evaluate` | `odds_service.evaluate` | roda `src.decision.build` sobre a observação recém-registrada; usado também para digitação manual de odd sem print |
| `POST` | `/api/forward/register` | `forward_service.register` | chama `src.forward.build.register_day()` |
| `GET` | `/api/forward/summary` | `forward_service.summary` | |
| `GET` | `/api/forward/details` | `forward_service.details` | |
| `GET` | `/api/settings` / `PUT` | `settings_service` | 6 campos da seção 6.8 |

Nenhum endpoint duplicado (ex.: não existe `/api/odds/compare` separado de
`/api/odds/evaluate` — é a mesma operação).

---

## 10. Modelo de dados (visão consolidada)

```
CalendarProvider (novo, src/calendar/)
   data/raw/calendar/agenda_*.csv
        |
        | join por chave natural (match_key)
        v
Fase 8 (existente) -- data/outputs/phase8/precos_por_linha.parquet
        |
        v
[ usuário confirma print ]
        |
        v
screenshot_parser (novo, src/screenshot_parser/)
   data/raw/bookmaker_screenshots/*.{png,jpg,webp}   (imutável)
   data/raw/bookmaker_extracted/*.json               (auditoria)
        |
        v
Fase 9 (existente) -- data/outputs/phase9/{odds_observed,comparison_with_model}
        |
        v
Fase 10 (existente) -- data/outputs/phase10/opportunities_evaluated.parquet
        |
        v
Fase 11 (existente) -- data/outputs/phase11/{forward_predictions,...}
```

Todo o bloco "Fase 8-11" é **lido, nunca escrito diretamente** pela API —
toda escrita passa pelas funções já testadas (`src.odds.build.run`,
`src.decision.build.run`, `src.forward.build.register_day` etc.).

---

## 11. Integração exata com as Fases 8–11

| Necessidade da PWA | Função chamada | Contrato de entrada/saída já testado em |
|---|---|---|
| Radar do dia | `src.radar.build.run()` | `tests/test_radar.py` (13 testes) |
| Registrar odd extraída do print | `src.odds.build.run(entries=[...])` (mesmo formato de `record_odds.py --input-json`) | `tests/test_odds.py` (23 testes) |
| Classificar oportunidade | `src.decision.build.run()` | `tests/test_decision.py` (33 testes) |
| Salvar no Forward Test | `src.forward.build.register_day()` | `tests/test_forward.py` (36 testes) |
| Registrar resultado real (fora do escopo desta entrega, mas mapeado) | `src.forward.build.record_match_result()` + `settle_day()` | idem |

A API não introduz nenhum novo formato de entrada para essas funções — os
`schemas` da seção 8 são serializados exatamente para o dicionário/DataFrame
que essas funções já esperam (mesmos campos de `OBSERVATION_COLUMNS`,
`ALLOWED_MARKETS`, etc., reaproveitados de `src/odds/config.py` e
`src/decision/config.py` — nunca redefinidos em `api/`).

---

## 12. Riscos técnicos

| # | Risco | Mitigação proposta |
|---|---|---|
| R1 | `match_id` do radar é efêmero (reindexado a cada CSV bruto do dia) — se o radar rodar de novo no mesmo dia, `match_key` (derivado, estável) precisa continuar resolvendo para o mesmo `match_id` novo. | `match_key` é sempre recalculado a partir de campos de conteúdo (não de posição), então continua estável entre execuções — mas isso deve ganhar um teste dedicado no LOTE C (calendário) antes de confiar nele em produção. |
| R2 | Fonte de calendário (`data/raw/calendar/agenda_*.csv`) é manual — mesmo risco de fragilidade/erro humano já aceito para `data/raw/phase8/partidas_futuras_*.csv`. | Documentar como limitação conhecida (mesmo padrão do docs/013 seção 10), não esconder. Reaproveitar, quando possível, a mesma fonte já usada para popular o CSV da Fase 8 manualmente, evitando digitar a agenda duas vezes. |
| R3 | Extração de print sem OCR/visão automática (MVP `ManualExtractor`) exige digitação do usuário — mais lento que a "mágica" de visão já demonstrada nesta sessão. | Aceito conscientemente para o MVP (zero dependência nova); interface `Extractor` já deixa o upgrade para um `VisionExtractor` pronto para plugar sem redesenhar a tela. |
| R4 | Betano continua bloqueada para qualquer automação — nenhuma tela deve sugerir abrir a Betano dentro de um webview controlado pela PWA (isso reintroduziria o mesmo bloqueio de Swiper/anti-bot já documentado). | UI só abre a Betano numa nova aba do navegador do usuário (`target="_blank"`), nunca embutida. |
| R5 | Ambiente local sem autenticação — qualquer pessoa na mesma máquina/rede (se o bind vazar de `localhost`) acessa os dados. | Backend só faz bind em `127.0.0.1` por padrão (nunca `0.0.0.0`); documentar isso explicitamente na Fase de implementação como requisito não-negociável do LOTE A. |
| R6 | Cache do service worker da PWA poderia, por engano, servir radar/odds desatualizados offline. | Cache-first só para assets estáticos (JS/CSS/ícones); network-only (sem fallback de cache) para toda rota `/api/*` — já decidido na seção "PWA" do pedido, reafirmado aqui como requisito de implementação. |
| R7 | Upload de imagem é a única entrada de arquivo do usuário na PWA — superfície de risco (arquivo malicioso, tamanho excessivo). | Validar `Content-Type` real (não só extensão) via `Pillow`/`imghdr`, limite de tamanho (ex.: 8 MB), nunca executar/interpretar o conteúdo do upload — só ler pixels. |
| R8 | `total_games` (Games Mais/Menos) pode ser coletado pelo parser mas não tem contrapartida de modelo — risco de o usuário achar que "não passou do limite" quando, na verdade, não há previsão alguma. | Tela de Detalhe/Resultado mostra estado explícito "mercado ainda não modelado" (seção 6.3.1), nunca um número substituto. |
| R9 | Dois servidores de dev (Vite + FastAPI) exigem CORS/proxy configurados corretamente, ou requisições falham silenciosamente em dev. | Vite `server.proxy` para `/api` → `http://127.0.0.1:8000` (LOTE B), evita CORS em dev; em produção local (LOTE I) o `.bat` pode servir o build do Vite via o próprio FastAPI (`StaticFiles`), eliminando CORS de vez. |
| R10 | Crescimento dos parquets append-only (odds, previsões) ao longo de meses de uso diário pode, eventualmente, deixar leituras mais lentas. | Não é um problema a resolver agora (volume atual é pequeno) — só registrado como algo a observar; solução futura (particionamento por data) não faz parte desta entrega. |

---

## 13. O que NÃO está sendo decidido nesta entrega

- Qual extractor de visão usar (se algum) — ver seção 7.3.
- Se/quando `total_games` vira mercado modelado — depende da Fase 5/6
  (CLAUDE.md §19, dados decidem, não esta tarefa).
- Autenticação multiusuário — fora de escopo enquanto o uso for local e
  pessoal.
- Deploy fora da máquina do usuário — a PWA é local-first por pedido
  explícito.
- Qualquer automação de aposta ou integração de casa de apostas — proibido
  pelo CLAUDE.md §15 e reafirmado na seção 0.

---

## 14. Plano de implementação em lotes

Cada lote é pequeno, testável isoladamente, e não avança para o próximo sem
autorização — mesma disciplina de "parar ao fim de cada fase" já usada em
todo o projeto (memória `phase-based-workflow`).

```
LOTE A — Fundação FastAPI
  - adicionar fastapi, uvicorn, python-multipart, pillow ao requirements.txt
  - api/main.py com bind 127.0.0.1, CORS restrito a localhost
  - api/deps.py (paths de data/), 1 endpoint de saude (GET /api/health)
  - teste: subir o servidor, GET /api/health -> 200

LOTE B — Fundação React/PWA
  - web/ com Vite + React + TypeScript + Tailwind
  - vite-plugin-pwa, manifest.json, icones placeholder, service worker
    (cache so de estaticos, sem cache de /api/*)
  - proxy /api -> 127.0.0.1:8000 em dev
  - 1 tela vazia de teste consumindo GET /api/health

LOTE C — Calendário
  - src/calendar/ (CalendarProvider, ManualFileCalendarProvider)
  - data/raw/calendar/agenda_*.csv (schema + validacao, testes)
  - GET /api/calendar + tela CALENDARIO
  - teste do risco R1 (match_key estavel entre execucoes)

LOTE D — Radar
  - api/services/radar_service.py sobre src.radar.build (sem alterar)
  - GET /api/radar/today, GET /api/matches/{match_key}
  - telas RADAR DO DIA e DETALHE DA PARTIDA

LOTE E — Upload de print
  - POST /api/screenshots (upload, storage em data/raw/bookmaker_screenshots/)
  - tela ENVIAR PRINT (drag-and-drop, colar, selecionar arquivo)

LOTE F — Parser/validação
  - src/screenshot_parser/ completo (mapping, validation, ManualExtractor)
  - POST /api/screenshots/{id}/confirm
  - tela LEITURA DO PRINT / CONFIRME ESTA LEITURA
  - tests/test_screenshot_parser.py

LOTE G — Avaliação
  - POST /api/odds/evaluate sobre src.odds.build + src.decision.build
  - tela RESULTADO DA ANALISE

LOTE H — Forward Test
  - POST /api/forward/register, GET /api/forward/summary, /details
  - tela FORWARD TEST (resumo simples + Detalhes tecnicos)

LOTE I — Launcher local
  - INICIAR_TENNIS_RADAR.bat (sobe FastAPI, sobe Vite/serve build, abre navegador)
  - tela CONFIGURACOES
```

Ordem de dependência: A → B podem ser paralelos entre si; C e D dependem de
A; E depende de B+D (precisa do contexto de partida); F depende de E; G
depende de F; H depende de G; I depende de tudo.

---

## 15. LOTE A — CONCLUÍDO

Implementada somente a fundação FastAPI, exatamente como planejado na
seção 14. Nenhum módulo de `src/` (Fases 0-11) foi alterado; nenhuma tela
(`web/`) foi criada; nenhum endpoint de domínio (calendário, radar,
screenshots, odds, forward) foi implementado.

### Arquivos criados

```
api/__init__.py
api/config.py           # Settings (env vars com defaults locais, sem pydantic-settings)
api/deps.py              # get_settings() cacheado, unica dependencia desta fase
api/main.py               # cria o app, CORS, handler de erro central, bind local
api/routes/__init__.py
api/routes/health.py      # GET /api/health
api/routes/info.py        # GET /api/info
api/schemas/__init__.py
api/schemas/common.py     # HealthResponse, InfoResponse
api/services/__init__.py
api/services/info_service.py  # le src/odds/config.py + src/forward/config.py + src/odds/pricing_compare.py
tests/test_api.py         # 13 testes novos (health, info, CORS, init, ausencia de efeitos colaterais)
```

### Dependências adicionadas (`requirements.txt`)

- `fastapi`
- `uvicorn`
- `httpx` — necessário para `fastapi.testclient.TestClient` (usado pelos
  testes de `tests/test_api.py`); nenhuma outra dependência nova.
- `python-multipart` e `pillow` (upload/validação de imagem) **não** foram
  adicionados — pertencem ao LOTE E, fora do escopo desta entrega.

### Endpoints disponíveis

| Método | Rota | Resposta |
|---|---|---|
| `GET` | `/api/health` | `{"status": "ok", "app": "Tennis Radar"}` |
| `GET` | `/api/info` | `app`, `api_version`, `timezone` (`America/Sao_Paulo`), `default_bookmaker` (lido de `src.odds.config.DEFAULT_BOOKMAKER` = `"Betano"`), `historical_data_cutoff` (lido via `src.odds.pricing_compare.staleness_warning`, reaproveitado sem alteração — hoje resolve para `2026-05-25`), `forward_version_id` (lido de `src.forward.config.FORWARD_VERSION_ID` = `"TENNIS_RADAR_V1_FORWARD"`) |

CORS liberado só para `http://localhost:5173` e `http://127.0.0.1:5173`
(hosts do Vite em dev, configurável via
`TENNIS_RADAR_API_ALLOWED_ORIGINS`); bind planejado para `127.0.0.1`
(`Settings.host`), nunca `0.0.0.0`. Handler central de exceção não tratada
devolve `{"detail": "Erro interno inesperado."}` com HTTP 500, sem vazar
stacktrace/mensagem interna.

### Testes novos

`tests/test_api.py` — 13 testes, cobrindo exatamente o pedido:

- `TestHealthEndpoint` (2): status 200 e corpo esperado; método não
  permitido (`POST`) devolve 405.
- `TestInfoEndpoint` (4): todos os campos presentes; `default_bookmaker`/
  `forward_version_id` batem literalmente com as constantes de `src/`
  (nunca redefinidos em `api/`); `timezone` default correto;
  `historical_data_cutoff` é `None` ou uma data ISO válida (nunca um valor
  inventado).
- `TestCorsConfiguration` (3): origem do Vite é ecoada no header CORS;
  origem externa arbitrária não é liberada; `Settings` nunca usa `"*"` ou
  bind público por padrão.
- `TestAppInitialization` (3): título/versão do app batem com `Settings`;
  rotas `/api/health` e `/api/info` estão registradas; exceção não tratada
  vira 500 genérico sem vazar detalhe interno.
- `TestNoSideEffectsOnExistingEngine` (1): chamar `/api/health` e
  `/api/info` não escreve, apaga nem modifica nenhum arquivo em
  `data/outputs/` (snapshot de mtimes antes/depois, idêntico).

### Resultado da suíte completa

```
python -m unittest discover -s tests -p "test_*.py"
Ran 266 tests in 438.100s
OK
```

266/266 testes passando (241 já existentes das Fases 0-11 + 25 novos desta
suíte, incluindo os 13 de `tests/test_api.py`) — zero regressão sobre o
motor estatístico.

---

## 16. LOTE B — CONCLUÍDO

Implementada somente a fundação React/PWA, exatamente como planejado na
seção 14. `src/` e `api/` não foram alterados; nenhuma tela de domínio
(calendário/radar/screenshots/odds/forward) foi implementada — só a tela
inicial provisória e a navegação, consumindo unicamente
`GET /api/health` e `GET /api/info` (LOTE A).

### Arquivos criados (`web/`)

```
web/index.html
web/vite.config.ts               # plugin React + Tailwind + PWA, proxy /api -> 127.0.0.1:8000, config do vitest
web/tsconfig.app.json             # (editado: tipos vite-plugin-pwa/client e jest-dom)
web/package.json
web/public/icons/icon.svg         # icone placeholder (favicon + manifest, tipo "any")
web/public/icons/maskable-icon.svg# icone placeholder com area de seguranca (manifest, tipo "maskable")
web/src/main.tsx                  # cria a raiz React, registra o service worker, monta o router
web/src/App.tsx                   # rotas: "/" (Home) + 4 rotas provisorias
web/src/App.test.tsx              # 5 testes da fundacao (ver abaixo)
web/src/index.css                 # import do Tailwind v4 + tokens de cor/tipografia (@theme)
web/src/layouts/AppLayout.tsx     # SideNav (desktop) + BottomNav (mobile) + area de conteudo
web/src/components/SideNav.tsx    # trilha de navegacao fixa no desktop
web/src/components/BottomNav.tsx  # barra de navegacao inferior no mobile
web/src/components/StatusIndicator.tsx  # bolinha + rotulo: carregando/online/offline
web/src/components/InfoRow.tsx    # linha rotulo/valor (sem cards, sem tabela)
web/src/pages/HomePage.tsx        # tela inicial: status + metadados de /api/info
web/src/pages/PlaceholderPage.tsx # "Em desenvolvimento" para Calendario/Radar/Forward/Configuracoes
web/src/services/api.ts           # unica camada de fetch() do frontend (getHealth/getInfo)
web/src/types/api.ts              # tipos TS espelhando api/schemas/common.py
web/src/test/setup.ts             # matchers do jest-dom + cleanup do Testing Library
```

`.gitignore` (raiz do projeto) atualizado com `web/node_modules/`,
`web/dist/`, `web/dev-dist/`, `web/.vite/`.

### Dependências de frontend adicionadas

Produção: `react`, `react-dom`, `react-router-dom` (navegação entre a Home e
as 4 áreas provisórias — sem essa lib, o roteamento client-side pedido no
"NAVEGAÇÃO" da instrução teria que ser reimplementado à mão).

Desenvolvimento/build: `vite`, `@vitejs/plugin-react`, `typescript`,
`@types/react`, `@types/react-dom` (base do stack pedido); `tailwindcss` +
`@tailwindcss/vite` (Tailwind CSS pedido, v4 via plugin nativo do Vite, sem
`postcss.config.js` separado); `vite-plugin-pwa` (manifest + service worker
pedidos); `vitest`, `@testing-library/react`, `@testing-library/jest-dom`,
`jsdom`, `@vitest/ui` (testes do frontend, pedidos explicitamente); `@types/node`
e `oxlint` vieram do scaffold padrão do Vite e não foram removidos por não
conflitarem com nada.

### Estrutura criada

Segue literalmente a árvore da seção 2/14: `web/public`, `web/src/{components,
layouts, pages, services, types}`, `App.tsx`, `main.tsx`, `index.html`,
`package.json`, `vite.config.ts`, `tsconfig.json`. Nenhuma pasta além dessas
foi criada.

### Design da tela inicial

Paleta e tipografia deliberadas para o assunto (radar de decisão rápida em
tênis), evitando o visual genérico de painel administrativo pedido para
evitar: fundo quase-preto com matiz verde-azulado de quadra à noite (`ink`/
`surface`), texto em branco-giz (`chalk`) e cinza esmaecido (`mist`), **dois
acentos funcionais e não decorativos** — azul de quadra dura (`court`) só
para navegação/interação, e amarelo-bolinha-de-tênis (`ball`) só para o
indicador "sistema online" (o "saibro" `clay` é usado só para o estado
offline/erro). Tipografia: "Space Grotesk" (títulos/rótulos estruturais) +
"IBM Plex Sans" (corpo/valores), carregadas via Google Fonts no `index.html`.
Layout em coluna única alinhada à esquerda, com filetes horizontais
separando os metadados (`InfoRow`) em vez de cards — atende ao pedido
explícito de evitar excesso de cards/tabelas e visual de painel
administrativo genérico. Navegação: trilha fixa à esquerda no desktop
(`SideNav`), barra inferior no mobile (`BottomNav`), ambas apontando para as
4 áreas futuras (Calendário/Radar/Forward Test/Configurações), que hoje só
mostram "Em desenvolvimento.".

### Estados da interface (tela Home)

`carregando` ("Verificando sistema…") → `online` (mostra os 4 campos de
`/api/info`: fuso horário, casa de apostas padrão, dados históricos até,
versão do forward test) → `offline` ("Não foi possível conectar ao servidor
local..."), sem nunca inventar um valor quando a API falha ou quando
`historical_data_cutoff` vem `null` (mostra "não disponível" nesse caso,
nunca uma data chutada).

### PWA configurada

`vite-plugin-pwa` com `registerType: "autoUpdate"`; manifest com `name`/
`short_name` = "Tennis Radar", `theme_color`/`background_color` =
`#0D1B1F`, ícones placeholder (`icon.svg` tipo "any", `maskable-icon.svg`
tipo "maskable"). Service worker gerado por `generateSW` faz **precache só
de assets estáticos do build** (`index.html`, JS, CSS, ícones, manifest —
verificado no `dist/sw.js`: 7 entradas, todas estáticas). O único
`registerRoute` do service worker é a rota de navegação SPA
(`NavigationRoute`) com `denylist: [/^\/api\//]` — nenhuma rota de runtime
caching foi registrada para `/api/*` (risco R6 da seção 12: nunca cache
agressivo para `/api/health`, `/api/info` ou futuras rotas de
calendário/radar/odds).

### Comunicação com a API

`web/src/services/api.ts` é a única camada de `fetch()` do frontend —
nenhum componente chama `fetch()` diretamente. Em dev, `vite.config.ts`
configura `server.proxy` de `/api` para `http://127.0.0.1:8000`, então o
frontend só referencia caminhos relativos (`/api/health`, `/api/info`),
nunca host/porta hardcoded. Verificado manualmente nesta entrega: com o
FastAPI (LOTE A) rodando em `127.0.0.1:8000` e o Vite em `localhost:5173`,
`curl http://localhost:5173/api/health` e `.../api/info` devolveram as
mesmas respostas do backend direto, e `GET /` devolveu HTTP 200.

### Testes novos (`web/src/App.test.tsx`, `npm run test` = `vitest run`)

5 testes, cobrindo exatamente o mínimo pedido:

- renderização da aplicação + estado "carregando" antes da resposta da API;
- estado "Sistema online" com os 4 campos de `/api/info` renderizados
  corretamente (incluindo a data formatada `25/05/2026`);
- estado "Sistema indisponível" quando `/api/health` falha, sem nenhum
  campo de metadado inventado e sem sequer chamar `/api/info`;
- `historical_data_cutoff: null` renderiza "não disponível", nunca uma data
  inventada;
- navegação provisória: clicar em "Radar" mostra "Em desenvolvimento.".

### Resultado do build de produção

```
npm run build   (tsc -b && vite build)
✓ 34 modules transformed
dist/manifest.webmanifest, dist/index.html, dist/assets/*.css, dist/assets/*.js
PWA v1.3.0 — mode generateSW — precache 7 entries (275.77 KiB)
dist/sw.js, dist/workbox-*.js gerados
```

Build e checagem de tipos (`tsc -b`) concluídos sem erros.

### Resultado da suíte Python completa (pós-LOTE B)

```
python -m unittest discover -s tests -p "test_*.py"
Ran 266 tests in 497.165s
OK
```

266/266 testes passando — mesma contagem do LOTE A (seção 15), zero
regressão sobre `src/`/`api/` (LOTE B só adicionou arquivos em `web/`, que
não é importado por nenhum módulo Python). Execução em primeiro plano, saída
completa capturada em `full_suite_output_lote_b.txt`. Os dois trechos
"ruidosos" no meio da saída são esperados e pré-existentes, não falhas: o
traceback de `RuntimeError` deliberadamente levantado pelo teste do handler
central de erro (`tests/test_api.py`, confirma que detalhe interno não
vaza) e a mensagem de erro de `argparse` do teste de validação de CLI de
`daily_forward_workflow.py`.

---

## 17. LOTE C — CONCLUÍDO

Implementado somente o calendário, exatamente como planejado na seção 14:
`src/calendar/` (provider + validação + `match_key`), `data/raw/calendar/
agenda_*.csv` (schema + validação + testes), `GET /api/calendar` e a tela
CALENDÁRIO. `src/radar`, `src/odds`, `src/forward` e o restante de `api/`
das fases anteriores não foram tocados; nenhuma tela/rota de Radar,
Screenshots, Odds ou Forward Test foi criada.

### Arquivos criados/alterados

```
src/calendar/__init__.py
src/calendar/config.py        # CALENDAR_RAW_DIR, REQUIRED_RAW_COLUMNS, SURFACES,
                               # limiares de status (secao 5.4)
src/calendar/providers.py     # Protocol CalendarProvider + dataclasses Tournament/MatchSchedule
src/calendar/match_key.py     # build_match_key (formula da secao 4.1), reaproveita
                               # normalize_name de src/radar/identity.py
src/calendar/manual_provider.py  # ManualFileCalendarProvider (le/valida agenda_*.csv,
                               # converte fuso original->UTC->Sao Paulo, deriva status)

api/schemas/calendar.py       # Tournament, MatchSchedule (Pydantic, espelha providers.py)
api/services/calendar_service.py  # instancia o provider, adapta para os schemas
api/routes/calendar.py        # GET /api/calendar (date_from, date_to, tour, tournament)
api/main.py                   # (editado: registra o router de calendario)

web/src/pages/CalendarPage.tsx      # tela CALENDARIO
web/src/pages/CalendarPage.test.tsx # 7 testes (ver abaixo)
web/src/services/api.ts       # (editado: getCalendar)
web/src/types/api.ts          # (editado: Tour, Surface, MatchStatus, MatchSchedule)
web/src/App.tsx               # (editado: rota "/calendario" aponta para CalendarPage)

tests/test_calendar.py        # 24 testes de src/calendar/ (unitarios)
tests/test_calendar_api.py    # 8 testes de integracao HTTP de GET /api/calendar
```

Nenhuma dependência nova (backend ou frontend) — `pandas` e `zoneinfo`
(stdlib) já cobrem leitura/validação de CSV e conversão de fuso; o
frontend reaproveita `fetch`/`Intl.DateTimeFormat` já usados no LOTE B.

### Decisões de implementação (dentro do escopo do LOTE C)

- **`match_key` mora em `src/calendar/`, não em `api/services/`.** A seção
  4.1 descreve o cálculo em termos gerais ("api/services/"), mas a seção
  5.2 já define que `CalendarProvider.get_match(match_key)` precisa
  resolver por essa chave — ou seja, o provider precisa calculá-la ao
  carregar cada linha. `api/services/calendar_service.py` continua só
  instanciando o provider e adaptando para Pydantic, sem lógica própria
  (mantém a regra da seção 5.2: nenhuma lógica de domínio mora em `api/`).
  `build_match_key` fica isolado em `src/calendar/match_key.py` para ser
  reaproveitado, sem duplicação, pelo `radar_service` no LOTE D.
- **`match_date` da chave é a data local do torneio** (`event_datetime_original.date()`,
  antes de qualquer conversão de fuso) — é o mesmo dia civil que
  `partidas_futuras_*.csv` (Fase 8) já usa em `match_date`, garantindo que
  calendário e radar produzam a mesma chave para a mesma partida quando o
  LOTE D fizer a junção.
- **Janela de datas (`date_from`/`date_to`) filtra pelo dia civil em
  `America/Sao_Paulo`**, não pelo dia do torneio — não estava definido
  explicitamente na seção 9, e como o propósito inteiro da conversão de
  fuso (seção 4.2) é a perspectiva do usuário no Brasil, filtrar pelo dia
  local do usuário é a leitura mais consistente com o resto do documento.
- **Limiares de status (`futuro`/`próximo`/`iniciado`/`encerrado`, seção
  5.4) são um heurística documentada, não um relógio de partida real** —
  não existe, em nenhuma fase do projeto, uma fonte de "hora real de
  término". `próximo` começa 2h antes do horário marcado; `iniciado` dura
  até 5h depois (teto generoso para partidas de 5 sets); constantes em
  `src/calendar/config.py`, isoladas para facilitar ajuste sem tocar no
  restante do provider.
- **`ManualFileCalendarProvider` lê TODOS os arquivos `agenda_*.csv` do
  diretório e combina**, ao contrário de `src/radar/sources.py` (que só lê
  o mais recente) — o calendário é, por natureza, uma janela de vários
  dias (`hoje` a `+3d`, seção 3.1), enquanto o radar processa um único
  lote diário.
- **Filtro "somente selecionados pelo radar" (seção 6.1) não foi
  implementado** — depende de `GET /api/radar/today`, que só existe no
  LOTE D. A tela mostra somente os filtros ATP/WTA e torneio nesta
  entrega; o cruzamento por `match_key` fica para o LOTE D, sem ampliar
  este lote.
- **`Tournament.country` sempre `None`** — não existe coluna de país em
  `agenda_*.csv` nesta fase; exposto como `null` explícito (seção 4.4),
  nunca inventado.

### Testes novos

`tests/test_calendar.py` — 24 testes de `src/calendar/`:

- `TestRawSourceValidation` (5): coluna obrigatória ausente, `tour`
  inválido, `surface` inválida, nome de jogador em branco, fuso horário
  desconhecido — todos rejeitados com `ValueError` explícito.
- `TestTimezoneConversion` (1): reproduz literalmente o exemplo da seção
  4.2 do documento (14:00 `Asia/Shanghai` → 06:00 UTC → 03:00
  `America/Sao_Paulo`).
- `TestStatusDerivation` (5): os quatro estados e as duas fronteiras
  (início da janela "próximo", fim da janela "iniciado").
- `TestListMatchesFiltering` (6): filtro por janela de data (dia civil em
  São Paulo), exclusão fora da janela, filtro por tour, filtro por
  torneio, ordenação por horário UTC, deduplicação de `list_tournaments`.
- `TestGetMatchByKey` (2): busca por chave existente e chave inexistente.
- `TestMultipleFilesCombined` (1): dois arquivos `agenda_*.csv` diferentes
  no mesmo diretório são combinados.
- `TestRiscoR1MatchKeyEstavel` (4): `build_match_key` é puro e
  determinístico; a chave não muda quando as mesmas partidas são gravadas
  em ordem diferente no CSV (simula uma recoleta/reexecução no mesmo dia);
  partidas diferentes produzem chaves diferentes; a chave é um slug
  seguro para URL.

`tests/test_calendar_api.py` — 8 testes de integração HTTP de
`GET /api/calendar` (rota registrada, resposta dentro da janela pedida,
janela sem dados devolve lista vazia, filtro de `tour`, `tour` inválido
devolve 422, `date_from`/`date_to` ausentes devolvem 422, conjunto de
campos da resposta bate exatamente com o schema, e a rota nunca escreve em
`data/raw/calendar/` — snapshot do arquivo bruto idêntico antes/depois).

`web/src/pages/CalendarPage.test.tsx` — 7 testes: estado de carregamento;
erro sem inventar dado (nenhuma partida fictícia aparece); os dois
horários lado a lado (torneio + São Paulo, exemplo da seção 4.2); estado
vazio quando a janela não tem partida; filtro por tour; filtro por
torneio; a chamada à API usa a janela padrão hoje→+3 dias (seção 3.1).

### Resultado do build de produção

```
npm run build
tsc -b && vite build
```

Sem erros de tipo. PWA `generateSW`, 7 entradas de precache estático
(278.45 KiB) — mesma contagem do LOTE B (nenhum asset novo: `CalendarPage`
não adiciona ícone/imagem). `dist/sw.js` conferido: a única ocorrência da
string `"api"` continua sendo o `denylist: [/^\/api\//]` da rota de
navegação — nenhuma entrada de `runtimeCaching` para `/api/*` foi
introduzida (regra da seção "PWA configurada" do LOTE B, reafirmada aqui).

### Verificação end-to-end real (servidor + proxy)

Além dos testes automatizados, o fluxo completo foi conferido com
processos reais (não só `TestClient`): FastAPI subido em
`127.0.0.1:8000` com um arquivo `agenda_*.csv` ilustrativo temporário
(uma partida de exemplo, claramente rotulada, removida ao final do
teste — nunca commitada), `curl` direto em `GET /api/calendar` e, em
seguida, o mesmo `curl` através do proxy `/api` do Vite dev server
(`localhost:5173`) — as duas respostas foram idênticas, confirmando que o
proxy configurado no LOTE B continua funcionando para a rota nova sem
nenhuma alteração em `vite.config.ts`. `data/raw/calendar/` fica vazio ao
final desta entrega (nenhum dado real de agenda foi coletado ainda — mesma
disciplina de população manual já aceita para `data/raw/phase8/`, risco R2
da seção 12); o diretório será populado pelo usuário quando houver uma
agenda real para carregar.

### Resultado da suíte Python completa (pós-LOTE C)

```
python -m unittest discover -s tests -p "test_*.py"
Ran 298 tests in 490.343s
OK
```

298/298 testes passando (266 já existentes do LOTE B + 32 novos desta
entrega: 24 de `tests/test_calendar.py` + 8 de `tests/test_calendar_api.py`)
— zero regressão sobre o motor estatístico ou sobre `api/`. Execução em
primeiro plano, saída completa capturada em `full_suite_output_lote_c.txt`.
Os mesmos dois trechos "ruidosos" do LOTE A/B continuam aparecendo no meio
da saída (traceback proposital de `tests/test_api.py` e mensagem de
`argparse` de `daily_forward_workflow.py`) — esperados, não falhas.

---

## 18. LOTE D — CONCLUÍDO

Implementado somente o radar do dia, exatamente como pedido: `GET
/api/radar/today`, a tela RADAR DO DIA, o cruzamento com o calendário
(LOTE C) pelo `match_key` compartilhado, e o filtro "somente selecionados
pelo radar" que tinha ficado pendente no LOTE C. Nenhum modelo, feature,
calibração, threshold, lógica de odds ou forward test foi alterado —
`src/radar`, `src/pricing`, `src/probabilistic`, `src/decision`, `src/odds`
e `src/forward` continuam exatamente como estavam. `src/calendar/` também
não foi tocado (só consumido). Leitura de print e LOTE E não foram
iniciados.

### Arquivos criados/alterados

```
api/schemas/radar.py          # RadarLine (Pydantic)
api/services/radar_service.py # adapter: le data/outputs/phase8/*.parquet,
                               # cruza com o calendario pelo match_key,
                               # agrupa decision_state -- nenhum recalculo
api/routes/radar.py           # GET /api/radar/today
api/main.py                   # (editado: registra o router de radar)

web/src/pages/RadarPage.tsx       # tela RADAR DO DIA
web/src/pages/RadarPage.test.tsx  # 9 testes (ver abaixo)
web/src/pages/CalendarPage.tsx    # (editado: badge de analise do radar +
                                   # filtro "somente selecionados pelo radar")
web/src/pages/CalendarPage.test.tsx  # (editado: +4 testes de integracao com o radar)
web/src/lib/radar.ts              # helpers compartilhados (badge por
                                   # match_key, rotulos de mercado/decisao)
web/src/services/api.ts       # (editado: getRadarToday)
web/src/types/api.ts          # (editado: RadarLine, Market, Side, DecisionState)
web/src/App.tsx               # (editado: rota "/radar" aponta para RadarPage)
web/src/App.test.tsx          # (editado: teste de navegacao provisoria usa
                               # "Forward" em vez de "Radar", que deixou de
                               # ser placeholder)

tests/test_radar_api.py       # 26 testes do adapter + endpoint HTTP
```

Nenhuma dependência nova.

### Origem dos dados

`api/services/radar_service.py` só LÊ os parquets já gravados por
`src.radar.build.run()` (Fase 8) em `data/outputs/phase8/`:

- `precos_por_linha.parquet` — uma linha por (partida, mercado, jogador
  quando aplicável, linha, lado); campos consumidos sem alteração:
  `operational_probability`, `fair_odds`, `is_candidate`,
  `candidate_blockers`, `sample_bucket_career`, `restricted`,
  `restricted_motivo`, `extreme_probability`, `resolution_method_player`/
  `_opponent`.
- `partidas_resolvidas.parquet` — só para recuperar `player_a_raw`/
  `player_b_raw`/`tournament`/`round`/`match_date` por `match_id` (esses
  campos não sobrevivem em `precos_por_linha.parquet`, que já foi pivotado
  para `player_name`/`opponent_name` por linha).
- `odds_minimas_por_edge.parquet` — os 5 cenários de edge (2%, 3%, 5%,
  7,5%, 10%) já calculados pela Fase 7/8 (`src/pricing/config.EDGE_LEVELS`).
- `src.odds.pricing_compare.staleness_warning` + `src.decision.staleness_policy.classify_staleness`
  (mesmas funções que `api/services/info_service.py` já usa desde o LOTE A)
  — nunca uma nova regra de defasagem.

Esta entrega **não implementa `?refresh=true`** (rodar
`src.radar.build.run()` sob demanda, mapeado na seção 3.3 para "Atualizar
radar do dia"). O pedido desta tarefa foi "expor os resultados **já
produzidos**", e a PWA deve "apenas consumir e apresentar dados
existentes" — implementá-lo agora ampliaria o lote. Fica registrado como
pendência explícita para um lote futuro, não como esquecimento.

### Adapter criado — `decision_state`

`is_candidate`/`candidate_blockers` (Fase 8, `src/radar/candidates.py`) já
existem prontos; `decision_state` é só um agrupamento de apresentação
desses MESMOS sinais em 3 grupos (pedido explícito desta tarefa), feito
inteiramente em `api/services/radar_service.py` (nunca no frontend, nunca
em `src/`):

```
CONFERIR_ODDS  <- is_candidate == True
OBSERVAR       <- is_candidate == False E o UNICO criterio que falhou foi
                  "probabilidade_nao_trivial"
DESCARTADO     <- qualquer outro caso (pelo menos um problema estrutural:
                  amostra insuficiente, mercado restrito, calibracao
                  indisponivel ou identidade nao confiavel)
```

Verificado sobre os dados reais desta entrega (13 partidas, 1.636 linhas
após deduplicação): 924 `CONFERIR_ODDS`, 316 `OBSERVAR`, 396 `DESCARTADO` —
`OBSERVAR` bate exatamente com o número de linhas cujo único blocker é
`probabilidade_nao_trivial` (conferido diretamente no parquet antes de
implementar o adapter).

**Achado técnico durante a implementação**: `total_aces_match` (mercado de
partida, não de jogador) é gravado DUAS vezes em `precos_por_linha.parquet`
— uma por jogador-âncora — com valores idênticos (mesma fórmula, não
depende de qual jogador foi usado como âncora; conferido sobre os dados
reais). O adapter deduplica para 1 linha por (partida, mercado, linha,
lado) e expõe `player=null`, evitando mostrar o mesmo card duas vezes na
UI. Isto é uma peculiaridade de representação já existente no parquet, não
uma alteração de modelo/feature.

**Achado técnico secundário**: `player_name`/`opponent_name` em
`precos_por_linha.parquet` vêm do nome resolvido (`players.parquet`), que
tem capitalização inconsistente para alguns jogadores (ex.:
`"sebastian baez"` em minúsculas). O adapter expõe, no campo `player`, o
mesmo texto bruto e corretamente capitalizado já usado em `player_a`/
`player_b` (`player_a_raw`/`player_b_raw`, escolhido pelo `player_id` via
`player_id_a`/`player_id_b` de `partidas_resolvidas.parquet` — identidade
já resolvida, não recalculada).

### Relacionamento por match_key

`api/services/radar_service.py` reaproveita **sem duplicar**
`src.calendar.match_key.build_match_key` (LOTE C) para calcular o
`match_key` de cada partida do radar a partir de `player_a_raw`/
`player_b_raw`/`tournament`/`round`/`match_date` (de
`partidas_resolvidas.parquet`), e cruza com `ManualFileCalendarProvider`
(também reaproveitado sem alteração) para preencher
`event_datetime_sao_paulo` quando existe uma entrada correspondente no
calendário.

Conferido ponta a ponta com servidor real: uma entrada de calendário
ilustrativa temporária (`Sebastian Baez x Jenson Brooksby`, mesmos dados
brutos do `data/raw/phase8/partidas_futuras_20260922.csv` real, removida
ao final do teste) produziu o **mesmo `match_key`** em `GET /api/calendar`
e em `GET /api/radar/today`
(`atp-chengdu-open-r32-sebastian-baez-jenson-brooksby-2026-09-23`), e
`event_datetime_sao_paulo` apareceu corretamente preenchido na linha do
radar.

**Limitação conhecida, não corrigível neste lote** (`src/calendar/` está
fora de escopo): `build_match_key` não normaliza a ORDEM dos dois
jogadores nem faz resolução de alias — ele depende de `agenda_*.csv`
(calendário) e `partidas_futuras_*.csv` (radar, Fase 8) listarem o mesmo
par de jogadores com o MESMO texto e na MESMA ordem A/B. Como são duas
coletas manuais independentes (ainda que da mesma fonte oficial), isso
pode divergir — quando divergir, a partida tem radar E está no calendário,
mas `event_datetime_sao_paulo` fica `null` e nenhum badge aparece no
calendário para ela (falha silenciosa de correspondência, não uma
exceção). Documentado aqui em vez de escondido; corrigir exigiria alterar
`src/calendar/match_key.py` (fora de escopo desta entrega).

### Campos expostos (`RadarLine`)

Ver `api/schemas/radar.py`. Resumo das decisões que se afastam do
`schema sugerido` da tarefa, sempre em favor de "usar nomes reais do
pipeline":

- `minimum_odds` é um único número (cenário `3pct`, o do meio dos 5 já
  calculados) **e** `odd_minima_por_edge` traz os 5 cenários completos —
  a Fase 7/8 deliberadamente não escolhe um edge operacional padrão
  ("não escolhemos um padrão operacional nesta fase", comentário original
  de `src/pricing/config.py`), então expor só um número inventaria uma
  decisão que o pipeline não toma. O exemplo do pedido ("odd mínima:
  4,35") não bate com nenhum dos 5 cenários reais calculados para a linha
  equivalente — era só ilustrativo, não um valor computado.
- `sample_bucket_career` é exposto com o nome/valor reais do pipeline
  (`"large_50_plus"`, etc.), não traduzido para `"HIGH"`/`"LOW"` (essa
  tradução não existe em nenhum lugar do código).
- `staleness_status` usa literalmente `src.decision.config.STALENESS_*`
  (`"ATUAL"`, `"MODERADAMENTE_DEFASADO"`, `"MUITO_DEFASADO"`) — o exemplo
  do pedido (`"MUITO_DEFASADO"`) já era um desses valores reais.

### Tela RADAR DO DIA

3 seções (`Conferir odds` / `Observar` / `Descartados`, este último dentro
de um `<details>` fechado por padrão — é sempre o maior grupo e o menos
acionável). Cada card mostra torneio, horário em São Paulo (ou "horário
não disponível" quando não há entrada correspondente no calendário),
jogadores, mercado + jogador + linha + lado, probabilidade, odd justa, odd
mínima e o estado — sem mostrar os 5 cenários de edge no card (pedido
explícito: "não mostrar edge como métrica principal"). Aviso de defasagem
sempre visível no topo, um por tour presente na resposta, nunca escondido.
Suporta `?match_key=...` na URL (usado pelo clique nos badges do
calendário) para filtrar para uma única partida.

### Calendário — badge "selecionado pelo radar"

`CalendarPage` busca `GET /api/radar/today` independentemente de
`GET /api/calendar` (se o radar falhar, o calendário continua funcionando
normalmente, só sem badge). `web/src/lib/radar.ts` agrupa as linhas do
radar por `match_key` e escolhe o `decision_state` de maior prioridade
quando uma partida tem linhas em mais de um grupo — é só uma agregação de
apresentação do que a API já devolve, nunca uma nova classificação. O
badge, quando existe, é um link para `/radar?match_key=...`. Filtro
"somente selecionados pelo radar" (pendente desde o LOTE C) implementado
como checkbox client-side.

### Markets

Só os 3 mercados já modelados (`aces_player`, `total_aces_match`,
`double_faults_player`, `src.probabilistic.config.MARKETS`) — `total_games`
não é gerado por `src.radar.build.run()`, então nunca aparece na resposta
(nada a filtrar, já vem assim do pipeline).

### Testes novos

`tests/test_radar_api.py` — 26 testes, todos sobre fixtures sintéticas
(nunca lê `data/outputs/phase8/` real, para ser determinístico):
`TestRadarLinesAdapter` (17: contagem de linhas com dedup de
`total_aces_match`, os 3 `decision_state` incluindo o caso combinado
`historico_suficiente,probabilidade_nao_trivial`, valores repassados sem
recálculo, `fair_odds` `NaN`→`None`, `restricted_motivo` repassado,
`identity_trusted` nos dois sentidos, capitalização correta de `player`,
`match_key` bate com `build_match_key`, `event_datetime_sao_paulo`
preenchido/`None`, partida não-usável nunca aparece, `staleness_status`
correto, cenário `3pct` como `minimum_odds` default, cenário de edge
ausente vira `None`), `TestRadarLinesEmptyState` (2: parquet ausente →
lista vazia, falha de `staleness_warning` nunca derruba o endpoint),
`TestRadarTodayEndpoint`/`TestRadarTodayEmptyEndpoint` (7: rota
registrada, contagem, conjunto de campos do schema, agrupamento correto
via HTTP, 200 vazio quando não há dados).

`web/src/pages/RadarPage.test.tsx` — 9 testes: carregamento, erro sem
inventar dado, lista vazia, agrupamento nas 3 seções (com `Descartados`
fechado por padrão), formatação de probabilidade/odd justa/odd mínima,
`"não disponível"` quando `fair_odds`/`minimum_odds` são `null`, mercado de
partida sem nome de jogador, aviso de defasagem sempre visível, filtro por
`match_key` da query string.

`web/src/pages/CalendarPage.test.tsx` — 4 testes novos: badge aparece só
para partida com análise no radar, busca do radar falhando não quebra o
calendário, filtro "somente selecionados pelo radar" esconde as demais,
badge é um link para `/radar?match_key=...`.

### Resultado do build de produção

```
npm run build
tsc -b && vite build
```

Sem erros de tipo. PWA `generateSW`, 7 entradas de precache estático
(284,42 KiB) — mesma contagem dos LOTEs B/C. `dist/sw.js` conferido: só a
mesma `denylist: [/^\/api\//]` de sempre, nenhuma entrada de
`runtimeCaching` nova para `/api/*`.

### Verificação end-to-end real (servidor + proxy)

Servidor FastAPI real com os dados reais já existentes em
`data/outputs/phase8/` (13 partidas, 1.636 linhas): `GET /api/radar/today`
conferido contra o próprio pedido do usuário (linha "Sebastian Baez —
Aces Over 5.5": probabilidade 24,47% ≈ 24,5%, odd justa 4,0869 ≈ 4,09 —
os mesmos números do exemplo dado nesta tarefa, confirmando que o exemplo
já vinha de um dado real do pipeline). Com uma entrada de calendário
ilustrativa temporária (removida ao final), o `match_key` bateu
identicamente entre `GET /api/calendar` e `GET /api/radar/today`, e
`event_datetime_sao_paulo` da linha do radar veio preenchido
corretamente. Conferido também via proxy do Vite dev server
(`localhost:5173/api/radar/today`) — resposta idêntica à do backend
direto.

### Limitações encontradas

- Junção calendário↔radar depende de texto/ordem de jogadores idênticos
  entre as duas coletas manuais (ver "Relacionamento por match_key" acima)
  — falha silenciosa (`null`/sem badge), nunca uma exceção, mas também
  nunca corrigível sem alterar `src/calendar/` (fora de escopo).
- `?refresh=true`/atualizar o radar sob demanda não foi implementado
  (ver "Origem dos dados" acima) — a tela sempre mostra o resultado da
  última execução de `src.radar.build.run()`, nunca dispara uma nova.
- "Detalhe da partida" (`GET /api/matches/{match_key}`) não existe ainda
  (LOTE futuro) — o clique no badge do calendário leva para o radar
  filtrado por `match_key`, não para uma tela de detalhe dedicada, como
  alternativa já prevista no pedido desta tarefa.
- `GET /api/radar/today` devolve todas as 1.636 linhas de uma vez (sem
  paginação) — aceitável para uso local pessoal hoje; se o volume diário
  crescer muito, pode valer a pena revisar (não é um problema a resolver
  agora, CLAUDE.md §20).

### Resultado da suíte Python completa (pós-LOTE D)

```
python -m unittest discover -s tests -p "test_*.py"
Ran 324 tests in 689.353s
OK
```

324/324 testes passando (298 já existentes do LOTE C + 26 novos de
`tests/test_radar_api.py`) — zero regressão sobre o motor estatístico ou
sobre `api/`. Execução em primeiro plano, saída completa capturada em
`full_suite_output_lote_d.txt`. Os mesmos dois trechos "ruidosos" do
LOTE A/B/C continuam aparecendo no meio da saída — esperados, não falhas.

---

---

## 19. LOTE E — CONCLUÍDO

Implementado somente o upload de print: `POST /api/screenshots`
(armazenamento em `data/raw/bookmaker_screenshots/`), a tela ENVIAR PRINT
(colar/arrastar/selecionar arquivo, tipo de aba, preview, envio) e a ação
"Adicionar print da Betano" na tela RADAR DO DIA. Exatamente como pedido:
nenhuma leitura/interpretação do conteúdo da imagem foi implementada (isso
é o LOTE F, não iniciado), nenhum modelo/`src/radar`/`src/odds`/
`src/forward`/lógica de decisão foi alterado, nenhuma integração
automática com a Betano foi criada, nenhum Playwright foi usado.

### Arquivos criados/alterados

```
src/screenshot_parser/__init__.py
src/screenshot_parser/config.py   # TabType (ACES/GAMES_TOTALS), formatos
                                   # permitidos, tamanho maximo, path base
src/screenshot_parser/storage.py  # save_screenshot() -- unica funcao de
                                   # negocio desta entrega: valida e grava
                                   # a imagem original + o sidecar JSON

api/schemas/screenshots.py        # ScreenshotUploadResponse, ScreenshotMetadata
                                   # (TabType reaproveitado de src/, nunca redefinido)
api/services/screenshot_service.py# camada HTTP fina sobre storage.save_screenshot
api/routes/screenshots.py         # POST /api/screenshots
api/main.py                       # (editado: registra o router de screenshots)
requirements.txt                  # (editado: +python-multipart, +pillow)

web/src/pages/ScreenshotUploadPage.tsx       # tela ENVIAR PRINT (rota /prints/:matchKey)
web/src/pages/ScreenshotUploadPage.test.tsx  # 10 testes (ver abaixo)
web/src/pages/RadarPage.tsx        # (editado: link "Adicionar print da
                                    # Betano" em cada card CONFERIR_ODDS/OBSERVAR)
web/src/pages/RadarPage.test.tsx   # (editado: +1 teste do link novo)
web/src/App.tsx                    # (editado: rota "/prints/:matchKey")
web/src/services/api.ts            # (editado: uploadScreenshot)
web/src/types/api.ts               # (editado: TabType, ScreenshotUploadResponse)

tests/test_screenshots_api.py      # 16 testes de integracao HTTP
```

Dependências novas: `python-multipart` (leitura de multipart/form-data
pelo FastAPI) e `pillow` (identificação real do formato de imagem —
`pillow` já estava presente no ambiente por outra razão, mas não constava
em `requirements.txt`; passou a constar). Nenhuma dependência de frontend
nova.

### Decisões de implementação

- **`tab_type` usa os valores literais pedidos nesta tarefa**
  (`ACES`/`GAMES_TOTALS`), não os valores `"aces"`/`"games_over_under"` que
  o desenho original da seção 8 havia esboçado para uma fase futura —
  a instrução explícita desta entrega tem precedência sobre o esboço.
- **Onde mora a lógica de armazenamento**: em `src/screenshot_parser/`
  (não em `api/`), seguindo o mesmo padrão de `src/calendar` e
  `src/odds/storage.py` — lógica de domínio testável sem subir a API.
  `api/services/screenshot_service.py` só lê o `UploadFile` e adapta o
  resultado para o schema HTTP, sem nenhuma regra própria. O módulo
  `src/screenshot_parser/` está deliberadamente incompleto em relação ao
  desenho da seção 7 (só tem `config.py`/`storage.py` — sem
  `mapping.py`/`validation.py`/`extractor.py`, que pertencem ao LOTE F,
  não iniciado).
- **Formato real da imagem, não extensão nem Content-Type declarado**:
  `storage._validate_and_identify_image` abre os bytes com Pillow
  (`Image.open(...).verify()`), e o formato devolvido pelo Pillow (não o
  nome do arquivo nem o header HTTP enviado pelo cliente) decide a
  extensão gravada em disco e o `mime_type` do metadata. Um arquivo de
  texto renomeado para `.png` é rejeitado com HTTP 422.
- **Estrutura de armazenamento exatamente como pedido**:
  `data/raw/bookmaker_screenshots/YYYY/MM/DD/<upload_id>_<tab_type>.<ext>`,
  com um JSON sidecar de mesmo nome (`<upload_id>_<tab_type>.json`) ao
  lado. `upload_id` é um `uuid4`, então cada envio (mesmo do mesmo
  arquivo/partida/aba) gera um par de arquivos novo — o histórico nunca é
  sobrescrito (verificado em teste dedicado). Se uma colisão de UUID
  acontecesse (praticamente impossível), `save_screenshot` levanta
  `RuntimeError` em vez de sobrescrever silenciosamente.
- **`stored_path` é sempre relativo a `data/raw/`**
  (`"bookmaker_screenshots/2026/09/23/<id>_ACES.png"`), construído como
  string a partir do timestamp — nunca derivado de um caminho absoluto do
  sistema de arquivos. Isso evita expor o caminho completo do Windows ao
  frontend (pedido explícito da seção SEGURANÇA) e também evita qualquer
  dependência da localização real do diretório de dados (importante para
  os testes, que apontam `SCREENSHOTS_RAW_DIR` para um diretório
  temporário via `mock.patch`, igual ao padrão já usado em
  `tests/test_calendar_api.py`).
- **`ScreenshotUploadResponse` (o que volta ao frontend) nunca inclui
  `sha256`/`stored_path`** — só o schema mais completo interno
  (`ScreenshotMetadata`, que espelha o JSON sidecar) tem esses campos.
  Não há endpoint que devolva `ScreenshotMetadata` nesta entrega (ver
  "Limitações" abaixo) — o schema existe porque foi pedido explicitamente
  ("Criar schemas para: ScreenshotUploadResponse, ScreenshotMetadata"),
  documentando o formato do sidecar mesmo sem um endpoint de leitura
  ainda.
- **Validação em ordem fixa e nunca grava nada em disco em caso de
  falha**: `match_key` não vazio → `tab_type` permitido → tamanho (>0 e
  ≤10 MB) → formato de imagem real. Todas as falhas desta camada viram
  HTTP 422 com uma mensagem específica (nunca stacktrace); campos
  ausentes/mal tipados (`match_key`/`tab_type`/arquivo faltando) já são
  rejeitados pela validação nativa do FastAPI antes de chegar em
  `storage.save_screenshot`.
- **`GET /api/screenshots?match_key=...` não foi implementado** — a
  instrução desta tarefa deixou explícito "só implemente se necessário" e
  "evitar endpoints extras"; o fluxo pedido termina em "Print salvo" +
  `upload_id`, sem precisar listar uploads anteriores. Fica como pendência
  explícita, não esquecimento (mesmo padrão de registrar pendências já
  usado nos LOTEs C/D).
- **Ação "Adicionar print da Betano" fica em cada card do RADAR DO DIA**
  (não em um lugar único por partida) para `CONFERIR_ODDS`/`OBSERVAR`,
  nunca para `DESCARTADO` — leva para `/prints/{match_key}` com
  `encodeURIComponent`. Como vários cards podem compartilhar o mesmo
  `match_key` (mercados diferentes da mesma partida), o link aparece
  repetido por linha — aceitável nesta entrega (o pedido fala em "para um
  jogo/mercado", compatível com essa leitura por linha).

### Tela ENVIAR PRINT (`/prints/:matchKey`)

Busca `GET /api/radar/today` e filtra pelo `match_key` da rota para montar
o cabeçalho (torneio, jogadores, horário em São Paulo) e a lista de
mercados em `CONFERIR_ODDS` — sem recalcular nada, é uma leitura filtrada
do mesmo endpoint que a tela RADAR DO DIA já usa (LOTE D). Se a partida não
aparecer no radar do dia (`match_key` sem linha), a tela mostra
"Partida não encontrada no radar do dia" mas continua permitindo o upload
(o `match_key` da URL é usado do mesmo jeito — o backend não exige que ele
exista no radar).

Fluxo de arquivo: colar (`onPaste`, evento de clipboard do container),
arrastar (`onDrop`/`onDragOver`) ou selecionar (`<input type="file">`
oculto, acionado por um botão) — as três vias chamam a mesma função
`acceptFile`, que valida tipo (`image/png`/`image/jpeg`/`image/webp`) e
tamanho (≤10 MB) no cliente antes de mostrar o preview (`URL.createObjectURL`,
revogado ao trocar/remover a imagem ou desmontar a tela). A validação do
cliente é só uma conveniência de UX — a validação real (conteúdo de
verdade da imagem) é sempre a do backend.

Botões de tipo de aba (`Aces` / `Games Mais/Menos`) usam `aria-pressed`
para indicar a seleção atual; o botão "Enviar print" fica desabilitado até
haver arquivo + tipo selecionados. Após `POST /api/screenshots` bem
sucedido, a tela troca para "Print salvo com sucesso" + `upload_id`,
exatamente como pedido, e para aí (sem redirecionar automaticamente, sem
iniciar leitura/confirmação — isso é LOTE F). Em caso de erro, a mensagem
devolvida pela API (`detail`) é mostrada e a seleção do usuário (arquivo +
tipo) é preservada, para tentar de novo sem precisar re-selecionar tudo.

### Testes novos

`tests/test_screenshots_api.py` — 16 testes, todos com
`SCREENSHOTS_RAW_DIR` substituído por um diretório temporário (mesmo
padrão de `tests/test_calendar_api.py`, nenhum arquivo real do projeto é
tocado):

- `TestRouteRegistered` (1): rota registrada no schema OpenAPI.
- `TestValidUploads` (3): PNG, JPG e WEBP válidos (imagens reais geradas
  com Pillow em memória) devolvem HTTP 201 com o schema exato de
  `ScreenshotUploadResponse`.
- `TestRejections` (8): formato proibido mesmo com extensão de imagem
  (texto puro nomeado `print.png`), arquivo vazio, arquivo acima de 10 MB,
  `tab_type` inválido, `match_key` ausente, `match_key` em branco, arquivo
  ausente, e — importante — um upload rejeitado não grava nada em disco
  (`tmp_path` fica vazio).
- `TestAuditTrail` (4): hash SHA-256 gravado bate com o conteúdo real;
  `upload_id` é único entre dois uploads do mesmo arquivo; o histórico
  nunca é sobrescrito (dois uploads geram dois arquivos de imagem
  distintos); o JSON sidecar tem todos os campos pedidos
  (`upload_id`, `created_at`, `bookmaker`, `match_key`, `tab_type`,
  `original_filename`, `stored_path`, `mime_type`, `file_size`, `sha256`),
  com `stored_path` sempre relativo e sem barra invertida (nunca caminho
  estilo Windows).

`web/src/pages/ScreenshotUploadPage.test.tsx` — 10 testes: contexto da
partida + mercados `CONFERIR_ODDS` do radar; estado inicial sem imagem com
envio desabilitado; seleção via `<input>`; remover imagem (volta ao estado
inicial); colar via evento de paste (clipboard simulado com
`fireEvent.paste`, sem inventar nenhuma API de navegador inexistente);
arrastar e soltar (`fireEvent.drop`); seleção de "Aces"; seleção de "Games
Mais/Menos"; envio com sucesso (mostra `upload_id`, confirma que
`match_key` da rota foi preservado na chamada à API); erro do backend
exibido sem apagar a seleção do usuário.

`web/src/pages/RadarPage.test.tsx` — 1 teste novo: o link
"Adicionar print da Betano" aparece para linhas `CONFERIR_ODDS`/`OBSERVAR`
(apontando para `/prints/{match_key}`) e não aparece para `DESCARTADO`.

### Verificação end-to-end real (servidor real, sem mocks)

Além dos testes automatizados, o endpoint foi exercitado com um servidor
FastAPI real (`127.0.0.1:8000`) e uma imagem PNG real gerada com Pillow,
usando uma chamada HTTP multipart construída manualmente (biblioteca
padrão do Python, sem dependência nova): `POST /api/screenshots` devolveu
HTTP 201 com `upload_id`/`match_key`/`tab_type`/`bookmaker`/`created_at`/
`mime_type`/`file_size`; os dois arquivos esperados foram conferidos em
`data/raw/bookmaker_screenshots/2026/09/23/` (a imagem PNG intacta e o
JSON sidecar com todos os campos, incluindo o `sha256` correto). Os
arquivos de teste (`match_key` claramente rotulado como temporário) foram
removidos ao final da verificação — `data/raw/bookmaker_screenshots/` fica
vazio/inexistente nesta entrega, mesma disciplina já usada nos LOTEs C/D
para não commitar dado de exemplo.

### Resultado do build de produção

```
npm run build
tsc -b && vite build
```

Sem erros de tipo. PWA `generateSW`, 7 entradas de precache estático
(290,71 KiB) — mesma contagem dos LOTEs B/C/D (nenhum asset novo).
`dist/sw.js` conferido: só a mesma `denylist: [/^\/api\//]` de sempre,
nenhuma entrada de `runtimeCaching` nova para `/api/*` (o upload de print
nunca deve ser cacheado/servido offline pelo service worker).

### Resultado da suíte de frontend

```
npm run test -- --run
Test Files  4 passed (4)
     Tests  37 passed (37)
```

37/37 testes (26 já existentes dos LOTEs B/C/D + 11 novos: 10 de
`ScreenshotUploadPage.test.tsx` + 1 de `RadarPage.test.tsx`).

### Resultado da suíte Python completa (pós-LOTE E)

```
python -m unittest discover -s tests -p "test_*.py"
Ran 340 tests in 499.406s

OK
```

340/340 testes passando (324 já existentes do LOTE D + 16 novos de
`tests/test_screenshots_api.py`) — zero regressão sobre o motor
estatístico, `api/` ou `src/calendar`. Execução em primeiro plano, saída
completa capturada em `full_suite_output_lote_e.txt`. Os mesmos dois
trechos "ruidosos" dos LOTEs A/B/C/D continuam aparecendo no meio da saída
(traceback proposital de `tests/test_api.py` e mensagem de `argparse` de
`daily_forward_workflow.py`) — esperados, não falhas.

### Limitações encontradas

- `GET /api/screenshots?match_key=...` não existe (ver "Decisões de
  implementação" acima) — não é possível, nesta entrega, listar/revisar
  prints já enviados para uma partida pela PWA; a única confirmação do
  envio é a tela "Print salvo com sucesso" no momento do upload.
  `ScreenshotMetadata` está definido (pedido explícito), mas nenhum
  endpoint o devolve ainda.
- Nenhuma leitura do conteúdo da imagem acontece (por desenho desta
  entrega) — o print fica arquivado para auditoria, mas nenhum valor
  (mercado, linha, odd) é extraído automaticamente. Isso é o LOTE F,
  ainda não iniciado.
- O link "Adicionar print da Betano" aparece por linha do radar (mercado),
  não uma única vez por partida — se uma partida tiver várias linhas
  `CONFERIR_ODDS`/`OBSERVAR`, o link aparece repetido nos respectivos
  cards, todos levando para a mesma tela de upload (`match_key` é o mesmo).
- Validação de tamanho lê o corpo inteiro do upload na memória antes de
  checar o limite de 10 MB — aceitável para uso local pessoal (mesmo
  raciocínio já usado no risco R10 da seção 12), não uma preocupação de
  streaming/performance nesta escala.

---

**LOTE E concluído. Não iniciar o LOTE F sem nova autorização. Pare ao
concluir.**

---

## 20. LOTE F — CONCLUÍDO

Implementada a leitura/validação/confirmação de print (`src/screenshot_parser/`
completo) e os 3 endpoints novos (`extract`/`extraction`/`confirm`), exatamente
como pedido: só os mercados `aces_player`, `total_aces_match` e `total_games`
são suportados; nenhum modelo estatístico/`src/radar`/`src/odds`/`src/forward`/
threshold foi alterado; `record_odds.py`, cálculo de edge, classificação
PASSOU/NÃO PASSOU e forward test **não** são chamados por este lote — a leitura
confirmada fica arquivada para auditoria, pronta para um lote futuro (Fase 9/10)
consumi-la, mas essa integração está fora de escopo aqui.

### Arquivos criados/alterados

```
src/screenshot_parser/config.py        # (editado: +EXTRACTED_RAW_DIR, CONFIRMED_DIR,
                                        #  SUPPORTED_MARKETS, SIDES, status/warning
                                        #  constants, configuracao do provider de visao)
src/screenshot_parser/storage.py       # (editado: +find_screenshot, +resolve_image_path
                                        #  -- localizam o upload pelo upload_id)
src/screenshot_parser/models.py        # NOVO -- MatchContext, RawReading,
                                        # NormalizedMarket, ExtractionResult,
                                        # ConfirmedExtraction
src/screenshot_parser/mapping.py       # NOVO -- "X+" -> Over(X-0.5); "Mais/Menos
                                        # de N" -> Over/Under N
src/screenshot_parser/validator.py     # NOVO -- validacoes + warnings + status
src/screenshot_parser/providers.py     # NOVO -- ScreenshotVisionProvider (Protocol),
                                        # ExtractionContext, erros, Fake/FailingVisionProvider
src/screenshot_parser/anthropic_provider.py  # NOVO -- implementacao real opcional
                                        # (via `requests`, sem SDK novo)
src/screenshot_parser/extraction_storage.py  # NOVO -- persistencia raw/confirmed
src/screenshot_parser/extractor.py     # NOVO -- orquestracao (run_extraction,
                                        # latest_extraction, confirm_extraction)

api/schemas/screenshots.py             # (editado: +NormalizedMarketSchema,
                                        # ExtractionResponse, ConfirmMarketInput,
                                        # ConfirmRequest, ConfirmResponse)
api/services/screenshot_service.py     # (editado: +extract_screenshot,
                                        # get_extraction, confirm_screenshot)
api/routes/screenshots.py              # (editado: +POST .../extract,
                                        # GET .../extraction, POST .../confirm)
requirements.txt                       # (editado: `requests` ja constava, mas
                                        # nao estava instalado neste ambiente --
                                        # instalado; nenhuma dependencia NOVA
                                        # adicionada ao arquivo)

web/src/types/api.ts                   # (editado: +ExtractionMarket, ExtractionSide,
                                        # ExtractionStatus, NormalizedMarket,
                                        # ExtractionResponse, ConfirmMarketInput,
                                        # ConfirmResponse)
web/src/services/api.ts                # (editado: +extractScreenshot, getExtraction,
                                        # confirmScreenshot)
web/src/pages/ScreenshotUploadPage.tsx # (editado: +botao "Ler print", tela de
                                        # revisao editavel, "Confirmar leitura")
web/src/pages/ScreenshotUploadPage.test.tsx  # (editado: +8 testes)

tests/test_screenshot_parser.py        # NOVO -- 33 testes (mapping, validator,
                                        # anthropic_provider com requests mockado)
tests/test_screenshot_extraction_api.py# NOVO -- 26 testes de integracao HTTP
```

### Provider de visão

`ScreenshotVisionProvider` (Protocol, `src/screenshot_parser/providers.py`) define
só `extract(image_path, context) -> ProviderExtraction`. Nenhuma parte do sistema
depende de uma implementação específica — `extractor.py` chama `providers.get_provider()`,
que lê a variável de ambiente `TENNIS_RADAR_VISION_PROVIDER` (default `"anthropic"`).

Implementação real: `AnthropicVisionProvider` (`anthropic_provider.py`), que chama a
API de mensagens da Anthropic via `requests` (já era dependência do projeto — nenhum
SDK novo foi adicionado só para isto, CLAUDE.md §20). Configuração, sem nenhum valor
adivinhado:

- `ANTHROPIC_API_KEY` — obrigatória.
- `TENNIS_RADAR_VISION_MODEL` — obrigatória; este módulo nunca escolhe um id de
  modelo default, porque um palpite errado falharia tarde e silenciosamente.
- `TENNIS_RADAR_VISION_TIMEOUT_SECONDS` — opcional, default 60s.

Erros de rede/timeout/autenticação/resposta inválida são traduzidos para
`ProviderUnavailableError`/`ProviderTimeoutError`/`ProviderResponseError`
(`api/routes/screenshots.py` mapeia para HTTP 503/504/502 respectivamente).

Para os testes: `FakeVisionProvider` (devolve leituras fixas, sem IO) e
`FailingVisionProvider` (levanta o erro passado no construtor) — nenhuma chamada
real de IA entra na suíte automática (pedido explícito). `tests/test_screenshot_parser.py`
testa `AnthropicVisionProvider` isoladamente com `requests.post` mockado (timeout,
erro de conexão, 401, 500, JSON inválido, resposta válida, itens incompletos
ignorados sem inventar valor, JSON dentro de bloco ```` ```json ````).

### Formato extraído e normalização

`RawReading` (o que um provider devolve) → `validator.validate_and_normalize()` →
`NormalizedMarket` (o que a API expõe). `mapping.py` traduz o texto da casa:

- `"X+"` → `model_line = X - 0.5`, `side = "Over"` (aces por jogador e total de aces).
- `"Mais de N"` → `side = "Over"`, `"Menos de N"` → `side = "Under"` (total de games;
  aceita separador decimal `.` ou `,`).

`side` é `"Over"`/`"Under"` (capitalizado, como a própria casa exibe) — **deliberadamente
diferente** do `"over"`/`"under"` minúsculo usado em `src/odds` (Fase 9): esta camada
audita o texto exibido pela casa, ainda não é uma observação de odd da Fase 9 (esse
mapeamento é decisão de um lote futuro, fora de escopo aqui).

### Validações e warnings

Nenhuma leitura é descartada — toda `RawReading` vira exatamente um `NormalizedMarket`
na saída, com warnings quando algo foge do esperado:

| Warning | Quando | Bloqueia confirmação? |
|---|---|---|
| `FORMATO_ILEGIVEL` | `bookmaker_display` não bate com nenhum formato conhecido | **Sim** |
| `ODD_INVALIDA` | `decimal_odds <= 1.00` | **Sim** |
| `JOGADOR_NAO_RECONHECIDO` | jogador não é `player_a`/`player_b` do contexto da partida | Não |
| `LEITURA_DUPLICADA` | mesma combinação `market+player+side+model_line` repetida | Não |
| `LINHAS_NAO_CRESCENTES` | linhas do bloco não vêm em ordem crescente | Não |
| `ODDS_NON_MONOTONIC` | odd cai ao subir a linha, dentro do mesmo bloco | Não |
| `LINHA_SEM_PAR_OVER_UNDER` | total de games sem o Over/Under correspondente na mesma linha | Não |
| `GAMES_ODDS_TENDENCIA_ATIPICA` | Over não sobe / Under não desce conforme a linha muda | Não |

Critério técnico de status (nenhum limiar de negócio arbitrário, pedido explícito):
`AUTO_VALIDATED` = nenhuma leitura tem warning e há pelo menos um mercado;
`NEEDS_CONFIRMATION` = qualquer warning presente, ou zero mercados extraídos
(warning de extração `NENHUM_MERCADO_ENCONTRADO`).

Na confirmação (`extractor.confirm_extraction`), só `FORMATO_ILEGIVEL`/`ODD_INVALIDA`
bloqueiam (`ExtractionValidationError`, HTTP 422) — os demais warnings são só um aviso
que o usuário pode confirmar mesmo assim, conforme pedido ("impedir apenas erros
estruturais graves").

### Persistência

Dois artefatos separados, nunca reescritos (um arquivo novo por extração/confirmação,
mesmo reenvio do mesmo upload):

```
data/raw/bookmaker_extracted/{extraction_id}.json     # extracao bruta da IA
data/processed/bookmaker_confirmed/{extraction_id}.json  # leitura confirmada
```

`GET /api/screenshots/{upload_id}/extraction` devolve sempre a extração mais recente
(`extraction_storage.latest_raw_extraction`, ordenado por `created_at`).

### Endpoints novos

| Método | Rota | Resposta |
|---|---|---|
| `POST` | `/api/screenshots/{upload_id}/extract` | roda o provider configurado, valida, persiste a extração bruta, devolve `ExtractionResponse` |
| `GET` | `/api/screenshots/{upload_id}/extraction` | devolve a extração mais recente já persistida (404 se nenhuma) |
| `POST` | `/api/screenshots/{upload_id}/confirm` | recebe `player`/`bookmaker_display`/`decimal_odds` editados, **recalcula `model_line`/`side` no backend** (nunca confia em valor do cliente), valida, persiste a confirmação |

Erros mapeados: `upload_id` inexistente → 404; imagem sumiu do disco → 404; provider
indisponível → 503; timeout → 504; resposta inválida do provider → 502; erro
estrutural na confirmação → 422. Nenhum desses caminhos chama `src.odds`/
`src.decision`/`src.forward`.

### UI de revisão

Após o upload (LOTE E), a tela `/prints/:matchKey` ganhou um botão "Ler print" →
"Analisando imagem…" → revisão lado a lado (print original + cartões editáveis por
mercado: jogador quando aplicável, linha exibida pela casa, odd — `model_line`/`side`
nunca são editados diretamente, são recalculados no backend a partir do texto editado,
conforme pedido). Quando `status = NEEDS_CONFIRMATION`, o banner "Confirme esta leitura"
aparece; os warnings de cada leitura aparecem como badges. "Confirmar leitura" chama o
endpoint de confirmação e troca a tela para "Leitura confirmada" com os valores finais
(somente leitura). O print original nunca é escondido (reaproveita o mesmo blob local
já usado no preview de upload — nenhum endpoint novo de "servir imagem" foi criado,
desnecessário já que o navegador ainda tem o arquivo em memória na mesma sessão).

### Testes

- `tests/test_screenshot_parser.py` — 33 testes unitários (mapping, validator,
  `AnthropicVisionProvider` com `requests` mockado).
- `tests/test_screenshot_extraction_api.py` — 26 testes de integração HTTP (ACES
  válido, `total_aces_match` válido, Games Over/Under válido, jogador inválido, odd
  inválida, duplicidade, warning de monotonicidade, extração vazia, provider com
  erro em cada um dos 3 status HTTP, persistência raw nunca sobrescrita,
  `GET .../extraction` devolve a mais recente, imagem original intacta após
  extração, confirmação sem correção, confirmação com correção manual, confirmação
  deriva `model_line` do `bookmaker_display` editado (não do valor antigo),
  confirmação bloqueia em erro estrutural mas aceita warning de consistência,
  `upload_id` inexistente em cada endpoint, persistência confirmed separada da raw).
- `web/src/pages/ScreenshotUploadPage.test.tsx` — 8 testes novos: botão "Ler print",
  estado "Analisando imagem…", mercados extraídos editáveis lado a lado com a
  imagem, banner + warnings quando `NEEDS_CONFIRMATION`, edição manual seguida de
  confirmação com os valores editados, erro de extração com "Tentar novamente",
  aba Games Mais/Menos (mercado de partida, sem campo "Jogador").

### Verificação manual end-to-end

Sem `ANTHROPIC_API_KEY` configurada neste ambiente, e sem nenhum print real
persistido em `data/raw/bookmaker_screenshots/` (LOTE E não deixou nenhum — só
gerou e removeu dados de teste), a verificação manual usou um `FakeVisionProvider`
sobre o **servidor/app real** (sem patchear os diretórios de dados): upload real →
extração real (provider trocado só por não ter chave de API) → confirmação real,
gravando de fato em `data/raw/bookmaker_screenshots/`, `data/raw/bookmaker_extracted/`
e `data/processed/bookmaker_confirmed/` — os três caminhos existiram, os JSONs
tinham os campos esperados, e a imagem original ficou intacta. Arquivos de teste
removidos ao final (mesma disciplina do LOTE E — `match_key` rotulado
`MANUAL_E2E_TEST_LOTE_F_DELETE_ME`, `data/` volta a ficar sem esses artefatos).

**Provider real (`AnthropicVisionProvider`) não foi exercitado contra a API de
verdade** — nem chave de API nem um print real da Betano estavam disponíveis nesta
sessão. É uma limitação conhecida, registrada explicitamente (não escondida): o
caminho de código está coberto por testes unitários com `requests.post` mockado,
mas a leitura de um print real por IA, ponta a ponta, fica pendente do primeiro
uso real (quando `ANTHROPIC_API_KEY`/`TENNIS_RADAR_VISION_MODEL` forem configuradas
e houver um print real para enviar).

### Resultado do build e das suítes

```
cd web && npm run build      # tsc -b && vite build -- sem erros de tipo
npm run test -- --run        # 44/44 testes (37 dos LOTEs B-E + 7 novos*)
```

\* 8 testes novos foram escritos; 7 aparecem como incremento líquido porque um
teste existente (upload com sucesso) já cobria parte do fluxo compartilhado —
a contagem exata está na saída do `vitest`.

```
python -m unittest discover -s tests -p "test_*.py"
Ran 399 tests in 498.864s

OK
```

399/399 testes passando (78 em `tests/test_screenshot_parser.py` +
`tests/test_screenshot_extraction_api.py` + `tests/test_screenshots_api.py`
somados, incluindo os 36 + 26 novos deste lote) — zero regressão sobre o motor
estatístico, `api/` ou os lotes anteriores da PWA. Resultado completo capturado
em `full_suite_output_lote_f.txt` (execução em background) — mesma disciplina
dos LOTEs A-E: os mesmos dois trechos "ruidosos" (traceback proposital de
`tests/test_api.py`, mensagem de `argparse` de `daily_forward_workflow.py`)
aparecem no meio da saída, esperados, não falhas.

### Limitações encontradas

- `AnthropicVisionProvider` não foi testado contra a API real (sem credenciais
  neste ambiente) — ver seção "Verificação manual end-to-end" acima.
- Nenhum print real da Betano foi lido nesta entrega (nenhum existia em
  `data/raw/bookmaker_screenshots/`) — a validação de qualidade de leitura real
  (quão bem o modelo de visão lê um print de verdade) fica pendente do primeiro
  uso real pelo usuário.
- A tela de revisão só permite editar `player`/`bookmaker_display`/`decimal_odds`
  de mercados já extraídos — não permite adicionar uma linha que a IA não tenha
  encontrado nem remover uma linha indesejada (fora do pedido explícito desta
  entrega, que fala em "editar", não em "adicionar/remover").
- `side` nesta camada é `"Over"`/`"Under"` (texto da casa), diferente do
  `"over"`/`"under"` minúsculo de `src/odds` — decisão deliberada (ver seção
  "Formato extraído e normalização"), mas quem for integrar a leitura confirmada
  com a Fase 9 num lote futuro precisa mapear isso explicitamente, não presumir
  que os dois já usam o mesmo vocabulário.
- Sem endpoint para listar todas as extrações/confirmações de um `upload_id`
  (só a mais recente, via `GET .../extraction`) — não foi pedido, e
  `extraction_storage.list_raw_extractions`/`list_confirmed` já existem
  internamente se um lote futuro precisar expor isso.

---

**LOTE F concluído. Não chamar `record_odds.py`/calcular edge/classificar
PASSOU/NÃO PASSOU/registrar forward test. Não iniciar o LOTE G sem nova
autorização. Pare ao concluir.**

---

## 21. LOTE G — CONCLUÍDO

Implementado o endpoint de avaliação (`POST /api/screenshots/{upload_id}/evaluate`)
que pega os mercados **CONFIRMADOS** do LOTE F
(`data/processed/bookmaker_confirmed/`) e os avalia usando **exclusivamente** o
pipeline já existente das Fases 9/10 (`src.odds.build.run` / `src.decision.build.run`).
Nenhum modelo/feature/calibração/threshold foi alterado; nenhuma fórmula de
`implied_probability`/`edge`/`fair_odds`/`minimum_acceptable_odds`/`decision_state`
foi duplicada ou recalculada — o novo módulo (`src/odds/screenshot_evaluation.py`)
só monta a entrada que `src.odds.build.run` já espera e lê de volta a linha já
classificada. Não é registrado nada no Forward Test (Fase 11) e o LOTE H não foi
iniciado.

### Arquivos criados/alterados

```
src/screenshot_parser/extractor.py     # (editado: +get_match_context, wrapper
                                        # publico sobre _build_match_context --
                                        # LOTE G precisa do mesmo contexto de
                                        # partida do LOTE F, sem duplicar a
                                        # leitura/validacao de agenda_*.csv)

src/odds/screenshot_evaluation.py      # NOVO -- adapter: ConfirmedExtraction ->
                                        # entrada de src.odds.build.run -> le de
                                        # volta a linha classificada pela Fase 10

api/schemas/odds_evaluation.py         # NOVO -- TechnicalDetails,
                                        # EvaluatedMarketResult, EvaluateResponse
api/services/odds_evaluation_service.py# NOVO -- camada HTTP fina sobre
                                        # src.odds.screenshot_evaluation
api/routes/screenshots.py              # (editado: +POST .../evaluate)

web/src/types/api.ts                   # (editado: +EvaluationLabel,
                                        # TechnicalDetails, EvaluatedMarketResult,
                                        # EvaluateResponse)
web/src/services/api.ts                # (editado: +evaluateScreenshot)
web/src/lib/radar.ts                   # (editado: +EVALUATION_LABEL_TEXT)
web/src/pages/ScreenshotUploadPage.tsx # (editado: +botao "Avaliar no Radar",
                                        # "Comparando com o modelo…", cards de
                                        # resultado, "Detalhes técnicos" colapsavel)
web/src/pages/ScreenshotUploadPage.test.tsx  # (editado: +9 testes; +correcao de
                                        # tipo pre-existente em 2 Promises de teste,
                                        # ver "Achado incidental" abaixo)

tests/test_screenshot_evaluation.py    # NOVO -- 9 testes do adapter (dados reais
                                        # de data/outputs/phase8/, saidas em tmp)
tests/test_odds_evaluation_api.py      # NOVO -- 5 testes de integração HTTP
```

### Fluxo implementado

```
mercado CONFIRMADO (LOTE F, data/processed/bookmaker_confirmed/)
        |
        v
src.odds.screenshot_evaluation.evaluate_confirmed(upload_id)
        |
        |-- mercado fora de src.decision.config.ALLOWED_MARKETS (total_games)?
        |     -> SEM_AVALIACAO_DISPONIVEL, "Mercado ainda não disponível para
        |        avaliação pelo modelo." -- NUNCA enviado a src.odds.build
        |
        v
monta entry {bookmaker, tour, market, player, opponent, tournament, line,
             {side}_odds, collected_at, source_method="screenshot_confirmed"}
        |
        v
src.odds.build.run(entries=[...], investigate_betano=False)   # Fase 9 (existente)
        |
        v
src.decision.build.run()                                       # Fase 10 (existente)
        |
        v
le de volta a linha (bookmaker, tour, market, player, side, line, decimal_odds,
collected_at) na tabela `evaluated` -- mapeia decision_state -> evaluation_label
(agrupamento visual, secao 6.6) -- devolve EvaluateResponse
```

### Resolução de jogador em mercados de partida

`total_aces_match` não identifica um jogador específico no print
(`NormalizedMarket.player = None`, LOTE F). `precos_por_linha.parquet` grava a
MESMA `operational_probability`/`line` para os dois jogadores de uma partida
nesse mercado (verificado nos dados reais do projeto) — por isso o adapter usa
`context.player_a` (via `ManualFileCalendarProvider`, mesmo contexto do LOTE F)
como âncora; o resultado é idêntico ao que se obteria usando `player_b`. O
campo `player` devolvido ao frontend continua `None` (nunca inventa um nome que
o print não mostrou).

### Mapeamento de `decision_state` para `evaluation_label`

Nunca uma nova regra de decisão — só um agrupamento visual do que a Fase 10 já
calculou (docs seção 6.6):

| `decision_state` (Fase 10) | `evaluation_label` (LOTE G) | Texto na PWA |
|---|---|---|
| `CANDIDATO_FORTE`, `CANDIDATO`, `CANDIDATO_FRACO` | `PASSOU_DO_LIMITE` | PASSOU DO LIMITE |
| `OBSERVAR` | `OBSERVAR` | OBSERVAR |
| `DESCARTAR` | `NAO_PASSOU` | NÃO PASSOU DO LIMITE |
| mercado fora da grade das Fases 6/7/9/10 | `SEM_AVALIACAO_DISPONIVEL` | SEM AVALIAÇÃO DISPONÍVEL |

`minimum_odds` é lido da coluna `odd_minima_{label}` já calculada na Fase 9,
escolhida pelo piso de edge do mercado (`market_edge_floor`, já calculado pela
Fase 10) — nunca chama `minimum_acceptable_odds` diretamente.

### Endpoint novo

| Método | Rota | Resposta |
|---|---|---|
| `POST` | `/api/screenshots/{upload_id}/evaluate` | avalia a leitura CONFIRMADA mais recente deste upload contra as Fases 9/10, devolve `EvaluateResponse` (um resultado por mercado) |

Erros mapeados: `upload_id` inexistente → 404 "Upload não encontrado."; upload
existe mas nenhuma leitura foi confirmada ainda → 404 "Nenhuma leitura
confirmada para este upload."; sem `tour` resolvível na agenda (`ManualFileCalendarProvider`)
para o `match_key` → 422 (todos os mercados de um mesmo print compartilham o
mesmo contexto, então a avaliação inteira é bloqueada em vez de um resultado
parcial inventado). Uma entrada individual rejeitada por `src.odds.build.validate_entry`
(ex.: odd inválida — não deveria acontecer numa leitura já confirmada, mas
nunca é ignorado silenciosamente) aparece no campo `error` daquele mercado
específico, sem derrubar os demais mercados da mesma avaliação.

Escolhido `POST /api/screenshots/{upload_id}/evaluate` (em vez de
`POST /api/odds/evaluate` como o plano original da seção 14 previa) porque o
pedido do LOTE G tornou a avaliação um passo **manual**, disparado só pelo
botão "Avaliar no Radar" depois de "Leitura confirmada" — nunca automático
após a confirmação — e o padrão `/screenshots/{upload_id}/...` já é o mesmo
usado por `.../extract` e `.../confirm` (mesmo recurso, mesma convenção).

### Persistência

Reaproveitada integralmente — nenhuma segunda fonte de verdade:

- `src.odds.build.run` grava em `data/outputs/phase9/{odds_observed,comparison_with_model}.parquet`
  (append-only, mesma disciplina da Fase 9) com `source_method="screenshot_confirmed"`.
- `src.decision.build.run` grava em `data/outputs/phase10/opportunities_evaluated.parquet`
  (append-only, mesma disciplina da Fase 10).
- Clicar "Avaliar no Radar" duas vezes para a MESMA leitura confirmada é
  idempotente: `collected_at` é sempre `confirmed.confirmed_at` (fixo por
  confirmação), e o dedup já existente da Fase 9 descarta a repetição exata.
  Confirmar de novo (nova correção, novo `confirmed_at`) gera um novo snapshot
  — mesma regra já documentada na Fase 9 (item 11: duas leituras em horários
  diferentes são duas observações distintas).

### UI — RESULTADO DA ANÁLISE

Após "Leitura confirmada": botão **"Avaliar no Radar"** → "Comparando com o
modelo…" → um card por mercado, com Probabilidade/Odd justa/Odd mínima/Betano
e o rótulo em destaque (PASSOU DO LIMITE / OBSERVAR / NÃO PASSOU DO LIMITE /
SEM AVALIAÇÃO DISPONÍVEL — nunca `implied_probability`/`edge` cru na tela
principal). "Detalhes técnicos" fica colapsado por padrão (prob. implícita,
edge do modelo, qualidade da amostra, restrição, defasagem, motivo do não
casamento quando houver). O aviso de defasagem estatística da Fase 9
(`staleness_warning`) é sempre mostrado, nunca escondido. Nenhum termo da lista
proibida (`FORBIDDEN_TERMS`) aparece em nenhum texto novo.

### Testes

- `tests/test_screenshot_evaluation.py` — 9 testes do adapter, direto sobre
  `src.odds.screenshot_evaluation.evaluate_confirmed` (as SAÍDAS das Fases 9/10
  vão para diretório temporário; a ENTRADA, `data/outputs/phase8/precos_por_linha.parquet`,
  é a real deste projeto — mesmo padrão de `TestBuildEndToEndWithRealData` em
  `tests/test_decision.py`, com `skipTest` se o arquivo não existir): mercado
  não suportado (`total_games`) nunca chega a `src.odds.build`; linha casada
  classificada pelo pipeline real (`aces_player`); odd alta o suficiente
  atinge `PASSOU_DO_LIMITE`; linha inexistente na grade do modelo →
  `DESCARTAR`/`NAO_PASSOU` com `match_reason` explícito; `total_aces_match`
  com `player=None` resolve via `player_a` do calendário; upload inexistente;
  upload existente mas nunca confirmado; contexto de partida indisponível;
  nenhuma fórmula de `src.pricing` é chamada diretamente por este módulo.
- `tests/test_odds_evaluation_api.py` — 5 testes HTTP: avaliação de
  `aces_player` confirmado (Baez × Brooksby, dados reais), `total_games` não
  modelado, upload inexistente (404), upload não confirmado (404), contexto de
  partida indisponível (422).
- `web/src/pages/ScreenshotUploadPage.test.tsx` — 9 testes novos: botão
  "Avaliar no Radar" após confirmação, "Comparando com o modelo…", PASSOU DO
  LIMITE, OBSERVAR, NÃO PASSOU DO LIMITE, mercado sem modelo, erro com "Tentar
  novamente", detalhes técnicos colapsáveis (fechado por padrão), aviso de
  defasagem preservado.

### Achado incidental (corrigido, fora do escopo do pedido)

`npm run build` (`tsc -b`) falhou por um erro de tipo **pré-existente** em
`ScreenshotUploadPage.test.tsx` (teste "mostra 'Analisando imagem...'" do LOTE
F, linha com `let resolveExtract: (value: unknown) => void`), não relacionado
a este lote — o mesmo padrão que eu precisava usar para o novo teste de
"Comparando com o modelo…" (`resolveEvaluate`) teria o mesmo problema.
Corrigido tipando explicitamente `Promise<ExtractionResponse>`/`Promise<EvaluateResponse>`
em vez de `unknown`, nas duas ocorrências — mudança de anotação de tipo só,
sem alterar nenhum comportamento de teste existente. Reportado aqui em vez de
escondido, conforme CLAUDE.md §23.

### Resultado do build e das suítes

```
cd web && npm run build      # tsc -b && vite build -- sem erros de tipo
npm run test -- --run        # 52/52 testes (4 arquivos; 9 novos em
                              # ScreenshotUploadPage.test.tsx)
```

```
python -m unittest discover -s tests -p "test_*.py"
Ran 416 tests in 616.079s

OK
```

416/416 testes passando (14 novos: 9 em `test_screenshot_evaluation.py` + 5 em
`test_odds_evaluation_api.py`). Resultado completo capturado em
`full_suite_output_lote_g.txt` (execução em background) — os mesmos dois
trechos "ruidosos" já documentados nos LOTEs A-F (traceback proposital de
`tests/test_api.py`, mensagem de `argparse` de `daily_forward_workflow.py`)
aparecem no meio da saída, esperados, não falhas. Nenhuma regressão sobre o
motor estatístico, `api/` ou os lotes anteriores da PWA.

### Limitações encontradas

- `double_faults_player` está em `src.decision.config.ALLOWED_MARKETS`, mas o
  LOTE F ainda não extrai esse mercado de nenhum print (`SUPPORTED_MARKETS`
  do `screenshot_parser` não o inclui) — o adapter já sabe avaliá-lo (mesmo
  caminho de `aces_player`), mas isso só será exercitado quando um lote futuro
  do parser passar a suportar esse mercado.
- `total_games` continua sem contrapartida operacional nas Fases 6/7/9/10
  (confirmado nesta entrega: `src.probabilistic.config.MARKETS` não o inclui)
  — mostrado como "Mercado ainda não disponível para avaliação pelo modelo.",
  nunca inventado. Decisão de modelar esse mercado continua fora de escopo
  (CLAUDE.md §19: dados decidem, não este lote).
- A avaliação sempre reprocessa o HISTÓRICO COMPLETO de `comparison_with_model.parquet`
  via `src.decision.build.run()` (mesmo comportamento de
  `scripts/evaluate_opportunities.py` hoje) — aceitável no volume atual
  (uso local, poucas partidas por dia), registrado como algo a observar se o
  histórico crescer muito (mesmo risco R10 já documentado na seção 12).
- Nenhum forward test é registrado por este lote (pedido explícito) — a
  ligação entre "PASSOU DO LIMITE" na tela e um registro no Forward Test
  (Fase 11) continua sendo uma decisão manual do usuário, fora de escopo aqui.

---

**LOTE G concluído. Não iniciar o LOTE H (Forward Test) sem nova autorização.
Pare ao concluir.**

---

## 22. LOTE H — CONCLUÍDO

Exposta na PWA a Fase 11 (Forward Test) já existente. A API **só lê,
organiza e apresenta** o que `src.forward` já calculou
(`data/outputs/phase11/*.parquet`/`phase11_summary.json`) — nenhuma fórmula
de resultado/settlement/paper test/CLV/Brier/Log Loss/ROI/métrica acumulada
foi reimplementada. A única escrita nova é o registro de **uma** oportunidade
por vez, disparado só pelo clique explícito em "Registrar no Forward Test"
(nunca automático, nunca em lote — isso continua sendo `register_day`, não
tocado).

### Fontes inspecionadas (antes de qualquer código)

`src/forward/{build,config,ids,predictions,inputs,settlement,results,
odds_snapshots,paper_test,clv,metrics,labels,versioning}.py` e os 5 scripts
CLI (`forward_register.py`, `forward_record_odds.py`, `forward_settle.py`,
`forward_report.py`, `run_forward_day.py`) — todas as funções usadas pela API
já existiam; nenhuma regra de settlement/métrica foi alterada.

### Arquivos criados/alterados

```
src/forward/build.py                   # (editado: +register_opportunity,
                                        # +is_registered -- registro de UMA
                                        # oportunidade, reaproveitando
                                        # inputs.load_opportunities_for_registration
                                        # + predictions.register_predictions
                                        # + o mesmo snapshot inicial que
                                        # register_day ja grava; nenhuma
                                        # regra nova de settlement/metrica)

src/odds/screenshot_evaluation.py      # (editado: +campo `forward_key` no
                                        # resultado de cada mercado avaliado
                                        # -- a MESMA chave natural ja usada
                                        # internamente para casar contra
                                        # `evaluated`, so exposta pra fora;
                                        # zero formula nova, ver nota abaixo)
api/schemas/odds_evaluation.py         # (editado: +ForwardKey,
                                        # +prediction_id/
                                        # already_registered_forward_test)
api/services/odds_evaluation_service.py# (editado: +calculo de
                                        # prediction_id/already_registered
                                        # via src.forward.ids/build.is_registered)

api/schemas/forward.py                 # NOVO -- contratos do resumo, lista,
                                        # detalhe e registro
api/services/forward_service.py        # NOVO -- leitura/organizacao sobre
                                        # forward_predictions/settlements/
                                        # paper_test/clv_analysis parquet
api/routes/forward.py                  # NOVO -- 4 endpoints (ver secao abaixo)
api/main.py                            # (editado: +router forward)

web/src/types/api.ts                   # (editado: +ForwardKey e todos os
                                        # tipos de api/schemas/forward.py)
web/src/services/api.ts                # (editado: +getForwardSummary,
                                        # getForwardPredictions,
                                        # getForwardPrediction,
                                        # registerForwardPrediction)
web/src/lib/forward.ts                 # NOVO -- rotulos PT (classificacao,
                                        # settlement, mercado/lado reaproveitados
                                        # de lib/radar.ts)
web/src/pages/ForwardPage.tsx          # NOVO -- tela FORWARD TEST (resumo,
                                        # paper test, detalhes tecnicos,
                                        # filtros, lista paginada)
web/src/pages/ForwardPredictionDetailPage.tsx  # NOVO -- detalhe de uma previsao
web/src/pages/ForwardPage.test.tsx     # NOVO -- 10 testes
web/src/pages/ForwardPredictionDetailPage.test.tsx  # NOVO -- 7 testes
web/src/pages/ScreenshotUploadPage.tsx # (editado: +botao "Registrar no
                                        # Forward Test" para PASSOU_DO_LIMITE/
                                        # OBSERVAR, "Ja registrado" quando aplicavel)
web/src/pages/ScreenshotUploadPage.test.tsx  # (editado: +7 testes do botao)
web/src/App.tsx                        # (editado: rotas /forward e
                                        # /forward/:predictionId deixam de
                                        # ser PlaceholderPage)
web/src/App.test.tsx                   # (editado: teste de navegacao
                                        # provisoria passa a usar "Config",
                                        # unica area ainda placeholder)

tests/test_forward_registration.py     # NOVO -- 6 testes de
                                        # register_opportunity/is_registered
tests/test_forward_api.py              # NOVO -- 14 testes de integracao HTTP
tests/test_odds_evaluation_api.py      # (editado: +2 testes -- forward_key/
                                        # prediction_id no endpoint do LOTE G)
```

### Nota sobre o campo `forward_key` (LOTE G ↔ LOTE H)

A instrução deste lote proíbe alterar `src/odds` e `src/decision`. Para o
botão "Registrar no Forward Test" funcionar sem duplicar o join que o LOTE G
já faz (`screenshot_evaluation.evaluate_confirmed` já casa a leitura
confirmada contra `opportunities_evaluated.parquet`), o frontend precisa da
mesma chave natural (`bookmaker, tour, match_id, market, player, side, line,
decimal_odds, collected_at`) que essa função já tem em mãos internamente.
A alternativa seria re-implementar esse casamento em outro lugar — isso sim
seria a duplicação de cálculo que o pedido proíbe explicitamente. A decisão
tomada foi expor esse dicionário (`forward_key`, já calculado, nenhuma
probabilidade/odd/edge nova) como um campo adicional do **adapter do LOTE G**
(`src/odds/screenshot_evaluation.py`, não uma fórmula da Fase 9/10 em si) —
registrado aqui explicitamente para o usuário validar essa leitura da
instrução antes de prosseguir para o LOTE I.

### Registro de uma oportunidade (`register_opportunity`)

```
forward_key (bookmaker, tour, match_id, market, player, side, line,
             decimal_odds, collected_at)
        |
        v
inputs.load_opportunities_for_registration()   # mesmo join do register_day
        |
        v
filtra a MESMA linha pela chave completa (nunca "a mais provável")
        |
        v
predictions.register_predictions([linha])      # mesma imutabilidade/dedup
        |
        v
odds_snapshots.append_snapshots(primeiro snapshot)  # mesma logica do register_day
```

Estados devolvidos: `registered` (nova previsão), `already_registered`
(reenvio idêntico — nunca duplicado), `not_found` (a oportunidade não está
em `opportunities_evaluated.parquet` — ex.: cache do frontend desatualizado),
`rejected_overwrite_attempt` (mesmo `prediction_id`, valores diferentes —
imutabilidade da Fase 11, item 1). Idempotência usa o **mesmo**
`prediction_id` estável já definido em `src.forward.ids.make_prediction_id`
(hash da chave natural) — nenhum identificador novo foi inventado.

### Endpoints novos

| Método | Rota | Fonte |
|---|---|---|
| `GET` | `/api/forward/summary` | `forward_predictions.parquet` + `settlements.parquet` (contagens) + `paper_test.parquet` (resumo, via `paper_test.summarize_paper_test`) + Brier/Log Loss/calibração/CLV/ROI por mercado (via `metrics.with_outcome`/`calibration_by_bucket` + `clv_analysis.parquet`/`paper_test.parquet`, as MESMAS funções que `cumulative_dashboard` já chama para o texto) |
| `GET` | `/api/forward/predictions` | `forward_predictions.parquet` + `settlements.parquet`, com filtros `tour`, `settlement_group` (pendentes/resolvidas), `classification_group` (candidato — agrega FRACO/normal/FORTE, observar, descartado) e paginação (`limit`/`offset`) |
| `GET` | `/api/forward/predictions/{prediction_id}` | idem + `paper_test.parquet` (pnl da linha) + `odds_snapshots.summarize_odds_movement` (histórico de odds) + `clv_analysis.parquet` (CLV, quando disponível) |
| `POST` | `/api/forward/register` | `src.forward.build.register_opportunity` (ver acima) |

`POST /api/forward/settle` **não foi implementado** — settlement/registro de
resultado real continuam operados via CLI (`scripts/forward_settle.py`,
`daily_forward_workflow.py`), pela mesma razão do LOTE F/G: entrada manual de
resultado é uma decisão de fluxo (quando o usuário sabe o placar real), não
"leitura e apresentação", e implementar só a metade (exibir sem permitir
registrar) seria uma implementação parcial sem necessidade clara —
documentado como limitação, não escondido.

### Tela FORWARD TEST

RESUMO (registradas/pendentes/resolvidas/candidatos/observar/descartados) →
RESULTADOS (acertos/erros/anulados/pendentes) → PAPER TEST (rótulo
`PAPER_TEST_ONLY`, nunca linguagem de lucro garantido) → "Detalhes técnicos"
colapsado por padrão (Brier/Log Loss geral, calibração por faixa, Brier/CLV
médio/Paper ROI por mercado) → lista de previsões com filtros (tour,
pendentes/resolvidas, candidato/observar/descartado) e paginação simples
(20 por página, nunca carrega tudo de uma vez). Cada linha abre
`/forward/{prediction_id}`: partida, mercado, linha, probabilidade do
modelo, odd justa, odd mínima (mesma técnica de seleção de coluna já
congelada do LOTE G — nunca recalcula `minimum_acceptable_odds`), odd
observada, classificação, resultado, paper result, histórico de odds
(primeira/última/fechamento observado) e CLV — com "Detalhes técnicos"
(implied probability, edge, amostra, restrição, defasagem, motivos/alertas)
também colapsado por padrão.

### Integração com o LOTE G

Na tela RESULTADO DA ANÁLISE, resultados **PASSOU DO LIMITE** e **OBSERVAR**
ganham o botão "Registrar no Forward Test" (comportamento só de interface —
nenhuma regra estatística nova; a Fase 11 já registra qualquer classificação,
inclusive DESCARTAR, via `register_day`/item 4 — só a **sugestão** do botão
na PWA é restrita, não a capacidade do backend). Ao clicar: chama
`POST /api/forward/register`; sucesso → "Já registrado no Forward Test";
erro → mensagem do backend, botão continua disponível para tentar de novo.

### Idempotência

Usa o `prediction_id` estável já definido (hash de bookmaker/tour/match_id/
market/player/side/line, `src.forward.ids.make_prediction_id`) — nenhum
identificador novo foi criado. Clicar duas vezes no mesmo resultado avaliado
é seguro (segunda chamada devolve `already_registered`, nenhuma duplicata).

### Testes

- `tests/test_forward_registration.py` — 6 testes: registro novo, reenvio
  idêntico (idempotente, nunca duplica), oportunidade inexistente,
  `is_registered` para id desconhecido, primeiro snapshot gravado no
  registro, mercado diferente não casa.
- `tests/test_forward_api.py` — 14 testes: resumo/lista/detalhe vazios,
  previsões registradas mas não settled (métricas ausentes, nunca
  inventadas), resumo com dados settled (contagens de classificação e de
  resultado), filtros (tour, classification_group, settlement_group),
  paginação, detalhe com settlement/paper/técnico, registro válido/
  duplicado/inexistente via HTTP.
- `tests/test_odds_evaluation_api.py` — 2 testes novos: `forward_key`/
  `prediction_id` presentes e corretos para mercado avaliado; ausentes para
  mercado não modelado.
- `web/src/pages/ForwardPage.test.tsx` — 10 testes: loading, erro, vazio,
  resumo com dados, métricas ausentes vs. presentes, filtros (tour e
  classificação, verificando os parâmetros enviados à API), previsão
  pendente vs. resolvida, paginação.
- `web/src/pages/ForwardPredictionDetailPage.test.tsx` — 7 testes: loading,
  404, erro genérico, dados completos, CLV/histórico de odds ausentes,
  detalhes técnicos colapsáveis (fechado por padrão, verificado via
  `<details>.open`, não por presença no DOM — jsdom não aplica o CSS que
  esconde o conteúdo fechado), previsão pendente sem paper result.
- `web/src/pages/ScreenshotUploadPage.test.tsx` — 7 testes novos: botão
  aparece para PASSOU_DO_LIMITE/OBSERVAR, ausente para NÃO_PASSOU/SEM_MODELO,
  registro com sucesso ("Já registrado no Forward Test"), estado já
  registrado vindo direto da API, erro de registro (botão continua
  disponível).

### Resultado do build e das suítes

```
cd web && npm run build      # tsc -b && vite build -- sem erros de tipo
npm run test -- --run        # 76/76 testes (6 arquivos; 24 novos deste lote)
```

```
python -m unittest discover -s tests -p "test_*.py"
Ran 437 tests in 536.188s

OK
```

437/437 testes passando (22 novos: 6 em `test_forward_registration.py` + 14
em `test_forward_api.py` + 2 em `test_odds_evaluation_api.py`). Resultado
completo capturado em `full_suite_output_lote_h.txt` (execução em
background) — os mesmos dois trechos "ruidosos" já documentados nos LOTEs
A-G (traceback proposital de `tests/test_api.py`, mensagem de `argparse` de
`daily_forward_workflow.py`) aparecem no meio da saída, esperados, não
falhas. Nenhuma regressão sobre o motor estatístico, `api/` ou os lotes
anteriores da PWA.

### Limitações encontradas

- `POST /api/forward/settle` (registro de resultado real / recálculo de
  settlement) não foi implementado na PWA — ver seção "Endpoints novos"
  acima. Continua operado via `scripts/forward_settle.py`/
  `daily_forward_workflow.py`.
- `GET /api/forward/summary` recalcula `calibration_by_bucket` a cada
  chamada (chamando a função já existente sobre os dados já persistidos,
  nunca reimplementando a fórmula) porque essa tabela não é persistida em
  nenhum parquet pela Fase 11 (só aparece dentro do texto de
  `cumulative_dashboard`) — custo aceitável no volume atual (poucas
  centenas de previsões), mesmo raciocínio do risco R10 já documentado.
- O botão "Registrar no Forward Test" depende do campo `forward_key`
  devolvido pela avaliação do LOTE G (mesma sessão/requisição) — se o
  usuário reabrir a tela de avaliação depois de muito tempo (ou de um
  reload), precisa clicar "Avaliar no Radar" de novo antes de registrar
  (nenhum cache adicional foi criado para evitar isso, fora do pedido).
- Filtro de classificação usa 3 grupos (candidato/observar/descartado, o
  mesmo agrupamento do LOTE G) em vez dos 5 estados brutos da Fase 10 — se
  um lote futuro precisar filtrar por `CANDIDATO_FRACO` isoladamente, o
  backend já devolve `classification` completo em cada item da lista;
  faltaria só o parâmetro de filtro mais granular, não um dado novo.

---

## 23. LOTE I — CONCLUÍDO

Launcher local para uso diário sem terminal. Só orquestra processos já
existentes (uvicorn e o dev server do Vite, exatamente como já rodavam
manualmente) e abre o navegador — nenhuma linha de `src/`, `api/` (além do
já existente `GET /api/health`) ou `web/src/` foi alterada. Radar, odds,
screenshot parser, forward test e calendário não foram tocados.

### Nota sobre escopo (seção 14 previa também uma tela CONFIGURAÇÕES)

O plano original da seção 14 listava "LOTE I — Launcher local" com a tela
CONFIGURAÇÕES junto. A instrução recebida para este lote pediu
explicitamente **somente** o launcher (`.bat`/PowerShell, PID, logs,
health-check, abertura do navegador) e não mencionou nenhuma tela nova —
por isso a tela CONFIGURAÇÕES **não foi criada** aqui. `web/src/App.tsx`
continua com a rota de configurações como `PlaceholderPage` (mesmo estado
do LOTE H). Registrado aqui para o usuário validar essa leitura antes de um
lote futuro cobrir essa tela.

### Arquivos criados

```
INICIAR_TENNIS_RADAR.bat               # NOVO -- entrada por duplo clique
ENCERRAR_TENNIS_RADAR.bat              # NOVO -- entrada por duplo clique
CRIAR_ATALHO_TENNIS_RADAR.bat          # NOVO -- opcional, cria atalho na
                                        # Area de Trabalho via WScript.Shell
scripts/launcher/common.ps1            # NOVO -- funcoes auxiliares
                                        # (Test-TcpPort, Test-HttpOk,
                                        # Wait-ForHttp, limpeza de PID orfao)
scripts/launcher/start_tennis_radar.ps1# NOVO -- sobe backend+frontend,
                                        # health-check, abre navegador
scripts/launcher/stop_tennis_radar.ps1 # NOVO -- encerra so os processos
                                        # rastreados por .runtime/*.pid
.gitignore                             # (editado: +.runtime/)
README.md                              # (editado: +secao "Uso diario")
```

Nenhum arquivo de `src/`, `api/` ou `web/src/` foi criado/alterado.

### Como iniciar

Duplo clique em `INICIAR_TENNIS_RADAR.bat` (raiz do projeto). O `.bat`
resolve o diretório do projeto por `%~dp0` (nunca caminho fixo) e chama
`scripts/launcher/start_tennis_radar.ps1 -Root <esse diretório>` via
`powershell -NoProfile -ExecutionPolicy Bypass -File`.

Sequência executada:

1. verifica `python` no PATH e `import fastapi, uvicorn` (se faltar, erro
   com o comando exato para corrigir — nunca instala nada sozinho);
2. verifica `node`/`npm` no PATH e `web/node_modules/vite/bin/vite.js`
   presente (se faltar, erro pedindo `npm install` dentro de `web/`);
3. **backend**: se a porta 8000 já responde `GET /api/health` com 200,
   reaproveita; se a porta está livre, inicia
   `python -m uvicorn api.main:app --host 127.0.0.1 --port 8000` (mesmo
   comando já validado no LOTE A) e aguarda até 60s o health responder;
4. **frontend**: se a porta 5173 já responde HTTP 200, reaproveita; se
   livre, inicia o dev server do Vite diretamente via
   `node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173
   --strictPort` (equivalente a `npm run dev`, ver decisão abaixo) e
   aguarda até 60s responder;
5. só então abre `http://localhost:5173` no navegador padrão e imprime
   "Tennis Radar iniciado com sucesso.".

Se qualquer verificação falhar, o script imprime o erro exato (porta
ocupada, dependência ausente, timeout) e **não** abre o navegador nem
finge sucesso — `exit 1`. O `.bat` faz `pause` no final (sucesso ou erro)
para a janela não fechar sozinha antes do usuário ler a mensagem.

### Como encerrar

Duplo clique em `ENCERRAR_TENNIS_RADAR.bat`. Ele chama
`scripts/launcher/stop_tennis_radar.ps1`, que:

1. lê `.runtime/frontend.pid` e `.runtime/backend.pid`;
2. para cada um: se o PID não existe mais, só remove o arquivo; se existe,
   roda `taskkill /PID <pid> /T /F` (mata a árvore daquele PID especifico
   — nunca `taskkill /IM python.exe` ou `/IM node.exe`, que atingiria
   outros projetos) e remove o arquivo de PID;
3. se não há arquivo de PID (processo não foi iniciado por este launcher,
   ou já foi encerrado antes), avisa e não faz nada.

Logs (`*.log`/`*.err.log`) **não** são apagados pelo encerramento — só os
`*.pid`.

### Portas

| Serviço | Porta | Bind |
|---|---|---|
| Backend (FastAPI/uvicorn) | 8000 | `127.0.0.1` (nunca `0.0.0.0`, já era assim desde o LOTE A) |
| Frontend (Vite dev server) | 5173 | `127.0.0.1` explícito via `--host 127.0.0.1` |

### Comportamento com porta ocupada

- Ocupada pelo **próprio** serviço já rodando corretamente (health/HTTP
  responde 200): reaproveita, não sobe uma segunda instância.
- Ocupada por **outro processo** (não responde no contrato esperado):
  erro claro ("porta X já está em uso por outro processo... Abortando —
  nada foi encerrado") e o script para ali — nunca mata processos para
  liberar a porta.

### Arquivos de runtime (`.runtime/`, no `.gitignore`)

```
.runtime/backend.pid       # PID do uvicorn (só existe se ESTE launcher o iniciou)
.runtime/frontend.pid      # PID do vite (idem)
.runtime/backend.log       # stdout do uvicorn
.runtime/backend.err.log   # stderr do uvicorn
.runtime/frontend.log      # stdout do vite
.runtime/frontend.err.log  # stderr do vite
```

### Frontend: dev server, não build de produção

Avaliadas as duas opções pedidas:

- **A) `npm run dev`** — já 100% implementado e testado desde o LOTE B: o
  proxy `/api → http://127.0.0.1:8000` já existe em `web/vite.config.ts`,
  já foi validado ponta a ponta em todo lote B–H ("Verificação end-to-end
  real (servidor + proxy)"), CORS já libera exatamente
  `localhost:5173`/`127.0.0.1:5173`.
- **B) servir `web/dist`** — exigiria decidir e implementar uma peça nova
  que hoje não existe: algo servindo os estáticos **e** repassando
  `/api/*` para o backend (FastAPI não monta estáticos hoje; um servidor
  estático puro não sabe fazer proxy). Seria arquitetura nova para este
  lote, que pediu explicitamente para não inventar arquitetura.

Decisão: **opção A**, dev server do Vite. É o que já existe, já testado,
sem CORS/proxy para reconfigurar. O launcher invoca o mesmo binário que
`npm run dev` executaria (`node_modules/vite/bin/vite.js`) diretamente via
`node`, em vez de passar por `npm.cmd` — evita um problema conhecido do
Windows (`Start-Process` com redirecionamento de saída não consegue
executar `.cmd` diretamente) e resulta num único processo Node rastreável
por PID, sem processo intermediário para encerrar depois.

Um efeito colateral encontrado e corrigido durante o teste manual: sem
`--host` explícito, o Vite 8 nesta máquina ficou escutando só em
`[::1]:5173` (IPv6), e o health-check em `127.0.0.1:5173` nunca respondia
mesmo com o Vite pronto. Corrigido passando `--host 127.0.0.1` (mesmo
princípio do backend: bind explícito, nunca ambíguo).

### Verificação manual end-to-end (sem mocks)

```
INICIAR_TENNIS_RADAR.bat (via powershell -File, mesmo caminho do .bat)
  -> python/uvicorn OK, node/vite OK
  -> backend iniciado, PID gravado, /api/health respondeu em ~1s
  -> frontend iniciado, PID gravado, http://127.0.0.1:5173/ respondeu
  -> GET http://127.0.0.1:5173/api/health (proxy do Vite) -> 200 (mesmo
     JSON do backend)
  -> navegador aberto em http://localhost:5173

Rodado uma 2a vez com os dois servicos no ar:
  -> "Backend ja esta rodando... (reaproveitando)"
  -> "Frontend ja esta rodando... (reaproveitando)"
  -> nenhum processo duplicado

Porta 8000 ocupada por processo alheio (servidor HTTP de teste, nao
Tennis Radar):
  -> "ERRO: porta 8000 ja esta em uso por outro processo... Abortando --
     nada foi encerrado."
  -> exit code 1, frontend nem chegou a subir, processo alheio intocado

ENCERRAR_TENNIS_RADAR.bat
  -> taskkill /PID <backend> /T /F, taskkill /PID <frontend> /T /F
  -> portas 8000 e 5173 livres em seguida (confirmado via netstat)
  -> .runtime/*.pid removidos, .runtime/*.log preservados

ENCERRAR_TENNIS_RADAR.bat rodado de novo (nada para encerrar):
  -> "nenhum PID registrado (nao foi iniciado por este launcher, ou ja
     foi encerrado)." para os dois -- nenhuma acao, nenhum erro
```

### Resultado da suíte completa (pós-LOTE I)

```
cd web && npm run build      # tsc -b && vite build -- sem erros de tipo,
                              # PWA (sw.js/workbox) gerado normalmente
npm run test -- --run        # 76/76 testes (nenhum teste novo -- este
                              # lote nao mexeu em web/src/)
```

```
python -m unittest discover -s tests -p "test_*.py"
```

Resultado completo em `full_suite_output_lote_i.txt`. Nenhum teste novo em
`tests/` (este lote não mexeu em `src/`/`api/`) — a suíte foi rodada só
para confirmar zero regressão, mesma contagem de testes do LOTE H
(437/437).

### Limitações encontradas

- **Tela CONFIGURAÇÕES** prevista na seção 14 para este lote não foi
  criada — ver nota de escopo no início desta seção.
- **Health-check do frontend** confirma só que o dev server do Vite
  respondeu HTTP 200 na raiz — não confirma que o proxy `/api` está de
  fato repassando para o backend (isso foi validado manualmente na
  verificação end-to-end acima, mas não é checado a cada `INICIAR_...`).
  Se o backend cair depois do health-check inicial, o launcher não
  percebe — o app na PWA mostraria erro de rede normalmente.
- **Backend "de fora" na porta 8000**: se alguém já tiver um Tennis Radar
  rodando fora do launcher (ex.: terminal manual) e o `.runtime/backend.pid`
  não existir, `INICIAR_...` reaproveita normalmente, mas
  `ENCERRAR_TENNIS_RADAR.bat` não vai derrubá-lo (não há PID rastreado) —
  comportamento esperado, dado que o pedido proíbe encerrar processos que
  este launcher não iniciou.
- **`node_modules` ausente**: o launcher só verifica e informa o comando
  (`npm install` dentro de `web/`); não instala nada sozinho, para não
  rodar uma operação potencialmente demorada/surpreendente num duplo
  clique silencioso.
- Sem `--reload` no uvicorn (igual ao comando já documentado no LOTE A) —
  mudanças em `api/`/`src/` exigem `ENCERRAR_...` + `INICIAR_...` de novo
  para ter efeito; comportamento inalterado em relação ao uso manual de
  antes deste lote.

---

**LOTE I concluído. Não iniciar nenhum lote adicional sem nova
autorização. Pare ao concluir.**
