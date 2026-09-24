// Testes da tela RADAR DO DIA (LOTE D, docs/018_PWA_ARQUITETURA.md):
// carregamento, erro sem dado inventado, lista vazia, agrupamento em
// CONFERIR ODDS / OBSERVAR / DESCARTADOS, renderização de probabilidade/
// odd justa/odd mínima, aviso de defasagem, e filtro por match_key vindo
// da tela Calendário.

import { beforeEach, describe, expect, it } from "vitest";
import { vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import RadarPage from "./RadarPage";
import * as api from "../services/api";
import type { RadarLine } from "../types/api";

vi.mock("../services/api");

const mockedApi = vi.mocked(api);

function line(overrides: Partial<RadarLine>): RadarLine {
  return {
    match_key: "atp-chengdu-open-r32-sebastian-baez-jenson-brooksby-2026-09-23",
    match_id: "FUTURE:ATP:0",
    tour: "ATP",
    tournament: "Chengdu Open",
    round: "R32",
    surface: "Hard",
    player_a: "Sebastian Baez",
    player_b: "Jenson Brooksby",
    event_datetime_sao_paulo: "2026-09-23T02:00:00-03:00",
    market: "aces_player",
    player: "Sebastian Baez",
    side: "over",
    line: 5.5,
    probability: 0.245,
    fair_odds: 4.09,
    minimum_odds: 4.35,
    odd_minima_por_edge: { "2pct": 4.2, "3pct": 4.35, "5pct": 4.6, "7_5pct": 4.9, "10pct": 5.2 },
    decision_state: "CONFERIR_ODDS",
    candidate_blockers: [],
    sample_bucket_career: "large_50_plus",
    restricted: false,
    restricted_motivo: null,
    extreme_probability: false,
    identity_trusted: true,
    resolution_method_player: "exact",
    resolution_method_opponent: "exact",
    staleness_status: "MUITO_DEFASADO",
    staleness_days: 121,
    historical_data_cutoff: "2026-05-25",
    ...overrides,
  };
}

function renderPage(initialPath = "/radar") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/radar" element={<RadarPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("RadarPage", () => {
  it("mostra estado de carregamento antes da resposta da API", () => {
    mockedApi.getRadarToday.mockImplementation(() => new Promise(() => {}));

    renderPage();

    expect(screen.getByText("Radar do Dia")).toBeInTheDocument();
    expect(screen.getByText("Carregando radar…")).toBeInTheDocument();
  });

  it("mostra erro sem inventar dado quando a API falha", async () => {
    mockedApi.getRadarToday.mockRejectedValue(new Error("network error"));

    renderPage();

    await waitFor(() =>
      expect(
        screen.getByText("Não foi possível carregar o radar. Verifique se a API está em execução."),
      ).toBeInTheDocument(),
    );
  });

  it("mostra estado vazio quando o radar não tem nenhuma linha", async () => {
    mockedApi.getRadarToday.mockResolvedValue([]);

    renderPage();

    await waitFor(() =>
      expect(screen.getByText("Nenhuma análise disponível no radar hoje.")).toBeInTheDocument(),
    );
  });

  it("agrupa as linhas em CONFERIR ODDS / OBSERVAR / DESCARTADOS", async () => {
    mockedApi.getRadarToday.mockResolvedValue([
      line({ decision_state: "CONFERIR_ODDS", player: "Sebastian Baez" }),
      line({ decision_state: "OBSERVAR", player: "Jenson Brooksby", line: 9.5 }),
      line({ decision_state: "DESCARTADO", market: "double_faults_player", player: "Sebastian Baez", line: 0.5 }),
    ]);

    renderPage();

    await waitFor(() => expect(screen.getByText("Conferir odds (1)")).toBeInTheDocument());
    expect(screen.getByText("Observar (1)")).toBeInTheDocument();
    expect(screen.getByText("Descartados (1)")).toBeInTheDocument();

    expect(screen.getByText(/Sebastian Baez — Mais de 5,5 aces/)).toBeInTheDocument();
    expect(screen.getByText(/Jenson Brooksby — Mais de 9,5 aces/)).toBeInTheDocument();
    // DESCARTADOS fica dentro de um <details> fechado por padrao (o
    // conteudo continua no DOM -- so nao aberto).
    const descartadosSummary = screen.getByText("Descartados (1)");
    expect(descartadosSummary.closest("details")).not.toHaveAttribute("open");
  });

  it("renderiza probabilidade, odd justa e odd mínima formatadas", async () => {
    mockedApi.getRadarToday.mockResolvedValue([line({})]);

    renderPage();

    await waitFor(() => expect(screen.getByText(/Sebastian Baez — Mais de 5,5 aces/)).toBeInTheDocument());
    expect(screen.getByText(/Probabilidade: 24,5%/)).toBeInTheDocument();
    expect(screen.getByText(/Odd justa: 4,09/)).toBeInTheDocument();
    expect(screen.getByText(/Odd mínima: 4,35/)).toBeInTheDocument();
  });

  it('mostra "não disponível" para odd justa quando o pipeline não precifica (cold start)', async () => {
    mockedApi.getRadarToday.mockResolvedValue([line({ fair_odds: null, minimum_odds: null })]);

    renderPage();

    await waitFor(() => expect(screen.getByText(/Sebastian Baez — Mais de 5,5 aces/)).toBeInTheDocument());
    expect(screen.getByText(/Odd justa: não disponível/)).toBeInTheDocument();
    expect(screen.getByText(/Odd mínima: não disponível/)).toBeInTheDocument();
  });

  it("mostra o mercado de partida sem nome de jogador (total_aces_match)", async () => {
    mockedApi.getRadarToday.mockResolvedValue([
      line({ market: "total_aces_match", player: null, line: 21.5 }),
    ]);

    renderPage();

    await waitFor(() => expect(screen.getByText(/Total da partida — Mais de 21,5 aces/)).toBeInTheDocument());
  });

  it("mostra o aviso de defasagem da base histórica sem escondê-lo", async () => {
    mockedApi.getRadarToday.mockResolvedValue([line({})]);

    renderPage();

    await waitFor(() =>
      expect(screen.getByText(/Base histórica atualizada até 25\/05\/2026/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/dados históricos muito defasados/)).toBeInTheDocument();
  });

  it("filtra por match_key vindo da query string (clique no calendário)", async () => {
    mockedApi.getRadarToday.mockResolvedValue([
      line({ match_key: "match-a", player_a: "Jogador A1", player_b: "Jogador A2" }),
      line({ match_key: "match-b", player_a: "Jogador B1", player_b: "Jogador B2" }),
    ]);

    renderPage("/radar?match_key=match-a");

    await waitFor(() => expect(screen.getByText("Jogador A1 x Jogador A2")).toBeInTheDocument());
    expect(screen.queryByText("Jogador B1 x Jogador B2")).not.toBeInTheDocument();
    expect(screen.getByText(/Mostrando só esta partida/)).toBeInTheDocument();
  });

  it('mostra "Adicionar print da Betano" para CONFERIR_ODDS/OBSERVAR, mas não para DESCARTADO', async () => {
    mockedApi.getRadarToday.mockResolvedValue([
      line({ decision_state: "CONFERIR_ODDS", match_key: "match-conferir" }),
      line({ decision_state: "OBSERVAR", match_key: "match-observar", line: 9.5 }),
      line({
        decision_state: "DESCARTADO",
        match_key: "match-descartado",
        market: "double_faults_player",
        line: 0.5,
      }),
    ]);

    renderPage();

    await waitFor(() => expect(screen.getAllByText("Adicionar print da Betano")).toHaveLength(2));
    const links = screen.getAllByText("Adicionar print da Betano");
    expect(links[0].closest("a")).toHaveAttribute("href", "/prints/match-conferir");
    expect(links[1].closest("a")).toHaveAttribute("href", "/prints/match-observar");
  });
});
