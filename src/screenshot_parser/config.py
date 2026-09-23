"""Configuracao do armazenamento/leitura de prints da casa de apostas.

LOTE E cobriu so a camada de upload/armazenamento/auditoria da imagem
original. LOTE F (docs/018_PWA_ARQUITETURA.md secao 7) acrescenta a
leitura do conteudo (mapping.py/validator.py/providers.py/extractor.py):
so os 2 mercados pedidos (ACES, GAMES_TOTALS) sao suportados; nenhum
outro tipo de aba nem mercado combinado.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PROJECT_ROOT / "data"
DATA_RAW = DATA_ROOT / "raw"
DATA_PROCESSED = DATA_ROOT / "processed"

SCREENSHOTS_RAW_DIR = DATA_RAW / "bookmaker_screenshots"

# LOTE F: extracao bruta da IA (auditoria, nunca reescrita) e a extracao
# confirmada pelo usuario (docs/018 secao "PERSISTENCIA" do LOTE F) --
# dois artefatos separados, como pedido explicitamente.
EXTRACTED_RAW_DIR = DATA_RAW / "bookmaker_extracted"
CONFIRMED_DIR = DATA_PROCESSED / "bookmaker_confirmed"

DEFAULT_BOOKMAKER = "Betano"


class TabType(str, Enum):
    ACES = "ACES"
    GAMES_TOTALS = "GAMES_TOTALS"


# Pillow devolve esses nomes de formato ao abrir a imagem de verdade --
# nunca a extensao do nome do arquivo nem o Content-Type declarado pelo
# cliente (nao confiar so na extensao, item de seguranca do pedido).
ALLOWED_IMAGE_FORMATS: dict[str, tuple[str, str]] = {
    "PNG": ("png", "image/png"),
    "JPEG": ("jpg", "image/jpeg"),
    "WEBP": ("webp", "image/webp"),
}

# Sugestao explicita do pedido (secao SEGURANCA).
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024

# ---------------------------------------------------------------------------
# LOTE F -- mercados suportados, lados e status de validacao
# ---------------------------------------------------------------------------

# Escopo exato do pedido: so estes 3 mercados (aces por jogador, total de
# aces da partida, total de games da partida). Nunca ampliar para duplas
# faltas/handicap/sets/combinados aqui, mesmo que apareçam no print.
SUPPORTED_MARKETS = ("aces_player", "total_aces_match", "total_games")

# A casa mostra "Mais de"/"Menos de" -- preservado tal como o pedido
# especificou nos exemplos (Over/Under capitalizados), deliberadamente
# distinto do "over"/"under" minusculo usado em src/odds (Fase 9): esta
# camada audita o texto exibido pela casa, nao e ainda uma observacao de
# odd da Fase 9 (esse mapeamento fica para um lote futuro, fora de escopo
# aqui -- o pedido probe explicitamente chamar record_odds/decision).
SIDES = ("Over", "Under")

# Criterio TECNICO (nao um limiar de negocio arbitrario, conforme pedido):
# AUTO_VALIDATED = todas as leituras passaram por todas as checagens sem
# gerar nenhum warning. NEEDS_CONFIRMATION = pelo menos um warning em
# qualquer leitura, ou nenhum mercado foi extraido.
STATUS_AUTO_VALIDATED = "AUTO_VALIDATED"
STATUS_NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"

EXTRACTION_WARNING_NO_MARKETS_FOUND = "NENHUM_MERCADO_ENCONTRADO"

CONFIRMED_BY_DEFAULT = "local_user"

# ---------------------------------------------------------------------------
# LOTE F -- provider de visao (desacoplado, configuravel por env var)
# ---------------------------------------------------------------------------

VISION_PROVIDER_ENV_VAR = "TENNIS_RADAR_VISION_PROVIDER"
DEFAULT_VISION_PROVIDER = "anthropic"

VISION_MODEL_ENV_VAR = "TENNIS_RADAR_VISION_MODEL"
VISION_TIMEOUT_ENV_VAR = "TENNIS_RADAR_VISION_TIMEOUT_SECONDS"
DEFAULT_VISION_TIMEOUT_SECONDS = 60

ANTHROPIC_API_KEY_ENV_VAR = "ANTHROPIC_API_KEY"
ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"
