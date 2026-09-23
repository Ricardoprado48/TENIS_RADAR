"""Interface abstrata de leitura visual (secao "IA / VISAO" do pedido do
LOTE F): `ScreenshotVisionProvider` -- nunca acopla o resto do sistema a
um unico fornecedor. `anthropic_provider.py` traz a implementacao real
(opcional, configuravel por variavel de ambiente); este modulo so define o
contrato + os erros + um provider falso usado nos testes (nenhuma chamada
real de IA entra na suite automatica, conforme pedido)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .models import MatchContext, RawReading


class VisionProviderError(RuntimeError):
    """Base de erros do provider -- capturada em api/routes/screenshots.py
    e traduzida para o status HTTP apropriado (secao "ERROS" do pedido)."""


class ProviderUnavailableError(VisionProviderError):
    """Provider nao configurado (ex.: falta API key) ou fora do ar."""


class ProviderTimeoutError(VisionProviderError):
    """O provider nao respondeu dentro do prazo configurado."""


class ProviderResponseError(VisionProviderError):
    """O provider respondeu, mas o conteudo nao pode ser interpretado como
    uma lista de leituras (JSON invalido, campo obrigatorio ausente)."""


@dataclass(frozen=True)
class ExtractionContext:
    """Contexto passado ao provider -- so serve para ajudar a leitura
    (ex.: saber quais jogadores procurar); nunca usado para inventar um
    valor que nao apareca na imagem (pedido explicito)."""

    match_context: MatchContext | None
    tab_type: str


@dataclass(frozen=True)
class ProviderExtraction:
    """O que um provider devolve: leituras brutas + a resposta crua (para
    auditoria em `raw_provider_response`)."""

    readings: list[RawReading]
    raw_response: str
    model: str | None = None


class ScreenshotVisionProvider(Protocol):
    name: str

    def extract(self, image_path: Path, context: ExtractionContext) -> ProviderExtraction: ...


class FakeVisionProvider:
    """Provider deterministico para testes: devolve sempre as leituras
    passadas no construtor, nunca faz IO/rede. Usar `FakeVisionProvider`
    para simular sucesso e `FailingVisionProvider` para simular os erros
    da secao "ERROS" do pedido."""

    name = "fake"

    def __init__(self, readings: list[RawReading], *, model: str | None = "fake-vision-v1", raw_response: str = "{}"):
        self._readings = readings
        self._model = model
        self._raw_response = raw_response

    def extract(self, image_path: Path, context: ExtractionContext) -> ProviderExtraction:
        return ProviderExtraction(readings=list(self._readings), raw_response=self._raw_response, model=self._model)


class FailingVisionProvider:
    """Provider que sempre levanta o erro passado no construtor -- usado
    para testar o mapeamento de erros do provider para HTTP."""

    name = "failing"

    def __init__(self, error: VisionProviderError):
        self._error = error

    def extract(self, image_path: Path, context: ExtractionContext) -> ProviderExtraction:
        raise self._error


def get_provider(name: str | None = None) -> ScreenshotVisionProvider:
    """Fabrica do provider configurado (env var
    `TENNIS_RADAR_VISION_PROVIDER`, default "anthropic" -- documentado em
    config.py). Suporta "anthropic" e "gemini". "fake"/"failing" so podem
    ser instanciados diretamente (testes), nunca resolvidos por nome."""
    import os

    from . import config as cfg

    resolved = name or os.environ.get(cfg.VISION_PROVIDER_ENV_VAR, cfg.DEFAULT_VISION_PROVIDER)
    if isinstance(resolved, str):
        resolved = resolved.strip().lower()

    if resolved == "anthropic":
        from .anthropic_provider import AnthropicVisionProvider

        return AnthropicVisionProvider()
    elif resolved == "gemini":
        from .gemini_provider import GeminiVisionProvider

        return GeminiVisionProvider()

    raise ProviderUnavailableError(f"Provider de visao desconhecido ou nao suportado em producao: {resolved!r}.")

