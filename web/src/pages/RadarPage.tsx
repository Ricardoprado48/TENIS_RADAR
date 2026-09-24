import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { getRadarToday } from "../services/api";
import type { DecisionState, RadarLine } from "../types/api";
import { DECISION_LABEL, MARKET_LABEL, formatLine, formatOdds, formatProbability, sideLabel } from "../lib/radar";

type LoadState = "loading" | "loaded" | "offline";

function formatTime(iso: string | null): string {
  if (!iso) return "horário não disponível";
  return new Intl.DateTimeFormat("pt-BR", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "America/Sao_Paulo",
  }).format(new Date(iso));
}


function lineLabel(line: RadarLine): string {
  const suffix = `${sideLabel(line.side)} ${formatLine(line.line)}`;

  if (line.market === "aces_player" && line.player) {
    return `${line.player} — ${suffix} aces`;
  }

  if (line.market === "total_aces_match") {
    return `Total da partida — ${suffix} aces`;
  }

  if (line.market === "double_faults_player" && line.player) {
    return `${line.player} — ${suffix} duplas faltas`;
  }

  const market = MARKET_LABEL[line.market];

  return line.player
    ? `${line.player} — ${suffix} ${market.toLowerCase()}`
    : `${suffix} ${market.toLowerCase()}`;
}

function RadarCard({ line }: { line: RadarLine }) {
  return (
    <div className="border border-rule p-4">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs text-mist">
          {line.tour} {line.tournament}
        </span>
        <span className="text-xs text-mist">{formatTime(line.event_datetime_sao_paulo)}</span>
      </div>
      <p className="mt-2 font-display text-base text-chalk">
        {line.player_a} x {line.player_b}
      </p>
      <p className="mt-1 text-sm text-chalk">{lineLabel(line)}</p>

      <div className="mt-3 flex flex-col gap-1 text-sm text-mist">
        <span>Probabilidade: {formatProbability(line.probability)}</span>
        <span>Odd justa: {formatOdds(line.fair_odds)}</span>
        <span>Odd mínima: {formatOdds(line.minimum_odds)}</span>
      </div>

      <div className="mt-2 text-xs text-mist">
        {line.effective_data_cutoff && line.effective_data_cutoff > (line.historical_data_cutoff || "2026-05-25") ? (
          <span>Dados do jogador atualizados até: {formatCutoffDate(line.effective_data_cutoff)}</span>
        ) : (
          <span>Dados recentes indisponíveis — Base histórica até 25/05/2026</span>
        )}
      </div>

      <p className="mt-3 text-xs uppercase tracking-wide text-mist">{DECISION_LABEL[line.decision_state]}</p>

      {line.decision_state !== "DESCARTADO" && (
        <Link
          to={`/prints/${encodeURIComponent(line.match_key)}`}
          className="mt-3 inline-block text-xs uppercase tracking-wide text-court"
        >
          Adicionar print da Betano
        </Link>
      )}
    </div>
  );
}

function StalenessBanner({ lines }: { lines: RadarLine[] }) {
  const entries = useMemo(() => {
    const seen = new Map<string, { tour: string; status: string | null; cutoff: string | null }>();
    for (const l of lines) {
      const key = l.tour;
      if (!seen.has(key)) {
        seen.set(key, { tour: l.tour, status: l.staleness_status, cutoff: l.historical_data_cutoff });
      }
    }
    return Array.from(seen.values());
  }, [lines]);

  if (entries.length === 0) return null;

  return (
    <div className="mt-4 flex flex-col gap-1">
      {entries.map((e) => (
        <p key={e.tour} className="text-xs text-mist">
          {e.tour}: {e.cutoff ? `Base histórica atualizada até ${formatCutoffDate(e.cutoff)}` : "Dados históricos defasados"}
          {e.status === "MUITO_DEFASADO" ? " — dados históricos muito defasados" : ""}
        </p>
      ))}
    </div>
  );
}

function formatCutoffDate(iso: string): string {
  const [year, month, day] = iso.split("-");
  return `${day}/${month}/${year}`;
}

const SECTION_ORDER: DecisionState[] = ["CONFERIR_ODDS", "OBSERVAR", "DESCARTADO"];

export default function RadarPage() {
  const [state, setState] = useState<LoadState>("loading");
  const [lines, setLines] = useState<RadarLine[]>([]);
  const [searchParams] = useSearchParams();
  const matchKeyFilter = searchParams.get("match_key");

  useEffect(() => {
    let cancelled = false;

    getRadarToday()
      .then((data) => {
        if (!cancelled) {
          setLines(data);
          setState("loaded");
        }
      })
      .catch(() => {
        if (!cancelled) {
          setState("offline");
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const filtered = useMemo(
    () => (matchKeyFilter ? lines.filter((l) => l.match_key === matchKeyFilter) : lines),
    [lines, matchKeyFilter],
  );

  const groups = useMemo(() => {
    const map: Record<DecisionState, RadarLine[]> = { CONFERIR_ODDS: [], OBSERVAR: [], DESCARTADO: [] };
    for (const line of filtered) {
      map[line.decision_state].push(line);
    }
    return map;
  }, [filtered]);

  return (
    <div>
      <p className="font-display text-2xl font-semibold tracking-tight">Radar do Dia</p>

      {matchKeyFilter && (
        <p className="mt-2 text-xs text-mist">
          Mostrando só esta partida — <Link to="/radar" className="text-court">ver radar completo</Link>
        </p>
      )}

      {state === "loading" && <p className="mt-4 text-sm text-mist">Carregando radar…</p>}

      {state === "offline" && (
        <p className="mt-4 text-sm text-clay">
          Não foi possível carregar o radar. Verifique se a API está em execução.
        </p>
      )}

      {state === "loaded" && (
        <>
          <StalenessBanner lines={filtered} />

          {filtered.length === 0 && (
            <p className="mt-6 text-sm text-mist">Nenhuma análise disponível no radar hoje.</p>
          )}

          {SECTION_ORDER.filter((s) => s !== "DESCARTADO").map((section) =>
            groups[section].length === 0 ? null : (
              <div key={section} className="mt-8">
                <p className="font-display text-sm uppercase tracking-wide text-mist">
                  {DECISION_LABEL[section]} ({groups[section].length})
                </p>
                <div className="mt-3 flex flex-col gap-3">
                  {groups[section].map((line, i) => (
                    <RadarCard key={`${line.match_id}-${line.market}-${line.player ?? "match"}-${line.line}-${line.side}-${i}`} line={line} />
                  ))}
                </div>
              </div>
            ),
          )}

          {groups.DESCARTADO.length > 0 && (
            <details className="mt-8">
              <summary className="cursor-pointer font-display text-sm uppercase tracking-wide text-mist">
                Descartados ({groups.DESCARTADO.length})
              </summary>
              <div className="mt-3 flex flex-col gap-3">
                {groups.DESCARTADO.map((line, i) => (
                  <RadarCard key={`${line.match_id}-${line.market}-${line.player ?? "match"}-${line.line}-${line.side}-${i}`} line={line} />
                ))}
              </div>
            </details>
          )}
        </>
      )}
    </div>
  );
}
