// Rotulos da tela FORWARD TEST (LOTE H, docs/018 secao 22) -- so traduz
// nomes internos (classificacao, settlement, mercado) para texto legivel,
// mesma disciplina de `src/forward/labels.py` (nao recalcula nada, so
// apresenta o que a API ja devolveu). Reaproveita `MARKET_LABEL`/`sideLabel`
// de `lib/radar.ts` -- nunca duplica esse mapeamento.

import type { Market } from "../types/api";
import { MARKET_LABEL, sideLabel } from "./radar";

export const CLASSIFICATION_LABEL: Record<string, string> = {
  DESCARTAR: "Descartado",
  OBSERVAR: "Observar",
  CANDIDATO_FRACO: "Candidato fraco",
  CANDIDATO: "Candidato",
  CANDIDATO_FORTE: "Candidato forte",
};

export const SETTLEMENT_LABEL: Record<string, string> = {
  WIN: "Acerto",
  LOSS: "Erro",
  VOID: "Anulado",
  UNRESOLVED: "Pendente",
  BOOKMAKER_RULE_REQUIRED: "Aguardando regra da casa",
};

export function marketLabel(market: string): string {
  return MARKET_LABEL[market as Market] ?? market;
}

export function forwardSideLabel(side: string): string {
  return sideLabel(side.toLowerCase());
}

export function classificationLabel(classification: string): string {
  return CLASSIFICATION_LABEL[classification] ?? classification;
}

export function settlementLabel(settlement: string): string {
  return SETTLEMENT_LABEL[settlement] ?? settlement;
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return "não disponível";
  return new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
    timeZone: "America/Sao_Paulo",
  }).format(new Date(iso));
}
