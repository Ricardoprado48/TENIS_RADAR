// Testes da tela FORWARD TEST (LOTE H, docs/018 secao 22): loading, erro,
// vazio, resumo, filtros, metricas ausentes/presentes, paginacao.

import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ForwardPage from "./ForwardPage";
import * as api from "../services/api";
import type { ForwardSummaryResponse, PredictionListItem, PredictionListResponse } from "../types/api";

vi.mock("../services/api");

const mockedApi = vi.mocked(api);

function emptySummary(): ForwardSummaryResponse {
  return {
    counts: {
      n_predictions_registered: 0, n_pending_settlement: 0, n_resolved: 0,
      n_candidates: 0, n_observar: 0, n_descartados: 0,
    },
    results: { wins: 0, losses: 0, void: 0, pending: 0 },
    paper_test: { label: "PAPER_TEST_ONLY", n_entries_simulated: 0, n_wins: null, n_losses: null, n_voids: null, n_pending_settlement: null, total_staked_units: null, total_pnl_units: null, roi: null, max_drawdown_units: null, max_consecutive_losses: null, outcome_distribution: null },
    technical: { brier_score_overall: null, log_loss_overall: null, calibration: [], by_market: [] },
  };
}

function summaryWithData(): ForwardSummaryResponse {
  return {
    counts: {
      n_predictions_registered: 3, n_pending_settlement: 1, n_resolved: 2,
      n_candidates: 1, n_observar: 1, n_descartados: 1,
    },
    results: { wins: 1, losses: 1, void: 0, pending: 1 },
    paper_test: {
      label: "PAPER_TEST_ONLY", n_entries_simulated: 2, n_wins: 1, n_losses: 1, n_voids: 0,
      n_pending_settlement: 0, total_staked_units: 2.0, total_pnl_units: 0.5, roi: 0.25,
      max_drawdown_units: 1.0, max_consecutive_losses: 1, outcome_distribution: { WIN: 1, LOSS: 1, VOID: 0, PENDING: 0 },
    },
    technical: {
      brier_score_overall: 0.18, log_loss_overall: 0.52,
      calibration: [{ bucket: "20-30%", n: 2, mean_predicted: 0.245, observed_rate: 0.5 }],
      by_market: [{ market: "aces_player", n: 2, brier_score: 0.18, clv_avg_pct: 1.2, paper_roi: 0.25 }],
    },
  };
}

function predictionItem(overrides: Partial<PredictionListItem> = {}): PredictionListItem {
  return {
    prediction_id: "PRED_0000000000000001",
    registered_at: "2026-09-22T14:00:00+00:00",
    tour: "ATP",
    tournament: "Chengdu Open",
    player: "Sebastian Baez",
    opponent: "Jenson Brooksby",
    market: "aces_player",
    side: "over",
    line: 5.5,
    decimal_odds: 3.95,
    classification: "CANDIDATO",
    settlement: "WIN",
    settlement_reason: "resultado real = 8, linha = 5.5, lado = over",
    ...overrides,
  };
}

