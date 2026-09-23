// Testes da tela ENVIAR PRINT (LOTE E, docs/018_PWA_ARQUITETURA.md secao
// 6.4/6.5): selecao de arquivo/colar/arrastar, preview, remover, escolha
// de aba (Aces/Games Mais-Menos), envio (sucesso/erro), e preservacao do
// match_key vindo da rota. jsdom nao implementa URL.createObjectURL -- e
// stubado aqui (API padrao do navegador, so ausente no ambiente de teste).

import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ScreenshotUploadPage from "./ScreenshotUploadPage";
import * as api from "../services/api";
import type { EvaluatedMarketResult, EvaluateResponse, ExtractionResponse, RadarLine } from "../types/api";

vi.mock("../services/api");

const mockedApi = vi.mocked(api);

const MATCH_KEY = "atp-chengdu-open-r32-sebastian-baez-jenson-brooksby-2026-09-23";

function line(overrides: Partial<RadarLine>): RadarLine {
  return {
    match_key: MATCH_KEY,
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

function renderPage() {
  return render(
    <MemoryRouter initialEntries={[`/prints/${MATCH_KEY}`]}>
      <Routes>
        <Route path="/prints/:matchKey" element={<ScreenshotUploadPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function pngFile(name = "print.png"): File {
  return new File(["conteudo-de-teste"], name, { type: "image/png" });
}

async function waitForHeader() {
  await waitFor(() => expect(screen.getByText("Sebastian Baez x Jenson Brooksby")).toBeInTheDocument());
}

beforeEach(() => {
  vi.resetAllMocks();
  mockedApi.getRadarToday.mockResolvedValue([line({})]);
  // jsdom nao implementa createObjectURL/revokeObjectURL.
  URL.createObjectURL = vi.fn(() => "blob:mock-preview");
  URL.revokeObjectURL = vi.fn();
});

describe("ScreenshotUploadPage", () => {
  it("mostra o contexto da partida e os mercados indicados pelo radar", async () => {
    renderPage();

    await waitForHeader();
    expect(screen.getByText(/Sebastian Baez — Aces Over 5.5/)).toBeInTheDocument();
  });

  it("comeca sem imagem selecionada e com o envio desabilitado", async () => {
    renderPage();

    await waitForHeader();
    expect(screen.getByText(/Arraste um print aqui/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enviar print" })).toBeDisabled();
  });

  it("permite selecionar um arquivo via input e mostra o preview", async () => {
    renderPage();
    await waitForHeader();

    const input = screen.getByLabelText("Selecionar arquivo de print");
    fireEvent.change(input, { target: { files: [pngFile()] } });

    expect(screen.getByAltText("Pré-visualização do print")).toBeInTheDocument();
    expect(screen.getByText("print.png")).toBeInTheDocument();
  });

  it("permite remover a imagem selecionada e voltar ao estado inicial", async () => {
    renderPage();
    await waitForHeader();

    fireEvent.change(screen.getByLabelText("Selecionar arquivo de print"), { target: { files: [pngFile()] } });
    expect(screen.getByText("print.png")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Remover" }));

    expect(screen.queryByText("print.png")).not.toBeInTheDocument();
    expect(screen.getByText(/Arraste um print aqui/)).toBeInTheDocument();
  });

  it("aceita colar uma imagem da area de transferencia (Ctrl+V)", async () => {
    renderPage();
    await waitForHeader();

    const file = pngFile("colado.png");
    const container = screen.getByText(/Arraste um print aqui/).closest("div")!.parentElement!;

    fireEvent.paste(container, {
      clipboardData: {
        items: [{ kind: "file", type: "image/png", getAsFile: () => file }],
      },
    });

    expect(screen.getByText("colado.png")).toBeInTheDocument();
  });

  it("aceita arrastar e soltar uma imagem", async () => {
    renderPage();
    await waitForHeader();

    const file = pngFile("arrastado.png");
    const dropzone = screen.getByTestId("dropzone");

    fireEvent.drop(dropzone, { dataTransfer: { files: [file] } });

    expect(screen.getByText("arrastado.png")).toBeInTheDocument();
  });

  it("permite escolher Aces como tipo de aba", async () => {
    renderPage();
    await waitForHeader();

    const acesButton = screen.getByRole("button", { name: "Aces" });
    fireEvent.click(acesButton);

    expect(acesButton).toHaveAttribute("aria-pressed", "true");
  });

  it("permite escolher Games Mais/Menos como tipo de aba", async () => {
    renderPage();
    await waitForHeader();

    const gamesButton = screen.getByRole("button", { name: "Games Mais/Menos" });
    fireEvent.click(gamesButton);

    expect(gamesButton).toHaveAttribute("aria-pressed", "true");
  });

  it("envia o print com sucesso e mostra o upload_id, preservando o match_key da rota", async () => {
    mockedApi.uploadScreenshot.mockResolvedValue({
      upload_id: "abc-123",
      match_key: MATCH_KEY,
      tab_type: "ACES",
      bookmaker: "Betano",
      created_at: "2026-09-23T12:00:00Z",
      mime_type: "image/png",
      file_size: 1234,
    });

    renderPage();
    await waitForHeader();

    fireEvent.change(screen.getByLabelText("Selecionar arquivo de print"), { target: { files: [pngFile()] } });
    fireEvent.click(screen.getByRole("button", { name: "Aces" }));
    fireEvent.click(screen.getByRole("button", { name: "Enviar print" }));

    await waitFor(() => expect(screen.getByText("Print salvo com sucesso")).toBeInTheDocument());
    expect(screen.getByText(/ID do envio: abc-123/)).toBeInTheDocument();

    expect(mockedApi.uploadScreenshot).toHaveBeenCalledWith(
      expect.objectContaining({ matchKey: MATCH_KEY, tabType: "ACES" }),
    );
  });

  it("mostra o erro do backend sem apagar a selecao do usuario", async () => {
    mockedApi.uploadScreenshot.mockRejectedValue(new Error("Arquivo excede o tamanho maximo de 10 MB."));

    renderPage();
    await waitForHeader();

    fireEvent.change(screen.getByLabelText("Selecionar arquivo de print"), { target: { files: [pngFile()] } });
    fireEvent.click(screen.getByRole("button", { name: "Games Mais/Menos" }));
    fireEvent.click(screen.getByRole("button", { name: "Enviar print" }));

    await waitFor(() =>
      expect(screen.getByText("Arquivo excede o tamanho maximo de 10 MB.")).toBeInTheDocument(),
    );
    expect(screen.queryByText("Print salvo com sucesso")).not.toBeInTheDocument();
    expect(screen.getByText("print.png")).toBeInTheDocument();
  });
});

// LEITURA DO PRINT (LOTE F): "Ler print" -> "Analisando imagem..." ->
// revisao editavel -> "Confirmar leitura" -> "Leitura confirmada".
describe("ScreenshotUploadPage - leitura do print (LOTE F)", () => {
  async function uploadSuccessfully(tabButtonName = "Aces") {
    mockedApi.uploadScreenshot.mockResolvedValue({
      upload_id: "upload-1",
      match_key: MATCH_KEY,
      tab_type: tabButtonName === "Aces" ? "ACES" : "GAMES_TOTALS",
      bookmaker: "Betano",
      created_at: "2026-09-23T12:00:00Z",
      mime_type: "image/png",
      file_size: 1234,
    });

    renderPage();
    await waitForHeader();

    fireEvent.change(screen.getByLabelText("Selecionar arquivo de print"), { target: { files: [pngFile()] } });
    fireEvent.click(screen.getByRole("button", { name: tabButtonName }));
    fireEvent.click(screen.getByRole("button", { name: "Enviar print" }));

    await waitFor(() => expect(screen.getByText("Print salvo com sucesso")).toBeInTheDocument());
  }

  it("mostra o botao 'Ler print' apos o envio", async () => {
    await uploadSuccessfully();
    expect(screen.getByRole("button", { name: "Ler print" })).toBeInTheDocument();
  });

  it("mostra 'Analisando imagem...' enquanto a extracao esta em andamento", async () => {
    await uploadSuccessfully();
    let resolveExtract: (value: ExtractionResponse) => void = () => {};
    mockedApi.extractScreenshot.mockReturnValue(new Promise<ExtractionResponse>((resolve) => (resolveExtract = resolve)));

    fireEvent.click(screen.getByRole("button", { name: "Ler print" }));
    expect(screen.getByText("Analisando imagem…")).toBeInTheDocument();

    resolveExtract({
      extraction_id: "ex-1",
      upload_id: "upload-1",
      match_key: MATCH_KEY,
      tab_type: "ACES",
      status: "AUTO_VALIDATED",
      provider: "fake",
      provider_model: null,
      created_at: "2026-09-23T12:00:01Z",
      markets: [],
      extraction_warnings: [],
    });
    await waitFor(() => expect(screen.queryByText("Analisando imagem…")).not.toBeInTheDocument());
  });

  it("mostra os mercados extraidos, editaveis, lado a lado com o print original", async () => {
    await uploadSuccessfully("Aces");
    mockedApi.extractScreenshot.mockResolvedValue({
      extraction_id: "ex-1",
      upload_id: "upload-1",
      match_key: MATCH_KEY,
      tab_type: "ACES",
      status: "AUTO_VALIDATED",
      provider: "fake",
      provider_model: null,
      created_at: "2026-09-23T12:00:01Z",
      markets: [
        {
          market: "aces_player",
          player: "Sebastian Baez",
          bookmaker_display: "6+",
          side: "Over",
          model_line: 5.5,
          decimal_odds: 2.92,
          confidence: 0.9,
          warnings: [],
          needs_confirmation: false,
        },
      ],
      extraction_warnings: [],
    });

    fireEvent.click(screen.getByRole("button", { name: "Ler print" }));

    await waitFor(() => expect(screen.getByDisplayValue("Sebastian Baez")).toBeInTheDocument());
    expect(screen.getByDisplayValue("6+")).toBeInTheDocument();
    expect(screen.getByDisplayValue("2.92")).toBeInTheDocument();
    expect(screen.getByAltText("Print original")).toBeInTheDocument();
    expect(screen.queryByText("Confirme esta leitura")).not.toBeInTheDocument();
  });

  it("mostra 'Confirme esta leitura' e os warnings quando a extracao precisa de revisao", async () => {
    await uploadSuccessfully("Aces");
    mockedApi.extractScreenshot.mockResolvedValue({
      extraction_id: "ex-1",
      upload_id: "upload-1",
      match_key: MATCH_KEY,
      tab_type: "ACES",
      status: "NEEDS_CONFIRMATION",
      provider: "fake",
      provider_model: null,
      created_at: "2026-09-23T12:00:01Z",
      markets: [
        {
          market: "aces_player",
          player: "Novak Djokovic",
          bookmaker_display: "6+",
          side: "Over",
          model_line: 5.5,
          decimal_odds: 2.0,
          confidence: null,
          warnings: ["JOGADOR_NAO_RECONHECIDO"],
          needs_confirmation: true,
        },
      ],
      extraction_warnings: [],
    });

    fireEvent.click(screen.getByRole("button", { name: "Ler print" }));

    await waitFor(() => expect(screen.getByText("Confirme esta leitura")).toBeInTheDocument());
    expect(screen.getByText("JOGADOR_NAO_RECONHECIDO")).toBeInTheDocument();
  });

  it("permite editar jogador/linha/odd e confirma a leitura com os valores editados", async () => {
    await uploadSuccessfully("Aces");
    mockedApi.extractScreenshot.mockResolvedValue({
      extraction_id: "ex-1",
      upload_id: "upload-1",
      match_key: MATCH_KEY,
      tab_type: "ACES",
      status: "AUTO_VALIDATED",
      provider: "fake",
      provider_model: null,
      created_at: "2026-09-23T12:00:01Z",
      markets: [
        {
          market: "aces_player",
          player: "Sebastian Baez",
          bookmaker_display: "6+",
          side: "Over",
          model_line: 5.5,
          decimal_odds: 2.92,
          confidence: null,
          warnings: [],
          needs_confirmation: false,
        },
      ],
      extraction_warnings: [],
    });
    mockedApi.confirmScreenshot.mockResolvedValue({
      extraction_id: "ex-2",
      upload_id: "upload-1",
      match_key: MATCH_KEY,
      tab_type: "ACES",
      confirmed_at: "2026-09-23T12:00:02Z",
      confirmed_by: "local_user",
      corrected: true,
      markets: [
        {
          market: "aces_player",
          player: "Sebastian Baez",
          bookmaker_display: "7+",
          side: "Over",
          model_line: 6.5,
          decimal_odds: 3.1,
          confidence: null,
          warnings: [],
          needs_confirmation: false,
        },
      ],
    });

    fireEvent.click(screen.getByRole("button", { name: "Ler print" }));
    await waitFor(() => expect(screen.getByDisplayValue("6+")).toBeInTheDocument());

    fireEvent.change(screen.getByDisplayValue("6+"), { target: { value: "7+" } });
    fireEvent.change(screen.getByDisplayValue("2.92"), { target: { value: "3.10" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar leitura" }));

    await waitFor(() => expect(screen.getByText("Leitura confirmada")).toBeInTheDocument());
    expect(mockedApi.confirmScreenshot).toHaveBeenCalledWith("upload-1", [
      { market: "aces_player", player: "Sebastian Baez", bookmaker_display: "7+", decimal_odds: 3.1 },
    ]);
    expect(screen.getByText("7+ · odd 3.1")).toBeInTheDocument();
  });

  it("mostra o erro de extracao e permite tentar novamente", async () => {
    await uploadSuccessfully("Games Mais/Menos");
    mockedApi.extractScreenshot.mockRejectedValueOnce(new Error("Provedor de visao indisponivel."));

    fireEvent.click(screen.getByRole("button", { name: "Ler print" }));
    await waitFor(() => expect(screen.getByText("Provedor de visao indisponivel.")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Tentar novamente" })).toBeInTheDocument();
  });

  it("le a aba Games Mais/Menos e mostra os mercados de total de games", async () => {
    await uploadSuccessfully("Games Mais/Menos");
    mockedApi.extractScreenshot.mockResolvedValue({
      extraction_id: "ex-1",
      upload_id: "upload-1",
      match_key: MATCH_KEY,
      tab_type: "GAMES_TOTALS",
      status: "AUTO_VALIDATED",
      provider: "fake",
      provider_model: null,
      created_at: "2026-09-23T12:00:01Z",
      markets: [
        {
          market: "total_games",
          player: null,
          bookmaker_display: "Mais de 22.5",
          side: "Over",
          model_line: 22.5,
          decimal_odds: 1.85,
          confidence: null,
          warnings: [],
          needs_confirmation: false,
        },
      ],
      extraction_warnings: [],
    });

    fireEvent.click(screen.getByRole("button", { name: "Ler print" }));

    await waitFor(() => expect(screen.getByDisplayValue("Mais de 22.5")).toBeInTheDocument());
    expect(screen.getByText(/Total de Games/)).toBeInTheDocument();
    // Mercado de partida (sem jogador) nao mostra o campo "Jogador".
    expect(screen.queryByText("Jogador")).not.toBeInTheDocument();
  });
});

// RESULTADO DA ANALISE (LOTE G): "Avaliar no Radar" -> "Comparando com o
// modelo..." -> cards PASSOU/OBSERVAR/NAO_PASSOU/SEM_MODELO, com detalhes
// tecnicos colapsaveis e o aviso de defasagem preservado.
describe("ScreenshotUploadPage - avaliacao no radar (LOTE G)", () => {
  async function reachConfirmedState() {
    mockedApi.uploadScreenshot.mockResolvedValue({
      upload_id: "upload-1",
      match_key: MATCH_KEY,
      tab_type: "ACES",
      bookmaker: "Betano",
      created_at: "2026-09-23T12:00:00Z",
      mime_type: "image/png",
      file_size: 1234,
    });
    mockedApi.extractScreenshot.mockResolvedValue({
      extraction_id: "ex-1",
      upload_id: "upload-1",
      match_key: MATCH_KEY,
      tab_type: "ACES",
      status: "AUTO_VALIDATED",
      provider: "fake",
      provider_model: null,
      created_at: "2026-09-23T12:00:01Z",
      markets: [
        {
          market: "aces_player",
          player: "Sebastian Baez",
          bookmaker_display: "6+",
          side: "Over",
          model_line: 5.5,
          decimal_odds: 2.92,
          confidence: null,
          warnings: [],
          needs_confirmation: false,
        },
      ],
      extraction_warnings: [],
    });
    mockedApi.confirmScreenshot.mockResolvedValue({
      extraction_id: "ex-1",
      upload_id: "upload-1",
      match_key: MATCH_KEY,
      tab_type: "ACES",
      confirmed_at: "2026-09-23T12:00:02Z",
      confirmed_by: "local_user",
      corrected: false,
      markets: [
        {
          market: "aces_player",
          player: "Sebastian Baez",
          bookmaker_display: "6+",
          side: "Over",
          model_line: 5.5,
          decimal_odds: 2.92,
          confidence: null,
          warnings: [],
          needs_confirmation: false,
        },
      ],
    });

    renderPage();
    await waitForHeader();

    fireEvent.change(screen.getByLabelText("Selecionar arquivo de print"), { target: { files: [pngFile()] } });
    fireEvent.click(screen.getByRole("button", { name: "Aces" }));
    fireEvent.click(screen.getByRole("button", { name: "Enviar print" }));
    await waitFor(() => expect(screen.getByText("Print salvo com sucesso")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Ler print" }));
    await waitFor(() => expect(screen.getByDisplayValue("Sebastian Baez")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Confirmar leitura" }));
    await waitFor(() => expect(screen.getByText("Leitura confirmada")).toBeInTheDocument());
  }

  function evaluatedResult(overrides: Partial<EvaluatedMarketResult> = {}): EvaluatedMarketResult {
    return {
      market: "aces_player" as const,
      player: "Sebastian Baez",
      bookmaker_display: "6+",
      model_line: 5.5,
      side: "Over" as const,
      bookmaker_odds: 2.92,
      model_probability: 0.245,
      fair_odds: 4.09,
      minimum_odds: 4.35,
      decision_state: "DESCARTAR",
      evaluation_label: "NAO_PASSOU" as const,
      evaluation_message: "DESCARTAR\n\nMotivos:\n- edge = -9.8 p.p.",
      staleness_status: "MUITO_DEFASADO",
      restricted: false,
      technical: {
        implied_probability: 0.342,
        model_edge: -0.098,
        sample_quality: "HIGH",
        matched: true,
        match_reason: null,
        data_staleness_days: 121,
        restricted_motivo: null,
      },
      forward_key: {
        bookmaker: "Betano", tour: "ATP", match_id: "FUTURE:ATP:0", market: "aces_player",
        player: "Sebastian Baez", side: "over", line: 5.5, decimal_odds: 2.92,
        collected_at: "2026-09-23T12:00:02+00:00",
      },
      prediction_id: "PRED_test0000000000",
      already_registered_forward_test: false,
      error: null,
      ...overrides,
    };
  }

  it("mostra o botao 'Avaliar no Radar' apos a confirmacao", async () => {
    await reachConfirmedState();
    expect(screen.getByRole("button", { name: "Avaliar no Radar" })).toBeInTheDocument();
  });

  it("mostra 'Comparando com o modelo...' enquanto a avaliacao esta em andamento", async () => {
    await reachConfirmedState();
    let resolveEvaluate: (value: EvaluateResponse) => void = () => {};
    mockedApi.evaluateScreenshot.mockReturnValue(new Promise<EvaluateResponse>((resolve) => (resolveEvaluate = resolve)));

    fireEvent.click(screen.getByRole("button", { name: "Avaliar no Radar" }));
    expect(screen.getByText("Comparando com o modelo…")).toBeInTheDocument();

    resolveEvaluate({
      upload_id: "upload-1",
      extraction_id: "ex-1",
      match_key: MATCH_KEY,
      confirmed_at: "2026-09-23T12:00:02Z",
      historical_data_cutoff: "2026-05-25",
      data_staleness_days: 121,
      staleness_warning: "Base historica atualizada ate 2026-05-25 -- defasagem de 121 dias.",
      results: [evaluatedResult()],
    });
    await waitFor(() => expect(screen.queryByText("Comparando com o modelo…")).not.toBeInTheDocument());
  });

  it("mostra PASSOU DO LIMITE para um candidato aprovado pela Fase 10", async () => {
    await reachConfirmedState();
    mockedApi.evaluateScreenshot.mockResolvedValue({
      upload_id: "upload-1",
      extraction_id: "ex-1",
      match_key: MATCH_KEY,
      confirmed_at: "2026-09-23T12:00:02Z",
      historical_data_cutoff: "2026-05-25",
      data_staleness_days: 121,
      staleness_warning: "Base historica atualizada ate 2026-05-25 -- defasagem de 121 dias.",
      results: [evaluatedResult({ decision_state: "CANDIDATO", evaluation_label: "PASSOU_DO_LIMITE" })],
    });

    fireEvent.click(screen.getByRole("button", { name: "Avaliar no Radar" }));

    await waitFor(() => expect(screen.getByText("PASSOU DO LIMITE")).toBeInTheDocument());
    expect(screen.getByText("24,5%")).toBeInTheDocument();
    expect(screen.getByText("Base historica atualizada ate 2026-05-25 -- defasagem de 121 dias.")).toBeInTheDocument();
  });

  it("mostra OBSERVAR quando a Fase 10 classifica como observacao", async () => {
    await reachConfirmedState();
    mockedApi.evaluateScreenshot.mockResolvedValue({
      upload_id: "upload-1",
      extraction_id: "ex-1",
      match_key: MATCH_KEY,
      confirmed_at: "2026-09-23T12:00:02Z",
      historical_data_cutoff: "2026-05-25",
      data_staleness_days: 121,
      staleness_warning: "Base historica atualizada ate 2026-05-25.",
      results: [evaluatedResult({ decision_state: "OBSERVAR", evaluation_label: "OBSERVAR" })],
    });

    fireEvent.click(screen.getByRole("button", { name: "Avaliar no Radar" }));
    await waitFor(() => expect(screen.getByText("OBSERVAR")).toBeInTheDocument());
  });

  it("mostra NAO PASSOU DO LIMITE quando a Fase 10 descarta a oportunidade", async () => {
    await reachConfirmedState();
    mockedApi.evaluateScreenshot.mockResolvedValue({
      upload_id: "upload-1",
      extraction_id: "ex-1",
      match_key: MATCH_KEY,
      confirmed_at: "2026-09-23T12:00:02Z",
      historical_data_cutoff: "2026-05-25",
      data_staleness_days: 121,
      staleness_warning: "Base historica atualizada ate 2026-05-25.",
      results: [evaluatedResult()],
    });

    fireEvent.click(screen.getByRole("button", { name: "Avaliar no Radar" }));
    await waitFor(() => expect(screen.getByText("NÃO PASSOU DO LIMITE")).toBeInTheDocument());
  });

  it("mostra 'Mercado ainda nao disponivel' quando a Fase 6/7/9/10 nao suporta o mercado", async () => {
    await reachConfirmedState();
    mockedApi.evaluateScreenshot.mockResolvedValue({
      upload_id: "upload-1",
      extraction_id: "ex-1",
      match_key: MATCH_KEY,
      confirmed_at: "2026-09-23T12:00:02Z",
      historical_data_cutoff: "2026-05-25",
      data_staleness_days: 121,
      staleness_warning: "Base historica atualizada ate 2026-05-25.",
      results: [
        evaluatedResult({
          market: "total_games",
          decision_state: null,
          evaluation_label: "SEM_AVALIACAO_DISPONIVEL",
          evaluation_message: "Mercado ainda nao disponivel para avaliacao pelo modelo.",
          model_probability: null,
          fair_odds: null,
          minimum_odds: null,
          staleness_status: null,
          restricted: null,
          technical: null,
          forward_key: null,
          prediction_id: null,
        }),
      ],
    });

    fireEvent.click(screen.getByRole("button", { name: "Avaliar no Radar" }));
    await waitFor(() =>
      expect(screen.getByText("Mercado ainda nao disponivel para avaliacao pelo modelo.")).toBeInTheDocument(),
    );
  });

  it("mostra o erro e permite tentar novamente quando a avaliacao falha", async () => {
    await reachConfirmedState();
    mockedApi.evaluateScreenshot.mockRejectedValueOnce(new Error("Nenhuma leitura confirmada para este upload."));

    fireEvent.click(screen.getByRole("button", { name: "Avaliar no Radar" }));
    await waitFor(() =>
      expect(screen.getByText("Nenhuma leitura confirmada para este upload.")).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Tentar novamente" })).toBeInTheDocument();
  });

  it("mostra os detalhes tecnicos so ao clicar (colapsavel)", async () => {
    await reachConfirmedState();
    mockedApi.evaluateScreenshot.mockResolvedValue({
      upload_id: "upload-1",
      extraction_id: "ex-1",
      match_key: MATCH_KEY,
      confirmed_at: "2026-09-23T12:00:02Z",
      historical_data_cutoff: "2026-05-25",
      data_staleness_days: 121,
      staleness_warning: "Base historica atualizada ate 2026-05-25.",
      results: [evaluatedResult()],
    });

    fireEvent.click(screen.getByRole("button", { name: "Avaliar no Radar" }));
    await waitFor(() => expect(screen.getByText("NÃO PASSOU DO LIMITE")).toBeInTheDocument());

    expect(screen.queryByText("Qualidade da amostra")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Detalhes técnicos" }));
    expect(screen.getByText("Qualidade da amostra")).toBeInTheDocument();
    expect(screen.getByText("HIGH")).toBeInTheDocument();
  });

  // LOTE H: botao "Registrar no Forward Test" so aparece para PASSOU DO
  // LIMITE/OBSERVAR, nunca para NAO PASSOU/SEM MODELO (item "INTEGRACAO COM
  // LOTE G" -- comportamento so de interface, nenhuma regra estatistica nova).
  describe("registro no Forward Test (LOTE H)", () => {
    async function evaluateWith(result: ReturnType<typeof evaluatedResult>) {
      mockedApi.evaluateScreenshot.mockResolvedValue({
        upload_id: "upload-1", extraction_id: "ex-1", match_key: MATCH_KEY,
        confirmed_at: "2026-09-23T12:00:02Z", historical_data_cutoff: "2026-05-25",
        data_staleness_days: 121, staleness_warning: "Base historica atualizada ate 2026-05-25.",
        results: [result],
      });
      fireEvent.click(screen.getByRole("button", { name: "Avaliar no Radar" }));
      await waitFor(() => expect(mockedApi.evaluateScreenshot).toHaveBeenCalled());
    }

    it("mostra o botao para PASSOU DO LIMITE", async () => {
      await reachConfirmedState();
      await evaluateWith(evaluatedResult({ decision_state: "CANDIDATO", evaluation_label: "PASSOU_DO_LIMITE" }));
      await waitFor(() => expect(screen.getByText("PASSOU DO LIMITE")).toBeInTheDocument());
      expect(screen.getByRole("button", { name: "Registrar no Forward Test" })).toBeInTheDocument();
    });

    it("mostra o botao para OBSERVAR", async () => {
      await reachConfirmedState();
      await evaluateWith(evaluatedResult({ decision_state: "OBSERVAR", evaluation_label: "OBSERVAR" }));
      await waitFor(() => expect(screen.getByText("OBSERVAR")).toBeInTheDocument());
      expect(screen.getByRole("button", { name: "Registrar no Forward Test" })).toBeInTheDocument();
    });

    it("nao mostra o botao para NAO PASSOU", async () => {
      await reachConfirmedState();
      await evaluateWith(evaluatedResult());
      await waitFor(() => expect(screen.getByText("NÃO PASSOU DO LIMITE")).toBeInTheDocument());
      expect(screen.queryByRole("button", { name: "Registrar no Forward Test" })).not.toBeInTheDocument();
    });

    it("nao mostra o botao para SEM MODELO", async () => {
      await reachConfirmedState();
      await evaluateWith(evaluatedResult({
        market: "total_games", decision_state: null, evaluation_label: "SEM_AVALIACAO_DISPONIVEL",
        evaluation_message: "Mercado ainda nao disponivel para avaliacao pelo modelo.",
        model_probability: null, fair_odds: null, minimum_odds: null, staleness_status: null,
        restricted: null, technical: null, forward_key: null, prediction_id: null,
      }));
      await waitFor(() => expect(screen.getByText("Mercado ainda nao disponivel para avaliacao pelo modelo.")).toBeInTheDocument());
      expect(screen.queryByRole("button", { name: "Registrar no Forward Test" })).not.toBeInTheDocument();
    });

    it("registra e mostra 'Ja registrado no Forward Test'", async () => {
      await reachConfirmedState();
      await evaluateWith(evaluatedResult({ decision_state: "CANDIDATO", evaluation_label: "PASSOU_DO_LIMITE" }));
      await waitFor(() => expect(screen.getByText("PASSOU DO LIMITE")).toBeInTheDocument());

      mockedApi.registerForwardPrediction.mockResolvedValue({
        status: "registered", prediction_id: "PRED_test0000000000", message: "Registrado no Forward Test.",
      });
      fireEvent.click(screen.getByRole("button", { name: "Registrar no Forward Test" }));

      await waitFor(() => expect(screen.getByText("Já registrado no Forward Test")).toBeInTheDocument());
      expect(mockedApi.registerForwardPrediction).toHaveBeenCalledWith(
        expect.objectContaining({ market: "aces_player", tour: "ATP" }),
      );
    });

    it("mostra 'Ja registrado' direto quando a API ja marca already_registered_forward_test", async () => {
      await reachConfirmedState();
      await evaluateWith(evaluatedResult({
        decision_state: "CANDIDATO", evaluation_label: "PASSOU_DO_LIMITE", already_registered_forward_test: true,
      }));
      await waitFor(() => expect(screen.getByText("Já registrado no Forward Test")).toBeInTheDocument());
      expect(screen.queryByRole("button", { name: "Registrar no Forward Test" })).not.toBeInTheDocument();
    });

    it("mostra erro e mantem o botao quando o registro falha", async () => {
      await reachConfirmedState();
      await evaluateWith(evaluatedResult({ decision_state: "OBSERVAR", evaluation_label: "OBSERVAR" }));
      await waitFor(() => expect(screen.getByText("OBSERVAR")).toBeInTheDocument());

      mockedApi.registerForwardPrediction.mockRejectedValueOnce(new Error("Oportunidade nao encontrada na Fase 10."));
      fireEvent.click(screen.getByRole("button", { name: "Registrar no Forward Test" }));

      await waitFor(() => expect(screen.getByText("Oportunidade nao encontrada na Fase 10.")).toBeInTheDocument());
      expect(screen.getByRole("button", { name: "Registrar no Forward Test" })).toBeInTheDocument();
    });
  });
});
