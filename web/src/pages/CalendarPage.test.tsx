// Testes da tela CALENDÁRIO (LOTE C/D, docs/018_PWA_ARQUITETURA.md secoes
// 6.1 e "CALENDARIO"): carregamento, erro sem dado inventado, exibicao dos
// dois horarios lado a lado (torneio + Sao Paulo), filtro por tour/torneio,
// estado vazio, badge de analise do radar (LOTE D) e filtro "somente
// selecionados pelo radar".

import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import CalendarPage from "./CalendarPage";
import * as api from "../services/api";
import type { MatchSchedule, RadarLine } from "../types/api";

vi.mock("../services/api");

const mockedApi = vi.mocked(api);

const MATCH_SHANGHAI: MatchSchedule = {
  match_key: "atp-shanghai-masters-r32-novak-djokovic-carlos-alcaraz-2026-09-23",
  tour: "ATP",
  tournament: "Shanghai Masters",
  round: "R32",
  surface: "Hard",
  player_a: "Novak Djokovic",
  player_b: "Carlos Alcaraz",
  event_datetime_original: "2026-09-23T14:00:00+08:00",
  event_timezone: "Asia/Shanghai",
  event_datetime_utc: "2026-09-23T06:00:00Z",
  event_datetime_sao_paulo: "2026-09-23T03:00:00-03:00",
  status: "futuro",
  source_url: "https://example.com/shanghai",
  collected_at: "2026-09-22T18:00:00Z",
};

const MATCH_WUHAN: MatchSchedule = {
  match_key: "wta-wuhan-open-qf-iga-swiatek-aryna-sabalenka-2026-09-24",
  tour: "WTA",
  tournament: "Wuhan Open",
  round: "QF",
  surface: "Hard",
  player_a: "Iga Swiatek",
  player_b: "Aryna Sabalenka",
  event_datetime_original: "2026-09-24T10:00:00+08:00",
  event_timezone: "Asia/Shanghai",
  event_datetime_utc: "2026-09-24T02:00:00Z",
  event_datetime_sao_paulo: "2026-09-23T23:00:00-03:00",
  status: "futuro",
  source_url: "https://example.com/wuhan",
  collected_at: "2026-09-22T18:05:00Z",
};

function radarLine(overrides: Partial<RadarLine>): RadarLine {
  return {
    match_key: MATCH_SHANGHAI.match_key,
    match_id: "FUTURE:ATP:0",
    tour: "ATP",
    tournament: "Shanghai Masters",
    round: "R32",
    surface: "Hard",
    player_a: "Novak Djokovic",
    player_b: "Carlos Alcaraz",
    event_datetime_sao_paulo: "2026-09-23T03:00:00-03:00",
    market: "aces_player",
    player: "Novak Djokovic",
    side: "over",
    line: 5.5,
    probability: 0.6,
    fair_odds: 1.67,
    minimum_odds: 1.75,
    odd_minima_por_edge: { "2pct": 1.7, "3pct": 1.75, "5pct": 1.8, "7_5pct": 1.9, "10pct": 2.0 },
    decision_state: "CONFERIR_ODDS",
    candidate_blockers: [],
    sample_bucket_career: "large_50_plus",
    restricted: false,
    restricted_motivo: null,
    extreme_probability: false,
    identity_trusted: true,
    resolution_method_player: "exact",
    resolution_method_opponent: "exact",
    staleness_status: "ATUAL",
    staleness_days: 5,
    historical_data_cutoff: "2026-09-18",
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/calendario"]}>
      <CalendarPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  mockedApi.getRadarToday.mockResolvedValue([]);
});

