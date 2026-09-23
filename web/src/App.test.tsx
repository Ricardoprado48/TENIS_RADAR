// Testes da fundacao do frontend (LOTE B, docs/018_PWA_ARQUITETURA.md):
// renderizacao da aplicacao, estado ONLINE, estado offline (sem inventar
// dado), leitura de /api/info e navegacao provisoria. Calendario (LOTE C),
// radar (LOTE D) e forward test (LOTE H) tem testes proprios em
// CalendarPage.test.tsx/RadarPage.test.tsx/ForwardPage.test.tsx -- aqui a
// navegacao usa "Config" (Configuracoes), unica area ainda provisoria.

import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";
import * as api from "./services/api";
import type { InfoResponse } from "./types/api";

vi.mock("./services/api");

const mockedApi = vi.mocked(api);

const SAMPLE_INFO: InfoResponse = {
  app: "Tennis Radar",
  api_version: "0.1.0",
  timezone: "America/Sao_Paulo",
  default_bookmaker: "Betano",
  historical_data_cutoff: "2026-05-25",
  forward_version_id: "TENNIS_RADAR_V1_FORWARD",
};

function renderApp() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <App />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("HomePage", () => {
  it("renderiza a aplicação e mostra o estado de carregamento antes da resposta da API", () => {
    mockedApi.getHealth.mockImplementation(() => new Promise(() => {}));
    mockedApi.getInfo.mockImplementation(() => new Promise(() => {}));

    renderApp();

    expect(screen.getByText("Tennis Radar")).toBeInTheDocument();
    expect(screen.getByText("Verificando sistema…")).toBeInTheDocument();
  });

  it("mostra sistema online e os dados de /api/info quando a API responde", async () => {
    mockedApi.getHealth.mockResolvedValue({ status: "ok", app: "Tennis Radar" });
    mockedApi.getInfo.mockResolvedValue(SAMPLE_INFO);

    renderApp();

    await waitFor(() => expect(screen.getByText("Sistema online")).toBeInTheDocument());
    expect(screen.getByText("America/Sao_Paulo")).toBeInTheDocument();
    expect(screen.getByText("Betano")).toBeInTheDocument();
    expect(screen.getByText("25/05/2026")).toBeInTheDocument();
    expect(screen.getByText("TENNIS_RADAR_V1_FORWARD")).toBeInTheDocument();
  });

  it("mostra sistema indisponível quando a API falha, sem inventar nenhum dado", async () => {
    mockedApi.getHealth.mockRejectedValue(new Error("network error"));

    renderApp();

    await waitFor(() => expect(screen.getByText("Sistema indisponível")).toBeInTheDocument());
    expect(screen.queryByText("America/Sao_Paulo")).not.toBeInTheDocument();
    expect(mockedApi.getInfo).not.toHaveBeenCalled();
  });

  it('mostra "não disponível" quando historical_data_cutoff vem null, em vez de inventar uma data', async () => {
    mockedApi.getHealth.mockResolvedValue({ status: "ok", app: "Tennis Radar" });
    mockedApi.getInfo.mockResolvedValue({ ...SAMPLE_INFO, historical_data_cutoff: null });

    renderApp();

    await waitFor(() => expect(screen.getByText("Sistema online")).toBeInTheDocument());
    expect(screen.getByText("não disponível")).toBeInTheDocument();
  });
});

describe("Navegação provisória", () => {
  it('mostra "Em desenvolvimento" ao navegar para uma área ainda não implementada', async () => {
    mockedApi.getHealth.mockResolvedValue({ status: "ok", app: "Tennis Radar" });
    mockedApi.getInfo.mockResolvedValue(SAMPLE_INFO);

    renderApp();

    const configLinks = screen.getAllByRole("link", { name: "Config" });
    fireEvent.click(configLinks[0]);

    expect(await screen.findByText("Em desenvolvimento.")).toBeInTheDocument();
  });
});