function listResponse(items: PredictionListItem[], total = items.length): PredictionListResponse {
  return { items, total, limit: 20, offset: 0 };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/forward"]}>
      <Routes>
        <Route path="/forward" element={<ForwardPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("ForwardPage", () => {
  it("mostra o estado de carregamento", () => {
    mockedApi.getForwardSummary.mockReturnValue(new Promise(() => {}));
    mockedApi.getForwardPredictions.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByText("Carregando resumo…")).toBeInTheDocument();
  });

  it("mostra erro quando o resumo falha", async () => {
    mockedApi.getForwardSummary.mockRejectedValue(new Error("offline"));
    mockedApi.getForwardPredictions.mockResolvedValue(listResponse([]));
    renderPage();
    await waitFor(() => expect(screen.getByText("Não foi possível carregar o resumo do Forward Test.")).toBeInTheDocument());
  });

  it("mostra o estado vazio (nenhuma previsao registrada)", async () => {
    mockedApi.getForwardSummary.mockResolvedValue(emptySummary());
    mockedApi.getForwardPredictions.mockResolvedValue(listResponse([]));
    renderPage();

    await waitFor(() => expect(screen.getByText("Nenhuma previsão registrada com estes filtros.")).toBeInTheDocument());
    expect(screen.getByText("Nenhuma entrada simulada ainda.")).toBeInTheDocument();
  });

  it("mostra as contagens do resumo", async () => {
    mockedApi.getForwardSummary.mockResolvedValue(summaryWithData());
    mockedApi.getForwardPredictions.mockResolvedValue(listResponse([predictionItem()]));
    renderPage();

    await waitFor(() => expect(screen.getByText("Sebastian Baez x Jenson Brooksby")).toBeInTheDocument());
    expect(screen.getAllByText("3")[0]).toBeInTheDocument(); // registradas
    expect(screen.getByText(/Acertos: 1 · Erros: 1 · Anulados: 0 · Pendentes: 1/)).toBeInTheDocument();
  });

  it("mostra metricas ausentes como 'nao disponivel' quando o backend nao calculou nada", async () => {
    mockedApi.getForwardSummary.mockResolvedValue(emptySummary());
    mockedApi.getForwardPredictions.mockResolvedValue(listResponse([]));
    renderPage();

    await waitFor(() => expect(screen.getByText(/Brier Score \(geral\)/)).toBeInTheDocument());
    expect(screen.getByText("Brier Score (geral): não disponível")).toBeInTheDocument();
  });

  it("mostra metricas quando presentes, dentro de Detalhes tecnicos", async () => {
    mockedApi.getForwardSummary.mockResolvedValue(summaryWithData());
    mockedApi.getForwardPredictions.mockResolvedValue(listResponse([predictionItem()]));
    renderPage();

    await waitFor(() => expect(screen.getByText("Brier Score (geral): 0.1800")).toBeInTheDocument());
    expect(screen.getByText(/Por mercado/)).toBeInTheDocument();
  });

  it("filtra por tour e chama a API com o parametro certo", async () => {
    mockedApi.getForwardSummary.mockResolvedValue(summaryWithData());
    mockedApi.getForwardPredictions.mockResolvedValue(listResponse([predictionItem()]));
    renderPage();

    await waitFor(() => expect(screen.getByText("Sebastian Baez x Jenson Brooksby")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "ATP" }));

    await waitFor(() =>
      expect(mockedApi.getForwardPredictions).toHaveBeenLastCalledWith(
        expect.objectContaining({ tour: "ATP", offset: 0 }),
      ),
    );
  });

  it("filtra por classificacao candidato", async () => {
    mockedApi.getForwardSummary.mockResolvedValue(summaryWithData());
    mockedApi.getForwardPredictions.mockResolvedValue(listResponse([predictionItem()]));
    renderPage();

    await waitFor(() => expect(screen.getByText("Sebastian Baez x Jenson Brooksby")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Candidato" }));

    await waitFor(() =>
      expect(mockedApi.getForwardPredictions).toHaveBeenLastCalledWith(
        expect.objectContaining({ classificationGroup: "candidato" }),
      ),
    );
  });

  it("mostra previsao pendente e previsao resolvida com rotulos distintos", async () => {
    mockedApi.getForwardSummary.mockResolvedValue(summaryWithData());
    mockedApi.getForwardPredictions.mockResolvedValue(
      listResponse([
        predictionItem({ prediction_id: "PRED_a", settlement: "WIN" }),
        predictionItem({ prediction_id: "PRED_b", settlement: "UNRESOLVED", player: "Outro Jogador" }),
      ], 2),
    );
    renderPage();

    await waitFor(() => expect(screen.getByText("Acerto")).toBeInTheDocument());
    expect(screen.getByText("Pendente")).toBeInTheDocument();
  });

  it("mostra paginacao e avanca para a proxima pagina", async () => {
    mockedApi.getForwardSummary.mockResolvedValue(summaryWithData());
    mockedApi.getForwardPredictions.mockResolvedValue(listResponse([predictionItem()], 25));
    renderPage();

    await waitFor(() => expect(screen.getByText(/1–20 de 25/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Próxima" }));

    await waitFor(() =>
      expect(mockedApi.getForwardPredictions).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 20 })),
    );
  });
});
