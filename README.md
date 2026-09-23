# Tennis Radar

Projeto de pesquisa estatística para mercados pré-jogo de tênis.

## Objetivo atual

Descobrir quais mercados possuem maior previsibilidade estatística utilizando dados históricos disponíveis antes de cada partida.

Mercados iniciais:

- Aces por jogador
- Total de aces
- Total de games
- Handicap de games
- Double faults
- Total de sets
- Tie-break

## Princípio central

Toda análise deve considerar o confronto:

Serve A × Return B

Serve B × Return A

Não analisar jogador isoladamente.

## Status

Fase 0 — Pesquisa e disponibilidade das fontes de dados.

Não existe produto final, interface ou integração com casas nesta etapa.

## Uso diário

1. Duplo clique em `INICIAR_TENNIS_RADAR.bat`.
2. Use a aplicação no navegador (abre sozinho em `http://localhost:5173`).
3. Ao terminar, execute `ENCERRAR_TENNIS_RADAR.bat`.

Detalhes (portas, logs, comportamento em erro) em
`docs/018_PWA_ARQUITETURA.md`, seção "LOTE I".
