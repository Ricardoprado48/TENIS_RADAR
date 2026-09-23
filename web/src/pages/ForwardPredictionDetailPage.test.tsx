// Testes do detalhe de previsao do Forward Test (LOTE H, docs/018 secao
// 22): loading, nao encontrada, erro, dados completos, CLV/historico de
// odds ausentes, detalhes tecnicos colapsaveis.

import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ForwardPredictionDetailPage from "./ForwardPredictionDetailPage";
import * as api from "../services/api";
import type { PredictionDetailResponse } from "../types/api";

vi.mock("../services/api");

const mockedApi = vi.mocked(api);

function baseDetail(overrides: Partial<PredictionDetailResponse> = {}): PredictionDetailResponse {
  return {
    prediction_id: "PRED_0000000000000001",
    registered_at: "2026-09-22T14:00:00+00:00",
    tour: "ATP",
    tournament: "Chengdu Open",
    match_id: "FUTURE:ATP:0",
    player: "Sebastian Baez",
    opponent: "Jenson Brooksby",
    surface_ctx: "Hard",
    market: "aces_player",
    side: "over",
    line: 5.5,
    operational_probability: 0.65,
    fair_odds: 1.538,
    minimum_odds: 1.58,
    decimal_odds: 3.95,
    bookmaker: "Betano",
    classification: "CANDIDATO",
    settlement: "WIN",
    settlement_reason: "resultado real = 8, linha = 5.5, lado = over",
    settled_at: "2026-09-23T10:00:00+00:00",
    paper_result_units: 2.95,
    paper_test_label: "PAPER_TEST_ONLY",
    odds_history: {
      n_snapshots: 2, first_observed_odds: 3.8, last_observed_odds: 3.95,
      best_observed_odds: 3.95, closing_odds_observed: 3.9, closing_odds_note: "ultima leitura manual disponivel",
    },
    clv: { clv_pct: 1.28, clv_probability_diff: -0.005 },
    technical: {
      implied_probability: 0.253, model_edge: 0.10, sample_quality: "HIGH", method_selected: "platt",
      restricted: false, restricted_motivo: null, staleness_bucket: "MUITO_DEFASADO", data_staleness_days: 121,
      historical_data_cutoff: "2026-05-25", reasons: ["edge = +10.0 p.p.", "amostra = HIGH"], alerts: [],
    },
    ...overrides,
  };
}

function renderPage(predictionId = "PRED_0000000000000001") {
  return render(
    <MemoryRouter initialEntries={[`/forward/${predictionId}`]}>
      <Routes>
        <Route path="/forward/:predictionId" element={<ForwardPredictionDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("ForwardPredictionDetailPage", () => {
  it("mostra o estado de carregamento", () => {
    mockedApi.getForwardPrediction.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByText("Carregando previsão…")).toBeInTheDocument();
  });

  it("mostra 'nao encontrada' em 404", async () => {
    mockedApi.getForwardPrediction.mockRejectedValue(new Error("Falha ao consultar /api/forward/predictions/x: HTTP 404"));
    renderPage();
    await waitFor(() => expect(screen.getByText("Previsão não encontrada.")).toBeInTheDocument());
  });

  it("mostra erro generico quando a API falha por outro motivo", async () => {
    mockedApi.getForwardPrediction.mockRejectedValue(new Error("network down"));
    renderPage();
    await waitFor(() => expect(screen.getByText("Não foi possível carregar esta previsão.")).toBeInTheDocument());
  });

  it("mostra os dados completos da previsao", async () => {
    mockedApi.getForwardPrediction.mockResolvedValue(baseDetail());
    renderPage();

    await waitFor(() => expect(screen.getByText("Sebastian Baez x Jenson Brooksby")).toBeInTheDocument());
    expect(screen.getByText("Candidato")).toBeInTheDocument();
    expect(screen.getByText("Acerto")).toBeInTheDocument();
    expect(screen.getByText(/Nº de leituras/)).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("mostra CLV e historico de odds ausentes quando nao disponiveis", async () => {
    mockedApi.getForwardPrediction.mockResolvedValue(baseDetail({ clv: null, odds_history: null }));
    renderPage();

    await waitFor(() => expect(screen.getByText("CLV indisponível.")).toBeInTheDocument());
    expect(screen.getByText("Nenhuma leitura de odds registrada ainda.")).toBeInTheDocument();
  });

  it("mostra detalhes tecnicos so ao clicar (colapsavel, fechado por padrao)", async () => {
    mockedApi.getForwardPrediction.mockResolvedValue(baseDetail());
    renderPage();

    await waitFor(() => expect(screen.getByText("Sebastian Baez x Jenson Brooksby")).toBeInTheDocument());
    // <details> nao esconde o conteudo do DOM no jsdom (so via CSS de
    // navegador real) -- a checagem correta de "fechado por padrao" e a
    // propriedade `open`, nao a presenca/ausencia do texto no DOM.
    const details = screen.getByText("Qualidade da amostra").closest("details") as HTMLDetailsElement;
    expect(details.open).toBe(false);

    fireEvent.click(screen.getByText("Detalhes técnicos"));
    expect(details.open).toBe(true);
    expect(screen.getByText("HIGH")).toBeInTheDocument();
  });

  it("mostra previsao pendente sem paper result", async () => {
    mockedApi.getForwardPrediction.mockResolvedValue(baseDetail({
      settlement: "UNRESOLVED", settlement_reason: "resultado da partida ainda nao registrado",
      settled_at: null, paper_result_units: null, clv: null, odds_history: null,
    }));
    renderPage();

    await waitFor(() => expect(screen.getByText("Pendente")).toBeInTheDocument());
    expect(screen.getByText(/sem paper test/)).toBeInTheDocument();
  });
});
