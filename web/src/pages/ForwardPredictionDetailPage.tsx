// Detalhe de uma previsao do Forward Test (LOTE H, docs/018 secao 22) --
// GET /api/forward/predictions/{prediction_id}. So leitura/apresentacao.

import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getForwardPrediction } from "../services/api";
import type { PredictionDetailResponse } from "../types/api";
import { classificationLabel, forwardSideLabel, formatDateTime, marketLabel, settlementLabel } from "../lib/forward";
import { formatOdds, formatProbability } from "../lib/radar";

type LoadState = "loading" | "loaded" | "error" | "not_found";

function fmtSignedPct(value: number | null): string {
  if (value === null) return "não disponível";
  return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(1)}%`;
}

function fmtNumber(value: number | null, decimals = 4): string {
  if (value === null) return "não disponível";
  return value.toFixed(decimals);
}

export default function ForwardPredictionDetailPage() {
  const { predictionId = "" } = useParams<{ predictionId: string }>();
  const [state, setState] = useState<LoadState>("loading");
  const [detail, setDetail] = useState<PredictionDetailResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    setState("loading");
    getForwardPrediction(predictionId)
      .then((data) => {
        if (!cancelled) {
          setDetail(data);
          setState("loaded");
        }
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof Error && err.message.includes("404")) {
          setState("not_found");
        } else {
          setState("error");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [predictionId]);

  return (
    <div>
      <Link to="/forward" className="text-xs uppercase tracking-wide text-court">
        ← Voltar ao Forward Test
      </Link>

      {state === "loading" && <p className="mt-4 text-sm text-mist">Carregando previsão…</p>}
      {state === "not_found" && <p className="mt-4 text-sm text-clay">Previsão não encontrada.</p>}
      {state === "error" && <p className="mt-4 text-sm text-clay">Não foi possível carregar esta previsão.</p>}

      {state === "loaded" && detail && (
        <div className="mt-4">
          <p className="text-xs text-mist">
            {detail.tour} · {detail.tournament ?? "torneio não disponível"} · {formatDateTime(detail.registered_at)}
          </p>
          <p className="mt-2 font-display text-xl text-chalk">
            {detail.player ? detail.player : "Partida"}
            {detail.opponent ? ` x ${detail.opponent}` : ""}
          </p>
          <p className="mt-1 text-sm text-mist">
            {marketLabel(detail.market)} — {forwardSideLabel(detail.side)} {detail.line}
          </p>

          <div className="mt-4 border border-rule p-4">
            <dl className="grid grid-cols-2 gap-2 text-sm text-mist">
              <dt>Probabilidade do modelo</dt>
              <dd className="text-chalk">
                {detail.operational_probability !== null ? formatProbability(detail.operational_probability) : "não disponível"}
              </dd>
              <dt>Odd justa</dt>
              <dd className="text-chalk">{formatOdds(detail.fair_odds)}</dd>
              <dt>Odd mínima</dt>
              <dd className="text-chalk">{formatOdds(detail.minimum_odds)}</dd>
              <dt>Odd observada</dt>
              <dd className="text-chalk">{formatOdds(detail.decimal_odds)} ({detail.bookmaker})</dd>
              <dt>Classificação</dt>
              <dd className="text-chalk">{classificationLabel(detail.classification)}</dd>
              <dt>Resultado</dt>
              <dd className="text-chalk">{settlementLabel(detail.settlement)}</dd>
              <dt>Paper result (unidades)</dt>
              <dd className="text-chalk">
                {detail.paper_result_units !== null ? fmtNumber(detail.paper_result_units, 2) : "sem paper test (mercado descartado ou pendente)"}
              </dd>
            </dl>
            {detail.settlement_reason && <p className="mt-3 text-xs text-mist">{detail.settlement_reason}</p>}
          </div>

          <div className="mt-4 border border-rule p-4">
            <p className="font-display text-sm uppercase tracking-wide text-mist">Histórico de odds</p>
            {detail.odds_history ? (
              <dl className="mt-2 grid grid-cols-2 gap-2 text-sm text-mist">
                <dt>Nº de leituras</dt>
                <dd className="text-chalk">{detail.odds_history.n_snapshots}</dd>
                <dt>Primeira odd</dt>
                <dd className="text-chalk">{formatOdds(detail.odds_history.first_observed_odds)}</dd>
                <dt>Última odd</dt>
                <dd className="text-chalk">{formatOdds(detail.odds_history.last_observed_odds)}</dd>
                <dt>Odd de fechamento</dt>
                <dd className="text-chalk">{formatOdds(detail.odds_history.closing_odds_observed)}</dd>
              </dl>
            ) : (
              <p className="mt-2 text-sm text-mist">Nenhuma leitura de odds registrada ainda.</p>
            )}
            {detail.odds_history?.closing_odds_note && (
              <p className="mt-2 text-xs text-mist">{detail.odds_history.closing_odds_note}</p>
            )}

            <p className="mt-4 text-xs uppercase tracking-wide text-mist">CLV</p>
            {detail.clv ? (
              <p className="mt-1 text-sm text-chalk">
                {fmtSignedPct(detail.clv.clv_pct)} vs. fechamento — nunca interpretado isoladamente como prova de lucratividade.
              </p>
            ) : (
              <p className="mt-1 text-sm text-mist">CLV indisponível.</p>
            )}
          </div>

          <details className="mt-4 border border-rule p-4">
            <summary className="cursor-pointer font-display text-sm uppercase tracking-wide text-mist">
              Detalhes técnicos
            </summary>
            <dl className="mt-3 grid grid-cols-2 gap-2 text-sm text-mist">
              <dt>Prob. implícita</dt>
              <dd>{detail.technical.implied_probability !== null ? formatProbability(detail.technical.implied_probability) : "não disponível"}</dd>
              <dt>Edge do modelo</dt>
              <dd>{detail.technical.model_edge !== null ? formatProbability(detail.technical.model_edge) : "não disponível"}</dd>
              <dt>Qualidade da amostra</dt>
              <dd>{detail.technical.sample_quality ?? "não disponível"}</dd>
              <dt>Restrito</dt>
              <dd>{detail.technical.restricted ? "sim" : "não"}{detail.technical.restricted_motivo ? ` — ${detail.technical.restricted_motivo}` : ""}</dd>
              <dt>Defasagem</dt>
              <dd>{detail.technical.staleness_bucket ?? "não disponível"} ({detail.technical.data_staleness_days ?? "?"} dias)</dd>
              <dt>Base histórica até</dt>
              <dd>{detail.technical.historical_data_cutoff ?? "não disponível"}</dd>
            </dl>
            {detail.technical.reasons.length > 0 && (
              <div className="mt-3">
                <p className="text-xs uppercase tracking-wide text-mist">Motivos</p>
                <ul className="mt-1 flex flex-col gap-1 text-sm text-mist">
                  {detail.technical.reasons.map((r, i) => (
                    <li key={i}>- {r}</li>
                  ))}
                </ul>
              </div>
            )}
            {detail.technical.alerts.length > 0 && (
              <div className="mt-3">
                <p className="text-xs uppercase tracking-wide text-mist">Alertas</p>
                <ul className="mt-1 flex flex-col gap-1 text-sm text-mist">
                  {detail.technical.alerts.map((a, i) => (
                    <li key={i}>- {a}</li>
                  ))}
                </ul>
              </div>
            )}
          </details>
        </div>
      )}
    </div>
  );
}
