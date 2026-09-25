// Tela ENVIAR PRINT (LOTE E: upload) + LEITURA DO PRINT (LOTE F: leitura
// por IA, revisao editavel e confirmacao -- docs/018_PWA_ARQUITETURA.md
// secao 6.4/6.5). So os 2 mercados do LOTE F (ACES, GAMES_TOTALS) sao
// suportados; nada aqui recalcula probabilidade/odd/edge -- isso fica em
// src/ (lotes futuros, ainda nao iniciados).

import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import {
  confirmScreenshot,
  evaluateScreenshot,
  extractScreenshot,
  getRadarToday,
  registerForwardPrediction,
  uploadScreenshot,
} from "../services/api";
import type {
  ConfirmMarketInput,
  EvaluatedMarketResult,
  ExtractionMarket,
  NormalizedMarket,
  RadarLine,
  TabType,
} from "../types/api";
import { EVALUATION_LABEL_TEXT, MARKET_LABEL, formatOdds, formatProbability, sideLabel } from "../lib/radar";

type ContextState = "loading" | "loaded" | "offline";
type SendState = "idle" | "uploading" | "success" | "error";
type ExtractState = "idle" | "loading" | "loaded" | "error";
type ConfirmState = "idle" | "submitting" | "confirmed" | "error";
type EvaluateState = "idle" | "loading" | "loaded" | "error";

const EXTRACTION_MARKET_LABEL: Record<ExtractionMarket, string> = {
  aces_player: MARKET_LABEL.aces_player,
  total_aces_match: MARKET_LABEL.total_aces_match,
  total_games: "Total de Games",
};

// Mesmos formatos aceitos pelo backend (src/screenshot_parser/config.py) --
// checagem no cliente e so uma conveniencia de UX, a validacao real (Pillow
// abrindo os bytes de verdade) acontece no servidor.
const ACCEPTED_MIME_TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);
const MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024;

const TAB_TYPE_LABEL: Record<TabType, string> = {
  ACES: "Aces",
  GAMES_TOTALS: "Games Mais/Menos",
};

// Cor de destaque por rotulo (LOTE G, docs/018 secao 6.6) -- reaproveita
// so os tokens semanticos ja definidos em index.css (court = acento
// positivo/interacao). `clay` fica reservado para erro de sistema (mesma
// regra ja documentada em index.css), nunca para um estado do modelo.
const EVALUATION_LABEL_COLOR: Record<EvaluatedMarketResult["evaluation_label"], string> = {
  PASSOU_DO_LIMITE: "text-court",
  OBSERVAR: "text-chalk",
  NAO_PASSOU: "text-mist",
  SEM_AVALIACAO_DISPONIVEL: "text-mist",
};

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatTime(iso: string | null): string {
  if (!iso) return "horário não disponível";
  return new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "America/Sao_Paulo",
  }).format(new Date(iso));
}

function marketLine(line: RadarLine): string {
  const suffix = `${sideLabel(line.side)} ${line.line}`;
  return line.player ? `${line.player} — ${MARKET_LABEL[line.market]} ${suffix}` : `${MARKET_LABEL[line.market]} ${suffix}`;
}

