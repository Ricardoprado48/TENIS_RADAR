# 003 — REGRAS ESTATÍSTICAS

## Regra 1 — Point-in-time

Uma partida só pode ser prevista com dados disponíveis antes dela.

## Regra 2 — Matchup

Sempre calcular:

Serve A × Return B

Serve B × Return A

## Regra 3 — Superfície

Separar:

- hard;
- clay;
- grass.

## Regra 4 — Estatísticas por oportunidade

Preferir taxas.

Exemplo:

Ace Rate = Aces / Service Points

em vez de somente Aces por Partida.

## Regra 5 — Ajuste pelo adversário

Sempre que possível, ajustar estatísticas pela qualidade dos adversários enfrentados.

## Regra 6 — Recência

Testar diferentes janelas e pesos.

Não definir uma janela como verdadeira sem backtest.

## Regra 7 — Baselines

Modelos complexos precisam superar modelos simples.

## Regra 8 — Backtest

Usar walk-forward.

Nunca permitir vazamento temporal.

## Métricas principais

Numéricas:

- MAE
- RMSE

Probabilísticas:

- Brier Score
- Log Loss
- Calibration

## Aces

Investigar:

- Ace%;
- Ace Allowed%;
- service points;
- return points;
- superfície;
- oposição;
- duração esperada.

## Games

Investigar:

- hold%;
- break%;
- service points won;
- return points won;
- tie-break probability;
- distribuição de sets.

## Double faults

Investigar taxa por service point e estabilidade por jogador/superfície.
