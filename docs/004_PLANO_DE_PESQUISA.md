# 004 — PLANO DE PESQUISA

## Fase 0 — Fontes

Objetivo:

Identificar as melhores fontes gratuitas.

Saída:

- fontes aprovadas;
- campos disponíveis;
- limitações;
- plano de ingestão.

---

## Fase 1 — Ingestão

Baixar dados históricos.

Preservar arquivos originais em:

data/raw

---

## Fase 2 — Normalização

Criar dataset padronizado.

Resolver:

- IDs;
- nomes;
- datas;
- torneios;
- superfícies;
- estatísticas.

Salvar em:

data/processed

---

## Fase 3 — Features

Criar:

- serve profile;
- return profile;
- surface profile;
- recent form;
- opponent-adjusted metrics.

Sempre:

Serve A × Return B

Serve B × Return A

---

## Fase 4 — Baselines

Construir modelos simples para:

- aces;
- total aces;
- total games;
- handicap;
- double faults;
- sets.

---

## Fase 5 — Backtest

Walk-forward cronológico.

Sem leakage.

---

## Fase 6 — Comparação

Criar tabela:

| Mercado | MAE | RMSE | Brier | Estabilidade | Amostra |
|---|---:|---:|---:|---:|---:|
| Aces jogador | | | | | |
| Total aces | | | | | |
| Total games | | | | | |
| Handicap games | | | | | |
| Double faults | | | | | |
| Total sets | | | | | |

---

## Fase 7 — Seleção

Escolher somente mercados que demonstrem robustez fora da amostra.

---

## Fases posteriores

Somente depois da validação:

- partidas atuais;
- odds justas;
- odd mínima;
- consulta pontual de casas;
- interface;
- alertas.
