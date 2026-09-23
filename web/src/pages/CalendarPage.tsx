import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { getCalendar, getRadarToday } from "../services/api";
import type { MatchSchedule, RadarLine, Tour } from "../types/api";
import { DECISION_LABEL, radarBadgeByMatchKey } from "../lib/radar";

type LoadState = "loading" | "loaded" | "offline";

// Janela padrao da tela (docs/018_PWA_ARQUITETURA.md secao 3.1: "GET
// /api/calendar?from=hoje&to=+3d") -- hoje ate +3 dias, calculada no
// relogio local do dispositivo (mesma limitacao ja aceita no calculo de
// status do backend, secao 5.4).
const WINDOW_DAYS_AHEAD = 3;

function toISODate(d: Date): string {
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function defaultWindow(): { from: string; to: string } {
  const today = new Date();
  const to = new Date(today);
  to.setDate(to.getDate() + WINDOW_DAYS_AHEAD);
  return { from: toISODate(today), to: toISODate(to) };
}

// O frontend nunca recalcula fuso -- so formata os dois instantes que a
// API ja resolveu (event_datetime_original no fuso do torneio,
// event_datetime_sao_paulo em America/Sao_Paulo), sempre com Intl
// (docs/018 secao 4.2).
function formatInZone(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone,
  }).format(new Date(iso));
}

function formatDayHeading(iso: string): string {
  return new Intl.DateTimeFormat("pt-BR", {
    weekday: "long",
    day: "2-digit",
    month: "2-digit",
    timeZone: "America/Sao_Paulo",
  }).format(new Date(iso));
}

const STATUS_LABEL: Record<MatchSchedule["status"], string> = {
  futuro: "Futuro",
  proximo: "Começando em breve",
  iniciado: "Em andamento",
  encerrado: "Encerrado",
};

function groupByStatus(status: MatchSchedule["status"]): "future" | "past" {
  return status === "encerrado" ? "past" : "future";
}

export default function CalendarPage() {
  const [state, setState] = useState<LoadState>("loading");
  const [matches, setMatches] = useState<MatchSchedule[]>([]);
  const [radarLines, setRadarLines] = useState<RadarLine[]>([]);
  const [tourFilter, setTourFilter] = useState<Tour | "all">("all");
  const [tournamentFilter, setTournamentFilter] = useState<string>("all");
  const [radarOnlyFilter, setRadarOnlyFilter] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const { from, to } = defaultWindow();

    getCalendar(from, to)
      .then((data) => {
        if (!cancelled) {
          setMatches(data);
          setState("loaded");
        }
      })
      .catch(() => {
        // Nunca inventar dados: se a API falhar, so mostramos o estado
        // indisponivel, nunca uma agenda vazia que pareca "sem jogos".
        if (!cancelled) {
          setState("offline");
        }
      });

    // Busca independente: o radar so acrescenta o badge "selecionado pelo
    // radar" (LOTE D) -- se essa chamada falhar, o calendario continua
    // funcionando normalmente, so sem badge nenhum.
    getRadarToday()
      .then((data) => {
        if (!cancelled) setRadarLines(data);
      })
      .catch(() => {
        if (!cancelled) setRadarLines([]);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const radarBadges = useMemo(() => radarBadgeByMatchKey(radarLines), [radarLines]);

  const tournaments = useMemo(
    () => Array.from(new Set(matches.map((m) => m.tournament))).sort(),
    [matches],
  );

  const filtered = useMemo(
    () =>
      matches.filter(
        (m) =>
          (tourFilter === "all" || m.tour === tourFilter) &&
          (tournamentFilter === "all" || m.tournament === tournamentFilter) &&
          (!radarOnlyFilter || radarBadges.has(m.match_key)),
      ),
    [matches, tourFilter, tournamentFilter, radarOnlyFilter, radarBadges],
  );

  const dayGroups = useMemo(() => {
    const groups = new Map<string, MatchSchedule[]>();
    for (const m of filtered) {
      const day = m.event_datetime_sao_paulo.slice(0, 10);
      const list = groups.get(day);
      if (list) {
        list.push(m);
      } else {
        groups.set(day, [m]);
      }
    }
    return Array.from(groups.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [filtered]);

  return (
    <div>
      <p className="font-display text-2xl font-semibold tracking-tight">Calendário</p>

      {state === "loading" && <p className="mt-4 text-sm text-mist">Carregando agenda…</p>}

      {state === "offline" && (
        <p className="mt-4 text-sm text-clay">
          Não foi possível carregar a agenda. Verifique se a API está em execução.
        </p>
      )}

      {state === "loaded" && (
        <>
          <div className="mt-4 flex flex-wrap gap-3">
            <select
              aria-label="Filtrar por tour"
              value={tourFilter}
              onChange={(e) => setTourFilter(e.target.value as Tour | "all")}
              className="border border-rule bg-surface px-3 py-2 text-sm text-chalk"
            >
              <option value="all">ATP e WTA</option>
              <option value="ATP">ATP</option>
              <option value="WTA">WTA</option>
            </select>

            <select
              aria-label="Filtrar por torneio"
              value={tournamentFilter}
              onChange={(e) => setTournamentFilter(e.target.value)}
              className="border border-rule bg-surface px-3 py-2 text-sm text-chalk"
            >
              <option value="all">Todos os torneios</option>
              {tournaments.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>

            <label className="flex items-center gap-2 text-sm text-chalk">
              <input
                type="checkbox"
                checked={radarOnlyFilter}
                onChange={(e) => setRadarOnlyFilter(e.target.checked)}
              />
              Somente selecionados pelo radar
            </label>
          </div>

          {filtered.length === 0 && (
            <p className="mt-6 text-sm text-mist">
              Nenhuma partida encontrada para os próximos {WINDOW_DAYS_AHEAD} dias com os filtros
              atuais.
            </p>
          )}

          {dayGroups.map(([day, dayMatches]) => (
            <div key={day} className="mt-8">
              <p className="font-display text-sm uppercase tracking-wide text-mist">
                {formatDayHeading(dayMatches[0].event_datetime_sao_paulo)}
              </p>
              <div className="mt-3 flex flex-col gap-3">
                {dayMatches.map((m) => {
                  const badge = radarBadges.get(m.match_key);
                  return (
                    <div
                      key={m.match_key}
                      data-status-group={groupByStatus(m.status)}
                      className="border border-rule p-4"
                    >
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="text-xs text-mist">
                          {m.tour} · {m.tournament} · {m.round} · {m.surface}
                        </span>
                        <span className="text-xs text-mist">{STATUS_LABEL[m.status]}</span>
                      </div>
                      <p className="mt-2 font-display text-base text-chalk">
                        {m.player_a} vs {m.player_b}
                      </p>
                      <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-xs text-mist">
                        <span>
                          Horário do torneio: {formatInZone(m.event_datetime_original, m.event_timezone)}
                        </span>
                        <span>
                          São Paulo: {formatInZone(m.event_datetime_sao_paulo, "America/Sao_Paulo")}
                        </span>
                      </div>
                      {badge && (
                        <Link
                          to={`/radar?match_key=${encodeURIComponent(m.match_key)}`}
                          className="mt-3 inline-block text-xs uppercase tracking-wide text-court"
                        >
                          {DECISION_LABEL[badge]}
                        </Link>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
