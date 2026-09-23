// Tela FORWARD TEST (LOTE H, docs/018_PWA_ARQUITETURA.md secao 22) -- so
// LE e apresenta o que a Fase 11 ja calculou via GET /api/forward/summary e
// GET /api/forward/predictions. Nenhum resultado/settlement/paper
// test/CLV/Brier/Log Loss/ROI e recalculado aqui.

import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { getForwardPredictions, getForwardSummary } from "../services/api";
import type {
  ForwardSummaryResponse,
  PredictionListItem,
} from "../types/api";
import { classificationLabel, forwardSideLabel, formatDateTime, marketLabel, settlementLabel } from "../lib/forward";
import { formatOdds, formatProbability } from "../lib/radar";

type LoadState = "loading" | "loaded" | "error";

type TourFilter = "ALL" | "ATP" | "WTA";
type SettlementFilter = "ALL" | "pendentes" | "resolvidas";
type ClassificationFilter = "ALL" | "candidato" | "observar" | "descartado";

const PAGE_SIZE = 20;

function fmtSignedPct(value: number | null): string {
  if (value === null) return "não disponível";
  return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(1)}%`;
}

function fmtNumber(value: number | null, decimals = 4): string {
  if (value === null) return "não disponível";
  return value.toFixed(decimals);
}

function SummaryCounts({ summary }: { summary: ForwardSummaryResponse }) {
  const { counts, results } = summary;
  return (
    <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
      <div className="border border-rule p-3">
        <p className="text-xs uppercase tracking-wide text-mist">Registradas</p>
        <p className="mt-1 font-display text-lg text-chalk">{counts.n_predictions_registered}</p>
      </div>
      <div className="border border-rule p-3">
        <p className="text-xs uppercase tracking-wide text-mist">Pendentes</p>
        <p className="mt-1 font-display text-lg text-chalk">{counts.n_pending_settlement}</p>
      </div>
      <div className="border border-rule p-3">
        <p className="text-xs uppercase tracking-wide text-mist">Resolvidas</p>
        <p className="mt-1 font-display text-lg text-chalk">{counts.n_resolved}</p>
      </div>
      <div className="border border-rule p-3">
        <p className="text-xs uppercase tracking-wide text-mist">Candidatos</p>
        <p className="mt-1 font-display text-lg text-chalk">{counts.n_candidates}</p>
      </div>
      <div className="border border-rule p-3">
        <p className="text-xs uppercase tracking-wide text-mist">Observar</p>
        <p className="mt-1 font-display text-lg text-chalk">{counts.n_observar}</p>
      </div>
      <div className="border border-rule p-3">
        <p className="text-xs uppercase tracking-wide text-mist">Descartados</p>
        <p className="mt-1 font-display text-lg text-chalk">{counts.n_descartados}</p>
      </div>

      <div className="col-span-2 border border-rule p-3 sm:col-span-3">
        <p className="text-xs uppercase tracking-wide text-mist">Resultados</p>
        <p className="mt-1 text-sm text-chalk">
          Acertos: {results.wins} · Erros: {results.losses} · Anulados: {results.void} · Pendentes: {results.pending}
        </p>
      </div>
    </div>
  );
}

function PaperTestSection({ summary }: { summary: ForwardSummaryResponse }) {
  const pt = summary.paper_test;
  return (
    <div className="mt-6 border border-rule p-4">
      <p className="font-display text-sm uppercase tracking-wide text-mist">Paper Test</p>
      <p className="mt-1 text-xs text-mist">
        {pt.label} — nunca dinheiro real, nunca recomendação de valor monetário.
      </p>
      {pt.n_entries_simulated === 0 ? (
        <p className="mt-3 text-sm text-mist">Nenhuma entrada simulada ainda.</p>
      ) : (
        <div className="mt-3 flex flex-col gap-1 text-sm text-chalk">
          <span>Entradas simuladas: {pt.n_entries_simulated}</span>
          <span>
            Acertos: {pt.n_wins ?? 0} · Erros: {pt.n_losses ?? 0} · Anulados: {pt.n_voids ?? 0} · Pendentes: {pt.n_pending_settlement ?? 0}
          </span>
          <span>Unidades apostadas (fictícias): {fmtNumber(pt.total_staked_units, 1)}</span>
          <span>Resultado acumulado (unidades): {fmtNumber(pt.total_pnl_units, 2)}</span>
          <span>ROI paper: {fmtSignedPct(pt.roi)}</span>
        </div>
      )}
    </div>
  );
}

function TechnicalSummarySection({ summary }: { summary: ForwardSummaryResponse }) {
  const tech = summary.technical;
  return (
    <details className="mt-6 border border-rule p-4">
      <summary className="cursor-pointer font-display text-sm uppercase tracking-wide text-mist">
        Detalhes técnicos
      </summary>
      <div className="mt-3 flex flex-col gap-1 text-sm text-mist">
        <span>Brier Score (geral): {fmtNumber(tech.brier_score_overall)}</span>
        <span>Log Loss (geral): {fmtNumber(tech.log_loss_overall)}</span>
      </div>

      {tech.calibration.length > 0 && (
        <div className="mt-3">
          <p className="text-xs uppercase tracking-wide text-mist">Calibração por faixa</p>
          <ul className="mt-1 flex flex-col gap-1 text-sm text-mist">
            {tech.calibration.map((b) => (
              <li key={b.bucket}>
                {b.bucket} (N={b.n}): previsto {b.mean_predicted !== null ? formatProbability(b.mean_predicted) : "N/A"}, observado{" "}
                {b.observed_rate !== null ? formatProbability(b.observed_rate) : "N/A"}
              </li>
            ))}
          </ul>
        </div>
      )}

      {tech.by_market.length > 0 && (
        <div className="mt-3">
          <p className="text-xs uppercase tracking-wide text-mist">Por mercado</p>
          <ul className="mt-1 flex flex-col gap-1 text-sm text-mist">
            {tech.by_market.map((m) => (
              <li key={m.market}>
                {marketLabel(m.market)} (N={m.n}): Brier {fmtNumber(m.brier_score)} · CLV médio {fmtSignedPct(m.clv_avg_pct)} · Paper ROI{" "}
                {fmtSignedPct(m.paper_roi)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </details>
  );
}

function PredictionRow({ item }: { item: PredictionListItem }) {
  return (
    <Link
      to={`/forward/${item.prediction_id}`}
      className="block border border-rule p-3 text-sm transition-colors hover:border-court"
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs text-mist">{formatDateTime(item.registered_at)}</span>
        <span className="text-xs uppercase tracking-wide text-mist">{settlementLabel(item.settlement)}</span>
      </div>
      <p className="mt-1 text-xs text-mist">
        {item.tour} · {item.tournament ?? "torneio não disponível"}
      </p>
      <p className="mt-1 text-chalk">
        {item.player ? `${item.player}` : "Partida"}
        {item.opponent ? ` x ${item.opponent}` : ""}
      </p>
      <p className="mt-1 text-mist">
        {marketLabel(item.market)} — {forwardSideLabel(item.side)} {item.line} · odd {formatOdds(item.decimal_odds)}
      </p>
      <p className="mt-1 text-xs uppercase tracking-wide text-mist">{classificationLabel(item.classification)}</p>
    </Link>
  );
}

export default function ForwardPage() {
  const [summaryState, setSummaryState] = useState<LoadState>("loading");
  const [summary, setSummary] = useState<ForwardSummaryResponse | null>(null);

  const [listState, setListState] = useState<LoadState>("loading");
  const [items, setItems] = useState<PredictionListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);

  const [tourFilter, setTourFilter] = useState<TourFilter>("ALL");
  const [settlementFilter, setSettlementFilter] = useState<SettlementFilter>("ALL");
  const [classificationFilter, setClassificationFilter] = useState<ClassificationFilter>("ALL");

  useEffect(() => {
    let cancelled = false;
    getForwardSummary()
      .then((data) => {
        if (!cancelled) {
          setSummary(data);
          setSummaryState("loaded");
        }
      })
      .catch(() => {
        if (!cancelled) setSummaryState("error");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setListState("loading");
    getForwardPredictions({
      tour: tourFilter === "ALL" ? undefined : tourFilter,
      settlementGroup: settlementFilter === "ALL" ? undefined : settlementFilter,
      classificationGroup: classificationFilter === "ALL" ? undefined : classificationFilter,
      limit: PAGE_SIZE,
      offset,
    })
      .then((data) => {
        if (!cancelled) {
          setItems(data.items);
          setTotal(data.total);
          setListState("loaded");
        }
      })
      .catch(() => {
        if (!cancelled) setListState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [tourFilter, settlementFilter, classificationFilter, offset]);

  function resetPageAnd<T>(setter: (v: T) => void) {
    return (v: T) => {
      setOffset(0);
      setter(v);
    };
  }

  const setTour = useMemo(() => resetPageAnd(setTourFilter), []);
  const setSettlement = useMemo(() => resetPageAnd(setSettlementFilter), []);
  const setClassification = useMemo(() => resetPageAnd(setClassificationFilter), []);

  const hasPrev = offset > 0;
  const hasNext = offset + PAGE_SIZE < total;

  return (
    <div>
      <p className="font-display text-2xl font-semibold tracking-tight">Forward Test</p>

      {summaryState === "loading" && <p className="mt-4 text-sm text-mist">Carregando resumo…</p>}
      {summaryState === "error" && (
        <p className="mt-4 text-sm text-clay">Não foi possível carregar o resumo do Forward Test.</p>
      )}
      {summaryState === "loaded" && summary && (
        <>
          <SummaryCounts summary={summary} />
          <PaperTestSection summary={summary} />
          <TechnicalSummarySection summary={summary} />
        </>
      )}

      <div className="mt-8">
        <p className="font-display text-sm uppercase tracking-wide text-mist">Previsões</p>

        <div className="mt-3 flex flex-wrap gap-2">
          {(["ALL", "ATP", "WTA"] as TourFilter[]).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTour(t)}
              aria-pressed={tourFilter === t}
              className={`border px-3 py-1 text-xs ${tourFilter === t ? "border-court text-court" : "border-rule text-mist"}`}
            >
              {t === "ALL" ? "Todos os tours" : t}
            </button>
          ))}
          {([
            ["ALL", "Todos"],
            ["pendentes", "Pendentes"],
            ["resolvidas", "Resolvidas"],
          ] as [SettlementFilter, string][]).map(([v, label]) => (
            <button
              key={v}
              type="button"
              onClick={() => setSettlement(v)}
              aria-pressed={settlementFilter === v}
              className={`border px-3 py-1 text-xs ${settlementFilter === v ? "border-court text-court" : "border-rule text-mist"}`}
            >
              {label}
            </button>
          ))}
          {([
            ["ALL", "Toda classificação"],
            ["candidato", "Candidato"],
            ["observar", "Observar"],
            ["descartado", "Descartado"],
          ] as [ClassificationFilter, string][]).map(([v, label]) => (
            <button
              key={v}
              type="button"
              onClick={() => setClassification(v)}
              aria-pressed={classificationFilter === v}
              className={`border px-3 py-1 text-xs ${classificationFilter === v ? "border-court text-court" : "border-rule text-mist"}`}
            >
              {label}
            </button>
          ))}
        </div>

        {listState === "loading" && <p className="mt-4 text-sm text-mist">Carregando previsões…</p>}
        {listState === "error" && <p className="mt-4 text-sm text-clay">Não foi possível carregar as previsões.</p>}
        {listState === "loaded" && items.length === 0 && (
          <p className="mt-4 text-sm text-mist">Nenhuma previsão registrada com estes filtros.</p>
        )}
        {listState === "loaded" && items.length > 0 && (
          <>
            <div className="mt-4 flex flex-col gap-3">
              {items.map((item) => (
                <PredictionRow key={item.prediction_id} item={item} />
              ))}
            </div>
            <div className="mt-4 flex items-center justify-between text-xs text-mist">
              <button
                type="button"
                disabled={!hasPrev}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                className="border border-rule px-3 py-1 disabled:opacity-30"
              >
                Anterior
              </button>
              <span>
                {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} de {total}
              </span>
              <button
                type="button"
                disabled={!hasNext}
                onClick={() => setOffset(offset + PAGE_SIZE)}
                className="border border-rule px-3 py-1 disabled:opacity-30"
              >
                Próxima
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
