"""Implementacao de `ScreenshotVisionProvider` usando a API Google Gemini
(generativelanguage.googleapis.com / models.generateContent).

Usa `requests` (ja dependencia do projeto -- sem SDKs adicionais, CLAUDE.md Sec.20)
para chamar o endpoint REST v1beta diretamente com a imagem codificada em base64
(inlineData) e generationConfig.responseMimeType="application/json".

Configuracao via variaveis de ambiente:
  - `GEMINI_API_KEY` (obrigatoria) -- chave da API Gemini.
  - `GEMINI_MODEL` (opcional) -- modelo de visao; se ausente, utiliza
    `cfg.DEFAULT_GEMINI_MODEL` ("gemini-2.5-flash").
  - `TENNIS_RADAR_VISION_TIMEOUT_SECONDS` (opcional, default 60).

Nunca entra na suite automatica com chamadas de rede reais (testes usam mock).
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import requests

from . import config as cfg
from .models import RawReading
from .providers import (
    ExtractionContext,
    ProviderExtraction,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

_MEDIA_TYPE_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def _build_prompt(context: ExtractionContext) -> str:
    ctx = context.match_context
    players_hint = ""
    if ctx is not None and (ctx.player_a or ctx.player_b):
        players_hint = (
            f"\nOs dois jogadores desta partida sao: {ctx.player_a!r} e {ctx.player_b!r}. "
            "Use esses nomes exatamente como aparecem aqui quando identificar o jogador de um "
            "mercado de aces por jogador."
        )

    if context.tab_type == cfg.TabType.ACES.value:
        markets_hint = (
            'Os mercados possiveis sao "aces_player" (aces de um jogador especifico, com o rotulo '
            'do tipo "X+") e "total_aces_match" (total de aces da partida, mesmo formato "X+", sem '
            "jogador associado -- use player=null)."
        )
    else:
        markets_hint = (
            'O unico mercado possivel e "total_games" (total de games da partida), com rotulos do '
            'tipo "Mais de N.N" ou "Menos de N.N" -- use player=null.'
        )

    return (
        "Voce esta lendo um print de tela de uma casa de apostas esportivas (mercados de tenis). "
        f"{markets_hint}{players_hint}\n\n"
        "Extraia SOMENTE os mercados que estiverem claramente legiveis na imagem. Nunca invente um "
        "jogador, linha ou odd que nao esteja visivel. Se um valor estiver ilegivel, nao inclua essa "
        "linha.\n\n"
        "Responda EXCLUSIVAMENTE com um JSON valido: uma lista de objetos com exatamente estes campos:\n"
        '  "market": "aces_player" | "total_aces_match" | "total_games"\n'
        '  "player": nome do jogador exatamente como na imagem, ou null para mercados de partida\n'
        '  "bookmaker_display": o texto exibido pela casa para a linha (ex.: "6+", "Mais de 22.5")\n'
        '  "decimal_odds": a odd decimal exibida, como numero\n'
        '  "confidence": sua confianca nesta leitura, de 0.0 a 1.0\n'
    )


class GeminiVisionProvider:
    name = "gemini"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.environ.get(cfg.GEMINI_API_KEY_ENV_VAR)

        if model is not None:
            self._model = model
        else:
            if cfg.GEMINI_MODEL_ENV_VAR in os.environ:
                env_model = os.environ.get(cfg.GEMINI_MODEL_ENV_VAR, "")
                self._model = env_model.strip()
            else:
                self._model = cfg.DEFAULT_GEMINI_MODEL

        if timeout is not None:
            self._timeout = timeout
        else:
            timeout_raw = os.environ.get(cfg.VISION_TIMEOUT_ENV_VAR)
            try:
                self._timeout = float(timeout_raw) if timeout_raw else cfg.DEFAULT_VISION_TIMEOUT_SECONDS
            except ValueError:
                self._timeout = cfg.DEFAULT_VISION_TIMEOUT_SECONDS

    def extract(self, image_path: Path, context: ExtractionContext) -> ProviderExtraction:
        if not self._api_key or not self._api_key.strip():
            raise ProviderUnavailableError(
                f"Variavel de ambiente {cfg.GEMINI_API_KEY_ENV_VAR} nao configurada."
            )
        if not self._model or not self._model.strip():
            raise ProviderUnavailableError(
                f"Variavel de ambiente {cfg.GEMINI_MODEL_ENV_VAR} configurada com valor invalido/vazio."
            )

        media_type = _MEDIA_TYPE_BY_SUFFIX.get(image_path.suffix.lower())
        if media_type is None:
            raise ProviderResponseError(
                f"Extensao de imagem nao suportada pelo provider: {image_path.suffix!r}."
            )

        try:
            image_bytes = image_path.read_bytes()
        except OSError as exc:
            raise ProviderResponseError(f"Falha ao ler arquivo de imagem: {exc}") from exc

        image_b64 = base64.b64encode(image_bytes).decode("ascii")
        prompt = _build_prompt(context)

        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": media_type,
                                "data": image_b64,
                            }
                        },
                        {"text": prompt},
                    ]
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.0,
            },
        }

        url = cfg.GEMINI_GENERATE_CONTENT_URL.format(model=self._model)
        headers = {
            "x-goog-api-key": self._api_key.strip(),
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=self._timeout)
        except requests.Timeout as exc:
            raise ProviderTimeoutError("Tempo esgotado ao consultar o provedor de visao (Gemini).") from exc
        except requests.RequestException as exc:
            raise ProviderUnavailableError(f"Falha de rede ao consultar o provedor de visao (Gemini): {exc}") from exc

        if response.status_code in (401, 403):
            raise ProviderUnavailableError("Provedor de visao (Gemini) recusou a autenticacao (API key invalida).")
        if response.status_code == 429:
            raise ProviderUnavailableError("Provedor de visao (Gemini) indisponivel no momento (limite de uso atingido).")
        if response.status_code >= 500:
            raise ProviderUnavailableError(f"Provedor de visao (Gemini) indisponivel (HTTP {response.status_code}).")
        if response.status_code != 200:
            raise ProviderResponseError(
                f"Provedor de visao (Gemini) devolveu HTTP {response.status_code}: {response.text[:500]}"
            )

        try:
            body = response.json()
        except Exception as exc:
            raise ProviderResponseError("Resposta do provedor Gemini nao e um JSON valido.") from exc

        if not isinstance(body, dict):
            raise ProviderResponseError("Resposta do provedor Gemini em formato inesperado (nao e um objeto JSON).")

        candidates = body.get("candidates")
        if not candidates or not isinstance(candidates, list):
            prompt_feedback = body.get("promptFeedback")
            raise ProviderResponseError(f"Gemini nao retornou candidatos validos. Feedback: {prompt_feedback}")

        content = candidates[0].get("content")
        if not isinstance(content, dict):
            raise ProviderResponseError("Candidato retornado pelo Gemini sem conteudo valido.")

        parts = content.get("parts")
        if not isinstance(parts, list) or not parts:
            raise ProviderResponseError("Conteudo do Gemini sem partes de texto.")

        text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
        if not text.strip():
            raise ProviderResponseError("Resposta vazia do provedor Gemini.")

        readings = _parse_readings(text)
        return ProviderExtraction(readings=readings, raw_response=text, model=self._model)


def _parse_readings(text: str) -> list[RawReading]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:]
        stripped = stripped.strip()

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ProviderResponseError("Resposta do provedor de visao nao e um JSON valido.") from exc

    if not isinstance(parsed, list):
        raise ProviderResponseError("Resposta do provedor de visao nao e uma lista de leituras.")

    readings: list[RawReading] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        market = item.get("market")
        bookmaker_display = item.get("bookmaker_display")
        decimal_odds = item.get("decimal_odds")
        if market not in cfg.SUPPORTED_MARKETS or not bookmaker_display or decimal_odds is None:
            continue
        try:
            decimal_odds = float(decimal_odds)
        except (TypeError, ValueError):
            continue

        confidence = item.get("confidence")
        if confidence is None:
            confidence = item.get("source_confidence")
        try:
            confidence = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            confidence = None

        readings.append(
            RawReading(
                market=market,
                player=item.get("player") or None,
                bookmaker_display=str(bookmaker_display),
                decimal_odds=decimal_odds,
                source_confidence=confidence,
            )
        )
    return readings