describe("CalendarPage", () => {
  it("mostra estado de carregamento antes da resposta da API", () => {
    mockedApi.getCalendar.mockImplementation(() => new Promise(() => {}));

    renderPage();

    expect(screen.getByText("Calendário")).toBeInTheDocument();
    expect(screen.getByText("Carregando agenda…")).toBeInTheDocument();
  });

  it("mostra erro sem inventar dado quando a API falha", async () => {
    mockedApi.getCalendar.mockRejectedValue(new Error("network error"));

    renderPage();

    await waitFor(() =>
      expect(
        screen.getByText("Não foi possível carregar a agenda. Verifique se a API está em execução."),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText("Novak Djokovic vs Carlos Alcaraz")).not.toBeInTheDocument();
  });

  it("mostra as partidas com os dois horários (torneio + São Paulo) lado a lado", async () => {
    mockedApi.getCalendar.mockResolvedValue([MATCH_SHANGHAI]);

    renderPage();

    await waitFor(() => expect(screen.getByText("Novak Djokovic vs Carlos Alcaraz")).toBeInTheDocument());
    expect(screen.getByText(/Horário do torneio: 23\/09, 14:00/)).toBeInTheDocument();
    expect(screen.getByText(/São Paulo: 23\/09, 03:00/)).toBeInTheDocument();
  });

  it("mostra estado vazio quando não há partida na janela padrão", async () => {
    mockedApi.getCalendar.mockResolvedValue([]);

    renderPage();

    await waitFor(() =>
      expect(screen.getByText(/Nenhuma partida encontrada/)).toBeInTheDocument(),
    );
  });

  it("filtra por tour", async () => {
    mockedApi.getCalendar.mockResolvedValue([MATCH_SHANGHAI, MATCH_WUHAN]);

    renderPage();

    await waitFor(() => expect(screen.getByText("Novak Djokovic vs Carlos Alcaraz")).toBeInTheDocument());
    expect(screen.getByText("Iga Swiatek vs Aryna Sabalenka")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Filtrar por tour"), { target: { value: "WTA" } });

    expect(screen.queryByText("Novak Djokovic vs Carlos Alcaraz")).not.toBeInTheDocument();
    expect(screen.getByText("Iga Swiatek vs Aryna Sabalenka")).toBeInTheDocument();
  });

  it("filtra por torneio", async () => {
    mockedApi.getCalendar.mockResolvedValue([MATCH_SHANGHAI, MATCH_WUHAN]);

    renderPage();

    await waitFor(() => expect(screen.getByText("Novak Djokovic vs Carlos Alcaraz")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Filtrar por torneio"), {
      target: { value: "Wuhan Open" },
    });

    expect(screen.queryByText("Novak Djokovic vs Carlos Alcaraz")).not.toBeInTheDocument();
    expect(screen.getByText("Iga Swiatek vs Aryna Sabalenka")).toBeInTheDocument();
  });

  it("chama a API com a janela padrão de hoje a +3 dias", async () => {
    mockedApi.getCalendar.mockResolvedValue([]);

    renderPage();

    await waitFor(() => expect(mockedApi.getCalendar).toHaveBeenCalledTimes(1));
    const [from, to] = mockedApi.getCalendar.mock.calls[0];
    const fromDate = new Date(`${from}T00:00:00`);
    const toDate = new Date(`${to}T00:00:00`);
    const diffDays = Math.round((toDate.getTime() - fromDate.getTime()) / 86_400_000);
    expect(diffDays).toBe(3);
  });
});

describe("CalendarPage — integração com o radar (LOTE D)", () => {
  it("mostra um badge com o decision_state quando a partida tem análise no radar", async () => {
    mockedApi.getCalendar.mockResolvedValue([MATCH_SHANGHAI, MATCH_WUHAN]);
    mockedApi.getRadarToday.mockResolvedValue([radarLine({ decision_state: "OBSERVAR" })]);

    renderPage();

    await waitFor(() => expect(screen.getByText("Novak Djokovic vs Carlos Alcaraz")).toBeInTheDocument());
    expect(screen.getByText("Observar")).toBeInTheDocument();
  });

  it("não mostra badge para uma partida sem nenhuma linha no radar", async () => {
    mockedApi.getCalendar.mockResolvedValue([MATCH_SHANGHAI, MATCH_WUHAN]);
    mockedApi.getRadarToday.mockResolvedValue([radarLine({ decision_state: "CONFERIR_ODDS" })]);

    renderPage();

    await waitFor(() => expect(screen.getByText("Iga Swiatek vs Aryna Sabalenka")).toBeInTheDocument());
    // So existe 1 badge (para o jogo de Shanghai), nao para o de Wuhan.
    expect(screen.getAllByText("Conferir odds")).toHaveLength(1);
  });

  it("continua funcionando normalmente quando a busca do radar falha", async () => {
    mockedApi.getCalendar.mockResolvedValue([MATCH_SHANGHAI]);
    mockedApi.getRadarToday.mockRejectedValue(new Error("radar indisponível"));

    renderPage();

    await waitFor(() => expect(screen.getByText("Novak Djokovic vs Carlos Alcaraz")).toBeInTheDocument());
    expect(screen.queryByText("Conferir odds")).not.toBeInTheDocument();
  });

  it('filtro "somente selecionados pelo radar" esconde partidas sem análise', async () => {
    mockedApi.getCalendar.mockResolvedValue([MATCH_SHANGHAI, MATCH_WUHAN]);
    mockedApi.getRadarToday.mockResolvedValue([radarLine({ decision_state: "CONFERIR_ODDS" })]);

    renderPage();

    await waitFor(() => expect(screen.getByText("Iga Swiatek vs Aryna Sabalenka")).toBeInTheDocument());

    fireEvent.click(screen.getByLabelText("Somente selecionados pelo radar"));

    expect(screen.getByText("Novak Djokovic vs Carlos Alcaraz")).toBeInTheDocument();
    expect(screen.queryByText("Iga Swiatek vs Aryna Sabalenka")).not.toBeInTheDocument();
  });

  it("o badge é um link para o radar filtrado por match_key", async () => {
    mockedApi.getCalendar.mockResolvedValue([MATCH_SHANGHAI]);
    mockedApi.getRadarToday.mockResolvedValue([radarLine({ decision_state: "CONFERIR_ODDS" })]);

    renderPage();

    const link = await screen.findByRole("link", { name: "Conferir odds" });
    expect(link).toHaveAttribute("href", `/radar?match_key=${encodeURIComponent(MATCH_SHANGHAI.match_key)}`);
  });
});