export default function ScreenshotUploadPage() {
  const { matchKey = "" } = useParams<{ matchKey: string }>();

  const [contextState, setContextState] = useState<ContextState>("loading");
  const [matchLines, setMatchLines] = useState<RadarLine[]>([]);

  const [tabType, setTabType] = useState<TabType | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);

  const [sendState, setSendState] = useState<SendState>("idle");
  const [sendError, setSendError] = useState<string | null>(null);
  const [uploadId, setUploadId] = useState<string | null>(null);

  const [extractState, setExtractState] = useState<ExtractState>("idle");
  const [extractError, setExtractError] = useState<string | null>(null);
  const [extractionStatus, setExtractionStatus] = useState<"AUTO_VALIDATED" | "NEEDS_CONFIRMATION" | null>(null);
  const [extractionWarnings, setExtractionWarnings] = useState<string[]>([]);
  const [editableMarkets, setEditableMarkets] = useState<NormalizedMarket[]>([]);

  const [confirmState, setConfirmState] = useState<ConfirmState>("idle");
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [confirmedMarkets, setConfirmedMarkets] = useState<NormalizedMarket[] | null>(null);

  const [evaluateState, setEvaluateState] = useState<EvaluateState>("idle");
  const [evaluateError, setEvaluateError] = useState<string | null>(null);
  const [evaluationResults, setEvaluationResults] = useState<EvaluatedMarketResult[]>([]);
  const [evaluationStaleness, setEvaluationStaleness] = useState<string | null>(null);
  const [openTechnical, setOpenTechnical] = useState<Set<number>>(new Set());

  const [registerState, setRegisterState] = useState<Record<number, "submitting" | "error">>({});
  const [registerError, setRegisterError] = useState<Record<number, string>>({});

  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    let cancelled = false;

    getRadarToday()
      .then((data) => {
        if (!cancelled) {
          setMatchLines(data.filter((l) => l.match_key === matchKey));
          setContextState("loaded");
        }
      })
      .catch(() => {
        if (!cancelled) setContextState("offline");
      });

    return () => {
      cancelled = true;
    };
  }, [matchKey]);

  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  const header = matchLines[0];
  const marketsToCheck = useMemo(
    () => matchLines.filter((l) => l.decision_state === "CONFERIR_ODDS").map(marketLine),
    [matchLines],
  );

  function acceptFile(candidate: File) {
    setFileError(null);
    if (!ACCEPTED_MIME_TYPES.has(candidate.type)) {
      setFileError("Formato não suportado. Envie PNG, JPG ou WEBP.");
      return;
    }
    if (candidate.size > MAX_FILE_SIZE_BYTES) {
      setFileError("Arquivo maior que 10 MB.");
      return;
    }
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setFile(candidate);
    setPreviewUrl(URL.createObjectURL(candidate));
    setSendState("idle");
    setSendError(null);
    setUploadId(null);
  }

  function handleInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const candidate = e.target.files?.[0];
    if (candidate) acceptFile(candidate);
    e.target.value = "";
  }

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    const candidate = e.dataTransfer.files?.[0];
    if (candidate) acceptFile(candidate);
  }

  function handleDragOver(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
  }

  function handlePaste(e: React.ClipboardEvent<HTMLDivElement>) {
    const items = e.clipboardData?.items;
    if (!items) return;
    for (const item of Array.from(items)) {
      if (item.kind === "file") {
        const candidate = item.getAsFile();
        if (candidate) {
          acceptFile(candidate);
          break;
        }
      }
    }
  }

  function handleRemove() {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setFile(null);
    setPreviewUrl(null);
    setFileError(null);
    setSendState("idle");
    setSendError(null);
    setUploadId(null);
  }

  async function handleSubmit() {
    if (!file || !tabType) return;
    setSendState("uploading");
    setSendError(null);
    try {
      const result = await uploadScreenshot({ image: file, matchKey, tabType });
      setUploadId(result.upload_id);
      setSendState("success");
    } catch (err) {
      setSendError(err instanceof Error ? err.message : "Falha ao enviar print.");
      setSendState("error");
    }
  }

  const canSend = Boolean(file && tabType) && sendState !== "uploading";

  async function handleExtract() {
    if (!uploadId) return;
    setExtractState("loading");
    setExtractError(null);
    try {
      const result = await extractScreenshot(uploadId);
      setExtractionStatus(result.status);
      setExtractionWarnings(result.extraction_warnings);
      setEditableMarkets(result.markets);
      setConfirmState("idle");
      setConfirmError(null);
      setConfirmedMarkets(null);
      setExtractState("loaded");
    } catch (err) {
      setExtractError(err instanceof Error ? err.message : "Falha ao ler o print.");
      setExtractState("error");
    }
  }

  function updateMarketField(index: number, field: "player" | "bookmaker_display" | "decimal_odds", value: string) {
    setEditableMarkets((prev) =>
      prev.map((m, i) => {
        if (i !== index) return m;
        if (field === "decimal_odds") {
          const parsed = Number(value.replace(",", "."));
          return { ...m, decimal_odds: Number.isNaN(parsed) ? m.decimal_odds : parsed };
        }
        if (field === "player") return { ...m, player: value || null };
        return { ...m, bookmaker_display: value };
      }),
    );
  }

  async function handleConfirm() {
    if (!uploadId || editableMarkets.length === 0) return;
    setConfirmState("submitting");
    setConfirmError(null);
    try {
      const payload: ConfirmMarketInput[] = editableMarkets.map((m) => ({
        market: m.market,
        player: m.player,
        bookmaker_display: m.bookmaker_display,
        decimal_odds: m.decimal_odds,
      }));
      const result = await confirmScreenshot(uploadId, payload);
      setConfirmedMarkets(result.markets);
      setConfirmState("confirmed");
      setEvaluateState("idle");
      setEvaluateError(null);
      setEvaluationResults([]);
      setEvaluationStaleness(null);
      setOpenTechnical(new Set());
    } catch (err) {
      setConfirmError(err instanceof Error ? err.message : "Falha ao confirmar a leitura.");
      setConfirmState("error");
    }
  }

  async function handleEvaluate() {
    if (!uploadId) return;
    setEvaluateState("loading");
    setEvaluateError(null);
    try {
      const result = await evaluateScreenshot(uploadId);
      setEvaluationResults(result.results);
      setEvaluationStaleness(result.staleness_warning);
      setEvaluateState("loaded");
    } catch (err) {
      setEvaluateError(err instanceof Error ? err.message : "Falha ao avaliar no radar.");
      setEvaluateState("error");
    }
  }

  async function handleRegisterForward(index: number) {
    const r = evaluationResults[index];
    if (!r.forward_key) return;
    setRegisterState((prev) => ({ ...prev, [index]: "submitting" }));
    try {
      const result = await registerForwardPrediction(r.forward_key);
      if (result.status === "not_found" || result.status === "rejected_overwrite_attempt") {
        throw new Error(result.message);
      }
      setEvaluationResults((prev) =>
        prev.map((item, i) =>
          i === index
            ? { ...item, already_registered_forward_test: true, prediction_id: result.prediction_id ?? item.prediction_id }
            : item,
        ),
      );
      setRegisterState((prev) => {
        const next = { ...prev };
        delete next[index];
        return next;
      });
    } catch (err) {
      setRegisterState((prev) => ({ ...prev, [index]: "error" }));
      setRegisterError((prev) => ({
        ...prev,
        [index]: err instanceof Error ? err.message : "Falha ao registrar no Forward Test.",
      }));
    }
  }

  function toggleTechnical(index: number) {
    setOpenTechnical((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }

  return (
    <div onPaste={handlePaste}>
      <p className="font-display text-2xl font-semibold tracking-tight">Adicionar print da Betano</p>

      {contextState === "loading" && <p className="mt-4 text-sm text-mist">Carregando partida…</p>}

      {contextState === "offline" && (
        <p className="mt-4 text-sm text-clay">Não foi possível carregar os dados da partida.</p>
      )}

      {contextState === "loaded" && (
        <div className="mt-4 border border-rule p-4">
          {header ? (
            <>
              <p className="text-xs text-mist">
                {header.tour} · {header.tournament} · {formatTime(header.event_datetime_sao_paulo)}
              </p>
              <p className="mt-2 font-display text-base text-chalk">
                {header.player_a} x {header.player_b}
              </p>
              {marketsToCheck.length > 0 ? (
                <ul className="mt-3 flex flex-col gap-1 text-sm text-mist">
                  {marketsToCheck.map((m) => (
                    <li key={m}>{m}</li>
                  ))}
                </ul>
              ) : (
                <p className="mt-3 text-sm text-mist">Nenhum mercado marcado para conferir odds nesta partida.</p>
              )}
            </>
          ) : (
            <p className="text-sm text-mist">Partida não encontrada no radar do dia.</p>
          )}
        </div>
      )}

      {sendState === "success" && uploadId ? (
        <div className="mt-6 flex flex-col gap-4">
          <div className="border border-rule p-4">
            <p className="font-display text-base text-chalk">Print salvo com sucesso</p>
            <p className="mt-1 text-sm text-mist">ID do envio: {uploadId}</p>
          </div>

          {extractState === "idle" && (
            <button
              type="button"
              onClick={handleExtract}
              className="self-start border border-court px-4 py-2 text-sm text-court"
            >
              Ler print
            </button>
          )}

          {extractState === "loading" && <p className="text-sm text-mist">Analisando imagem…</p>}

          {extractState === "error" && (
            <div>
              <p className="text-sm text-clay">{extractError}</p>
              <button type="button" onClick={handleExtract} className="mt-2 border border-rule px-4 py-2 text-sm text-chalk">
                Tentar novamente
              </button>
            </div>
          )}

          {extractState === "loaded" && (
            <div className="border border-rule p-4">
              {extractionStatus === "NEEDS_CONFIRMATION" && confirmState !== "confirmed" && (
                <p className="mb-3 text-sm font-semibold uppercase tracking-wide text-clay">
                  Confirme esta leitura
                </p>
              )}

              {extractionWarnings.includes("NENHUM_MERCADO_ENCONTRADO") && (
                <p className="mb-3 text-sm text-mist">Nenhum mercado foi lido nesta imagem.</p>
              )}

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {previewUrl && (
                  <img src={previewUrl} alt="Print original" className="max-h-96 self-start object-contain" />
                )}

                <div className="flex flex-col gap-3">
                  {(confirmState === "confirmed" ? confirmedMarkets ?? [] : editableMarkets).map((m, i) => (
                    <div key={i} className="border border-rule p-3 text-sm">
                      <p className="text-xs uppercase tracking-wide text-mist">
                        {EXTRACTION_MARKET_LABEL[m.market]}
                        {m.side ? ` · ${sideLabel(m.side.toLowerCase())} ${m.model_line ?? ""}` : ""}
                      </p>

                      {confirmState === "confirmed" ? (
                        <>
                          <p className="mt-1 text-chalk">{m.player ?? "Partida"}</p>
                          <p className="text-mist">
                            {m.bookmaker_display} · odd {m.decimal_odds}
                          </p>
                        </>
                      ) : (
                        <div className="mt-2 flex flex-col gap-2">
                          {m.market === "aces_player" && (
                            <label className="flex flex-col gap-1">
                              <span className="text-xs text-mist">Jogador</span>
                              <input
                                type="text"
                                value={m.player ?? ""}
                                onChange={(e) => updateMarketField(i, "player", e.target.value)}
                                className="border border-rule bg-transparent px-2 py-1 text-chalk"
                              />
                            </label>
                          )}
                          <label className="flex flex-col gap-1">
                            <span className="text-xs text-mist">Linha exibida pela casa</span>
                            <input
                              type="text"
                              value={m.bookmaker_display}
                              onChange={(e) => updateMarketField(i, "bookmaker_display", e.target.value)}
                              className="border border-rule bg-transparent px-2 py-1 text-chalk"
                            />
                          </label>
                          <label className="flex flex-col gap-1">
                            <span className="text-xs text-mist">Odd</span>
                            <input
                              type="text"
                              inputMode="decimal"
                              value={m.decimal_odds}
                              onChange={(e) => updateMarketField(i, "decimal_odds", e.target.value)}
                              className="border border-rule bg-transparent px-2 py-1 text-chalk"
                            />
                          </label>
                        </div>
                      )}

                      {m.warnings.length > 0 && (
                        <ul className="mt-2 flex flex-wrap gap-1">
                          {m.warnings.map((w) => (
                            <li key={w} className="border border-clay px-2 py-0.5 text-xs text-clay">
                              {w}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              {confirmState === "confirmed" ? (
                <div className="mt-4">
                  <p className="font-display text-base text-chalk">Leitura confirmada</p>

                  {evaluateState === "idle" && (
                    <button
                      type="button"
                      onClick={handleEvaluate}
                      className="mt-3 self-start border border-court px-4 py-2 text-sm text-court"
                    >
                      Avaliar no Radar
                    </button>
                  )}

                  {evaluateState === "loading" && (
                    <p className="mt-3 text-sm text-mist">Comparando com o modelo…</p>
                  )}

                  {evaluateState === "error" && (
                    <div className="mt-3">
                      <p className="text-sm text-clay">{evaluateError}</p>
                      <button
                        type="button"
                        onClick={handleEvaluate}
                        className="mt-2 border border-rule px-4 py-2 text-sm text-chalk"
                      >
                        Tentar novamente
                      </button>
                    </div>
                  )}

                  {evaluateState === "loaded" && (
                    <div className="mt-4 flex flex-col gap-3">
                      {evaluationStaleness && <p className="text-xs text-mist">{evaluationStaleness}</p>}

                      {evaluationResults.map((r, i) => (
                        <div key={i} className="border border-rule p-3 text-sm">
                          <p className="text-xs uppercase tracking-wide text-mist">
                            {EXTRACTION_MARKET_LABEL[r.market]}
                          </p>
                          <p className="mt-1 font-display text-base text-chalk">
                            {r.player ?? "Partida"} — {r.bookmaker_display}
                          </p>

                          {r.error ? (
                            <p className="mt-2 text-sm text-clay">{r.error}</p>
                          ) : r.evaluation_label === "SEM_AVALIACAO_DISPONIVEL" ? (
                            <p className="mt-2 text-sm text-mist">{r.evaluation_message}</p>
                          ) : (
                            <>
                              <dl className="mt-2 grid grid-cols-2 gap-1 text-sm text-mist">
                                <dt>Probabilidade</dt>
                                <dd className="text-chalk">
                                  {r.model_probability !== null ? formatProbability(r.model_probability) : "não disponível"}
                                </dd>
                                <dt>Odd justa</dt>
                                <dd className="text-chalk">{formatOdds(r.fair_odds)}</dd>
                                <dt>Odd mínima</dt>
                                <dd className="text-chalk">{formatOdds(r.minimum_odds)}</dd>
                                <dt>Betano</dt>
                                <dd className="text-chalk">{formatOdds(r.bookmaker_odds)}</dd>
                              </dl>

                              <p
                                className={`mt-3 font-display text-sm font-semibold uppercase tracking-wide ${EVALUATION_LABEL_COLOR[r.evaluation_label]}`}
                              >
                                {EVALUATION_LABEL_TEXT[r.evaluation_label]}
                              </p>

                              {r.forward_key && (r.evaluation_label === "PASSOU_DO_LIMITE" || r.evaluation_label === "OBSERVAR") && (
                                <div className="mt-3">
                                  {r.already_registered_forward_test ? (
                                    <p className="text-xs uppercase tracking-wide text-mist">
                                      Já registrado no Forward Test
                                    </p>
                                  ) : registerState[i] === "submitting" ? (
                                    <p className="text-xs text-mist">Registrando…</p>
                                  ) : (
                                    <button
                                      type="button"
                                      onClick={() => handleRegisterForward(i)}
                                      className="border border-court px-3 py-1 text-xs text-court"
                                    >
                                      Registrar no Forward Test
                                    </button>
                                  )}
                                  {registerState[i] === "error" && (
                                    <p className="mt-1 text-xs text-clay">{registerError[i]}</p>
                                  )}
                                </div>
                              )}
                            </>
                          )}

                          {r.technical && (
                            <div className="mt-3">
                              <button
                                type="button"
                                onClick={() => toggleTechnical(i)}
                                className="text-xs uppercase tracking-wide text-mist underline"
                              >
                                Detalhes técnicos
                              </button>
                              {openTechnical.has(i) && (
                                <dl className="mt-2 grid grid-cols-2 gap-1 text-xs text-mist">
                                  <dt>Prob. implícita</dt>
                                  <dd>
                                    {r.technical.implied_probability !== null
                                      ? formatProbability(r.technical.implied_probability)
                                      : "não disponível"}
                                  </dd>
                                  <dt>Edge do modelo</dt>
                                  <dd>
                                    {r.technical.model_edge !== null ? formatProbability(r.technical.model_edge) : "não disponível"}
                                  </dd>
                                  <dt>Qualidade da amostra</dt>
                                  <dd>{r.technical.sample_quality ?? "não disponível"}</dd>
                                  <dt>Restrito</dt>
                                  <dd>{r.restricted ? "sim" : "não"}</dd>
                                  <dt>Defasagem</dt>
                                  <dd>{r.staleness_status ?? "não disponível"}</dd>
                                  {r.technical.match_reason && (
                                    <>
                                      <dt>Motivo</dt>
                                      <dd>{r.technical.match_reason}</dd>
                                    </>
                                  )}
                                </dl>
                              )}
                            </div>
                          )}
                        </div>
                      ))}

                      <button
                        type="button"
                        onClick={handleEvaluate}
                        className="self-start text-xs uppercase tracking-wide text-mist underline"
                      >
                        Avaliar novamente
                      </button>
                    </div>
                  )}
                </div>
              ) : (
                <>
                  {confirmError && <p className="mt-3 text-sm text-clay">{confirmError}</p>}
                  <button
                    type="button"
                    onClick={handleConfirm}
                    disabled={editableMarkets.length === 0 || confirmState === "submitting"}
                    className="mt-4 border border-court px-4 py-2 text-sm text-court disabled:opacity-40"
                  >
                    {confirmState === "submitting" ? "Confirmando…" : "Confirmar leitura"}
                  </button>
                </>
              )}
            </div>
          )}
        </div>
      ) : (
        <>
          <div className="mt-6 flex gap-3">
            {(Object.keys(TAB_TYPE_LABEL) as TabType[]).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTabType(t)}
                aria-pressed={tabType === t}
                className={`border px-4 py-2 text-sm ${
                  tabType === t ? "border-court text-court" : "border-rule text-mist"
                }`}
              >
                {TAB_TYPE_LABEL[t]}
              </button>
            ))}
          </div>

          <div
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            data-testid="dropzone"
            className="mt-4 flex flex-col items-center justify-center border border-dashed border-rule p-8 text-center"
          >
            {previewUrl && file ? (
              <>
                <img src={previewUrl} alt="Pré-visualização do print" className="max-h-64 object-contain" />
                <p className="mt-3 text-sm text-chalk">{file.name}</p>
                <p className="text-xs text-mist">
                  {formatFileSize(file.size)} · {file.type}
                </p>
                <button type="button" onClick={handleRemove} className="mt-3 text-xs uppercase tracking-wide text-clay">
                  Remover
                </button>
              </>
            ) : (
              <>
                <p className="text-sm text-mist">Arraste um print aqui, cole com Ctrl+V ou</p>
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="mt-3 border border-rule px-4 py-2 text-sm text-chalk"
                >
                  Selecionar arquivo
                </button>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  className="hidden"
                  onChange={handleInputChange}
                  aria-label="Selecionar arquivo de print"
                />
              </>
            )}
          </div>

          {fileError && <p className="mt-2 text-sm text-clay">{fileError}</p>}
          {sendError && <p className="mt-2 text-sm text-clay">{sendError}</p>}
          {!tabType && file && <p className="mt-2 text-sm text-mist">Selecione o tipo de aba antes de enviar.</p>}

          <button
            type="button"
            onClick={handleSubmit}
            disabled={!canSend}
            className="mt-4 border border-court px-4 py-2 text-sm text-court disabled:opacity-40"
          >
            {sendState === "uploading" ? "Enviando…" : "Enviar print"}
          </button>
        </>
      )}
    </div>
  );
}
