// Unica camada de comunicacao com a API (docs/018_PWA_ARQUITETURA.md,
// secao "COMUNICACAO COM API"): nenhum componente chama fetch() direto.
// Os componentes usam sempre caminhos relativos (/api/...) -- o host/porta
// do backend fica so no proxy do Vite (vite.config.ts), nunca hardcoded
// aqui ou em uma tela.

import type {
  ConfirmMarketInput,
  ConfirmResponse,
  EvaluateResponse,
  ExtractionResponse,
  ForwardKey,
  ForwardSummaryResponse,
  HealthResponse,
  InfoResponse,
  MatchSchedule,
  PredictionDetailResponse,
  PredictionListResponse,
  RadarLine,
  RegisterForwardResponse,
  ScreenshotUploadResponse,
  TabType,
} from "../types/api";

async function getJSON<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`Falha ao consultar ${path}: HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

async function postJSON<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    const errorBody = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(errorBody?.detail ?? `Falha ao consultar ${path}: HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function getHealth(): Promise<HealthResponse> {
  return getJSON<HealthResponse>("/api/health");
}

export function getInfo(): Promise<InfoResponse> {
  return getJSON<InfoResponse>("/api/info");
}

export function getCalendar(dateFrom: string, dateTo: string): Promise<MatchSchedule[]> {
  const params = new URLSearchParams({ date_from: dateFrom, date_to: dateTo });
  return getJSON<MatchSchedule[]>(`/api/calendar?${params.toString()}`);
}

export function getRadarToday(): Promise<RadarLine[]> {
  return getJSON<RadarLine[]>("/api/radar/today");
}

export async function uploadScreenshot(params: {
  image: File;
  matchKey: string;
  tabType: TabType;
}): Promise<ScreenshotUploadResponse> {
  const formData = new FormData();
  formData.append("image", params.image);
  formData.append("match_key", params.matchKey);
  formData.append("tab_type", params.tabType);

  const response = await fetch("/api/screenshots", { method: "POST", body: formData });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? `Falha ao enviar print: HTTP ${response.status}`);
  }
  return response.json() as Promise<ScreenshotUploadResponse>;
}

export function extractScreenshot(uploadId: string): Promise<ExtractionResponse> {
  return postJSON<ExtractionResponse>(`/api/screenshots/${uploadId}/extract`);
}

export function getExtraction(uploadId: string): Promise<ExtractionResponse> {
  return getJSON<ExtractionResponse>(`/api/screenshots/${uploadId}/extraction`);
}

export function confirmScreenshot(uploadId: string, markets: ConfirmMarketInput[]): Promise<ConfirmResponse> {
  return postJSON<ConfirmResponse>(`/api/screenshots/${uploadId}/confirm`, { markets });
}

export function evaluateScreenshot(uploadId: string): Promise<EvaluateResponse> {
  return postJSON<EvaluateResponse>(`/api/screenshots/${uploadId}/evaluate`);
}

export function getForwardSummary(): Promise<ForwardSummaryResponse> {
  return getJSON<ForwardSummaryResponse>("/api/forward/summary");
}

export function getForwardPredictions(params: {
  tour?: "ATP" | "WTA";
  settlementGroup?: "pendentes" | "resolvidas";
  classificationGroup?: "candidato" | "observar" | "descartado";
  limit?: number;
  offset?: number;
} = {}): Promise<PredictionListResponse> {
  const query = new URLSearchParams();
  if (params.tour) query.set("tour", params.tour);
  if (params.settlementGroup) query.set("settlement_group", params.settlementGroup);
  if (params.classificationGroup) query.set("classification_group", params.classificationGroup);
  query.set("limit", String(params.limit ?? 50));
  query.set("offset", String(params.offset ?? 0));
  return getJSON<PredictionListResponse>(`/api/forward/predictions?${query.toString()}`);
}

export function getForwardPrediction(predictionId: string): Promise<PredictionDetailResponse> {
  return getJSON<PredictionDetailResponse>(`/api/forward/predictions/${predictionId}`);
}

export function registerForwardPrediction(forwardKey: ForwardKey): Promise<RegisterForwardResponse> {
  return postJSON<RegisterForwardResponse>("/api/forward/register", forwardKey);
}
