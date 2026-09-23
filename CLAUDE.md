# TENNIS RADAR — CLAUDE.md

## 1. Objetivo

Tennis Radar é um projeto de pesquisa estatística pré-jogo para tênis.

O objetivo atual NÃO é criar:
- interface;
- sistema de apostas;
- automação de apostas;
- integração com casas;
- scraping massivo de odds.

A primeira missão é descobrir quais mercados de tênis possuem maior previsibilidade estatística usando dados disponíveis antes de cada partida.

Mercados iniciais:

1. Aces por jogador
2. Total de aces
3. Total de games
4. Handicap de games
5. Double faults
6. Total de sets
7. Tie-break quando houver dados adequados

Não assumir antecipadamente qual mercado é melhor.

Os dados devem decidir.

---

## 2. Regra fundamental: matchup

Nenhuma previsão pode considerar somente o jogador analisado.

Tênis é uma interação entre dois jogadores.

Sempre considerar:

Serve A × Return B

e

Serve B × Return A

Exemplo:

Um jogador com Ace% alto não deve automaticamente receber projeção alta de aces.

É obrigatório considerar também:

- qualidade da devolução do adversário;
- Ace% permitido pelo devolvedor;
- qualidade dos sacadores enfrentados pelo devolvedor;
- superfície;
- quantidade esperada de pontos de saque;
- duração esperada da partida;
- contexto temporal.

Essa regra também vale para:

- hold;
- break;
- total games;
- handicap;
- double faults;
- tie-breaks.

---

## 3. Dados point-in-time

É proibido utilizar informações futuras para prever uma partida passada.

Para prever uma partida na data T:

usar somente informações disponíveis antes de T.

Exemplo correto:

partidas anteriores -> features -> previsão -> partida seguinte

Exemplo proibido:

estatísticas da temporada completa -> prever partida ocorrida no meio daquela temporada.

Todo backtest deve respeitar esta regra.

---

## 4. Backtesting

Utilizar preferencialmente walk-forward validation.

Para cada partida:

1. montar features usando somente partidas anteriores;
2. gerar previsão;
3. registrar previsão;
4. comparar com resultado real;
5. avançar cronologicamente.

Nunca usar split aleatório simples quando existir risco de vazamento temporal.

Registrar:

- data da partida;
- data da previsão;
- modelo;
- parâmetros;
- features utilizadas;
- valor previsto;
- probabilidade prevista;
- resultado real;
- erro.

---

## 5. Estatísticas de saque

Investigar:

- Ace%;
- aces por service point;
- first serve%;
- first serve points won;
- second serve points won;
- service points won;
- service games;
- hold%;
- double fault%;
- break points saved;
- desempenho por superfície;
- desempenho recente;
- desempenho ajustado por adversário.

Evitar médias absolutas quando existir medida por oportunidade.

Exemplo:

Preferir:

aces / service points

em vez de apenas:

aces / partida.

---

## 6. Estatísticas de devolução

Investigar:

- Ace% sofrido;
- aces sofridos por return point;
- return points won;
- first serve return points won;
- second serve return points won;
- break%;
- break points created;
- break points converted;
- qualidade dos adversários enfrentados;
- desempenho por superfície;
- desempenho recente.

Criar métricas opponent-adjusted sempre que possível.

Exemplo:

Ace Suppression =
taxa esperada de aces contra os sacadores enfrentados
versus
taxa realmente sofrida.

---

## 7. Ajuste pela força do adversário

Não utilizar estatísticas brutas sem considerar a força dos adversários quando isso puder distorcer a análise.

Exemplo:

Um jogador que sofreu poucos aces contra sacadores fracos não deve automaticamente ser classificado como excelente devolvedor.

Sempre que possível, construir métricas ajustadas pelo adversário.

---

## 8. Superfície

Separar obrigatoriamente:

- hard;
- clay;
- grass.

Quando os dados existirem, investigar também:

- indoor/outdoor;
- altitude;
- velocidade da quadra;
- torneio.

Não adicionar variáveis sem testar ganho real.

---

## 9. Recência

Resultados recentes podem receber maior peso.

Testar diferentes abordagens:

- últimas 10 partidas;
- últimas 20;
- últimas 50;
- últimos 12 meses;
- histórico completo ponderado por tempo.

Não escolher janela arbitrariamente.

Comparar por backtest.

---

## 10. Identidade dos jogadores

Criar identidade canônica dos jogadores desde o início.

Não utilizar somente nome textual como identificador definitivo.

Manter quando possível:

- player_id;
- nome canônico;
- aliases;
- nome na fonte original;
- ATP/WTA;
- país;
- data de nascimento;
- mão dominante.

Evitar duplicatas por:

- acentos;
- abreviações;
- grafias diferentes;
- mudança de sobrenome.

---

## 11. Dados brutos

Nunca sobrescrever dados brutos.

Estrutura:

data/raw
= fonte original imutável

data/processed
= dados normalizados

data/outputs
= relatórios, métricas e previsões

Preservar sempre que possível:

- fonte;
- URL;
- data de coleta;
- timestamp;
- schema;
- versão.

---

## 12. Prioridade das fontes

Usar nesta ordem quando possível:

1. dataset estruturado;
2. CSV / Parquet;
3. API oficial;
4. HTTP simples;
5. HTML;
6. Firecrawl;
7. Playwright / browser automation.

