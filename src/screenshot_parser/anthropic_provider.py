"""Implementacao real (opcional) de `ScreenshotVisionProvider` usando a
API de mensagens da Anthropic (docs/018 secao 7.3 "VisionExtractor").

Usa `requests` (ja e dependencia do projeto -- nenhuma dependencia nova
adicionada so por isto, CLAUDE.md Sec.20) para chamar a API diretamente,
em vez de adicionar o SDK `anthropic` inteiro so para uma chamada.

Configuracao (nenhum valor hardcoded que possa estar errado/desatualizado
-- falha cedo e com mensagem clara em vez de adivinhar):
  - `ANTHROPIC_API_KEY` (obrigatoria) -- chave de API.
  - `TENNIS_RADAR_VISION_MODEL` (obrigatoria) -- id do modelo de visao a
    usar; este modulo nunca escolhe um default, porque o id correto muda
    entre contas/versoes e um palpite errado falharia silenciosamente
    tarde demais.
  - `TENNIS_RADAR_VISION_TIMEOUT_SECONDS` (opcional, default 60).

Nunca entra na suite automatica com uma chamada de rede real (pedido
explicito) -- `tests/test_screenshot_parser.py` testa este modulo
substituindo `requests.post` por um mock.
"""

from __future__ import annotations

import base64
import json
import os

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
        "Responda EXCLUSIVAMENTE com um JSON valido (sem markdown, sem texto antes ou depois): uma "
        "lista de objetos com exatamente estes campos:\n"
        '  "market": "aces_player" | "total_aces_match" | "total_games"\n'
        '  "player": nome do jogador exatamente como na imagem, ou null para mercados de partida\n'
        '  "bookmaker_display": o texto exibido pela casa para a linha (ex.: "6+", "Mais de 22.5")\n'
        '  "decimal_odds": a odd decimal exibida, como numero\n'
        '  "source_confidence": sua confianca nesta leitura, de 0.0 a 1.0\n'
    )


class AnthropicVisionProvider:
    name = "anthropic"

    def __init__(self):
        self._api_key = os.environ.get(cfg.ANTHROPIC_API_KEY_ENV_VAR)
        self._model = os.environ.get(cfg.VISION_MODEL_ENV_VAR)
        timeout_raw = os.environ.get(cfg.VISION_TIMEOUT_ENV_VAR)
        try:
            self._timeout = float(timeout_raw) if timeout_raw else cfg.DEFAULT_VISION_TIMEOUT_SECONDS
        except ValueError:
            self._timeout = cfg.DEFAULT_VISION_TIMEOUT_SECONDS

    def extract(self, image_path, context: ExtractionContext) -> ProviderExtraction:
        if not self._api_key:
            raise ProviderUnavailableError(
                f"Variavel de ambiente {cfg.ANTHROPIC_API_KEY_ENV_VAR} nao configurada."
            )
        if not self._model:
            raise ProviderUnavailableError(
                f"Variavel de ambiente {cfg.VISION_MODEL_ENV_VAR} nao configurada (id do modelo de visao)."
            )

        media_type = _MEDIA_TYPE_BY_SUFFIX.get(image_path.suffix.lower())
        if media_type is None:
            raise ProviderResponseError(f"Extensao de imagem nao suportada pelo provider: {image_path.suffix!r}.")

        image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
        prompt = _build_prompt(context)

        payload = {
            "model": self._model,
            "max_tokens": 2048,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": media_type, "data": image_b64},
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        }
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": cfg.ANTHROPIC_API_VERSION,
            "content-type": "application/json",
        }

        try:
            response = requests.post(
                cfg.ANTHROPIC_MESSAGES_URL, headers=headers, json=payload, timeout=self._timeout
            )
        except requests.Timeout as exc:
            raise ProviderTimeoutError("Tempo esgotado ao consultar o provedor de visao.") from exc
        except requests.RequestException as exc:
            raise ProviderUnavailableError(f"Falha de rede ao consultar o provedor de visao: {exc}") from exc

        if response.status_code in (401, 403):
            raise ProviderUnavailableError("Provedor de visao recusou a autenticacao (API key invalida).")
        if response.status_code == 429:
            raise ProviderUnavailableError("Provedor de visao indisponivel no momento (limite de uso atingido).")
        if response.status_code >= 500:
            raise ProviderUnavailableError(f"Provedor de visao indisponivel (HTTP {response.status_code}).")
        if response.status_code != 200:
            raise ProviderResponseError(f"Provedor de visao devolveu HTTP {response.status_code}: {response.text[:500]}")

        try:
            body = response.json()
            text = "".join(block.get("text", "") for block in body.get("content", []) if block.get("type") == "text")
        except (ValueError, AttributeError) as exc:
            raise ProviderResponseError("Resposta do provedor de visao em formato inesperado.") from exc

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
            # Leitura sem os campos minimos -- nunca inventar, so ignorar
            # esta linha (o restante da extracao continua).
            continue
        try:
            decimal_odds = float(decimal_odds)
        except (TypeError, ValueError):
            continue
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
