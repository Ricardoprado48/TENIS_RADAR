// Helpers compartilhados entre RadarPage e CalendarPage (LOTE D) -- evita
// duas implementacoes paralelas do mesmo agrupamento/rotulo
// (docs/018_PWA_ARQUITETURA.md, "nao criar nova regra de decisao no
// frontend": isto so agrega/rotula o decision_state que a API ja calculou,
// nunca decide um novo estado a partir de probabilidade/odd).

import type { DecisionState, EvaluationLabel, Market, RadarLine } from "../types/api";

// Quando uma partida tem linhas em mais de um grupo, o badge do calendario
// mostra sempre o grupo mais relevante para abrir a Betano.
const BADGE_PRIORITY: DecisionState[] = ["CONFERIR_ODDS", "OBSERVAR", "DESCARTADO"];

export function radarBadgeByMatchKey(lines: RadarLine[]): Map<string, DecisionState> {
  const badges = new Map<string, DecisionState>();
  for (const line of lines) {
    const current = badges.get(line.match_key);
    if (!current || BADGE_PRIORITY.indexOf(line.decision_state) < BADGE_PRIORITY.indexOf(current)) {
      badges.set(line.match_key, line.decision_state);
    }
  }
  return badges;
}

export const MARKET_LABEL: Record<Market, string> = {
  aces_player: "Aces",
  total_aces_match: "Total de Aces",
  double_faults_player: "Duplas Faltas",
};

export const DECISION_LABEL: Record<DecisionState, string> = {
  CONFERIR_ODDS: "Conferir odds",
  OBSERVAR: "Observar",
  DESCARTADO: "Descartado",
};

export function formatLine(value: number | null | undefined): string {
  if (value === null || value === undefined) return "?";
  return String(value).replace(".", ",");
}

export function sideLabel(side: string): string {
  return side.toLowerCase() === "over" ? "Mais de" : "Menos de";
}

export function formatProbability(value: number): string {
  return value.toLocaleString("pt-BR", { style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

export function formatOdds(value: number | null): string {
  if (value === null) return "não disponível";
  return value.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// Rotulos da tela RESULTADO DA ANALISE (LOTE G, docs/018 secao 6.6) --
// agrupamento visual do `evaluation_label` ja calculado pela API a partir
// do `decision_state` da Fase 10 (nunca uma nova regra de decisao aqui).
// Nenhum destes textos usa termos da lista proibida
// (`src/decision/config.py::FORBIDDEN_TERMS`).
export const EVALUATION_LABEL_TEXT: Record<EvaluationLabel, string> = {
  PASSOU_DO_LIMITE: "PASSOU DO LIMITE",
  OBSERVAR: "OBSERVAR",
  NAO_PASSOU: "NÃO PASSOU DO LIMITE",
  SEM_AVALIACAO_DISPONIVEL: "SEM AVALIAÇÃO DISPONÍVEL",
};