Não usar solução complexa quando uma fonte estruturada resolver.

---

## 13. Fontes iniciais

Investigar prioritariamente:

- Jeff Sackmann Tennis Data;
- Tennis Abstract;
- outras fontes públicas documentadas.

Antes de automatizar uma fonte, verificar:

- cobertura histórica;
- ATP/WTA;
- estatísticas disponíveis;
- formato;
- estabilidade;
- licença;
- termos de uso;
- limitações.

Não criar dependência crítica de fonte frágil sem documentar o risco.

---

## 14. Odds

Odds não são requisito da fase inicial.

Primeiro avaliar capacidade preditiva do modelo contra resultados reais.

Posteriormente:

probabilidade -> odd justa

Fórmula:

odd_justa = 1 / probabilidade

Exemplo:

probabilidade = 0.625

odd justa = 1 / 0.625 = 1.60

Depois poderá ser definida uma margem de segurança e uma odd mínima aceitável.

Não afirmar existência de value sem comparação com odds reais e validação adequada.

---

## 15. Casas de apostas

Não integrar casas de apostas nesta fase.

Não implementar:

- login automatizado;
- colocação automática de apostas;
- contorno de bloqueios;
- evasão de restrições;
- scraping massivo.

A eventual coleta de odds será fase posterior e preferencialmente sob demanda.

---

## 16. Modelos

Começar simples.

Prioridades:

- médias ajustadas;
- regressão linear/logística;
- Poisson;
- Negative Binomial;
- Elo;
- modelos de hold/return;
- Monte Carlo;
- Markov.

Não iniciar com redes neurais ou modelos excessivamente complexos sem demonstrar ganho real sobre baselines simples.

Todo modelo complexo deve superar claramente um baseline.

---

## 17. Métricas

Para previsões numéricas:

- MAE;
- RMSE.

Para probabilidades:

- Brier Score;
- Log Loss;
- calibration curves.

Também registrar:

- tamanho da amostra;
- erro por superfície;
- erro por jogador;
- erro por ranking;
- erro por temporada;
- erro por torneio quando relevante.

Accuracy isolada não é suficiente.

---

## 18. Mercados

### Aces por jogador

Modelo deve considerar:

Serve Player
×
Return Opponent
×
Surface
×
Expected Service Opportunities.

### Total de aces

Combinar projeções dos dois jogadores e duração esperada.

### Total de games

Modelar:

Serve A × Return B

Serve B × Return A

e gerar distribuição de:

- games;
- sets;
- tie-breaks;
- placares.

### Handicap de games

Derivar da mesma distribuição de placares.

### Double faults

Modelar taxa por oportunidade de saque e contexto.

### Total de sets

Derivar da distribuição probabilística da partida.

---

## 19. Seleção do mercado

Não escolher mercado apenas por maior taxa de acerto.

Comparar:

- previsibilidade;
- MAE;
- RMSE;
- calibração;
- estabilidade temporal;
- estabilidade por superfície;
- quantidade de dados;
- sensibilidade a outliers;
- robustez fora da amostra;
- facilidade de atualização;
- complexidade operacional.

---

## 20. Desenvolvimento

Antes de alterar código:

1. ler CLAUDE.md;
2. consultar documentação relevante em /docs;
3. analisar estrutura existente;
4. fazer a menor alteração necessária;
5. executar testes;
6. registrar resultados.

Evitar:

- overengineering;
- UI antes da hora;
- Supabase antes da necessidade;
- dependências desnecessárias;
- abstrações sem uso;
- arquivos gigantes.

Preferir módulos pequenos e testáveis.

---

## 21. Skills, agentes e MCPs

Skills, subagentes e MCPs podem ser usados quando resolverem um problema real.

Não adicionar ferramenta apenas porque está disponível.

Prioridades possíveis:

GitHub:
- datasets;
- código de referência.

HTTP:
- downloads;
- APIs;
- páginas simples.

Firecrawl:
- fallback para extração de conteúdo.

Playwright:
- apenas quando JavaScript for indispensável.

Subagentes:
- pesquisas independentes;
- comparação de abordagens;
- auditorias.

O agente principal deve consolidar e validar resultados.

---

## 22. Ordem do projeto

### Fase 0
Pesquisa das fontes e disponibilidade dos dados.

### Fase 1
Ingestão e normalização.

### Fase 2
Construção das features Serve × Return.

### Fase 3
Baselines estatísticos.

### Fase 4
Walk-forward backtesting.

### Fase 5
Comparação dos mercados.

### Fase 6
Seleção dos mercados mais previsíveis.

### Fase 7
Previsões de partidas atuais.

### Fase 8
Conversão de probabilidades em odds justas.

### Fase 9
Consulta pontual de odds externas.

### Fase 10
Interface e automações.

Não avançar prematuramente.

---

## 23. Regra de pesquisa

Quando houver dúvida:

não inventar.

Pesquisar, testar e documentar.

Separar claramente:

- fato observado;
- hipótese;
- inferência;
- resultado de teste.

---

## 24. Objetivo atual

O objetivo atual é somente:

Construir uma base histórica confiável e determinar quais mercados de tênis são estatisticamente mais previsíveis utilizando somente informações disponíveis antes de cada partida.

Não desenvolver o produto final antes dessa resposta.
