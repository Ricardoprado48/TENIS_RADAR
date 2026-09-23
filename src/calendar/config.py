"""Configuracao do LOTE C - fonte de calendario (docs/018_PWA_ARQUITETURA.md
secao 5). Modulo paralelo e desacoplado do radar (Fase 8): nao toca em
src/radar/config.py nem em REQUIRED_RAW_COLUMNS do motor estatistico.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from src.probabilistic.config import TOURS  # noqa: F401 - reaproveitado, nao redefinido

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PROJECT_ROOT / "data"
DATA_RAW = DATA_ROOT / "raw"

CALENDAR_RAW_DIR = DATA_RAW / "calendar"

SURFACES = ["Hard", "Clay", "Grass"]

REQUIRED_RAW_COLUMNS = [
    "tour", "tournament", "round", "player_a_raw", "player_b_raw",
    "surface", "event_datetime_original", "event_timezone",
    "source_url", "collected_at",
]

# Fuso de exibicao da PWA (docs/018 secao 4.2) -- nunca o fuso do torneio.
DISPLAY_TIMEZONE = "America/Sao_Paulo"

# Status da partida (docs/018 secao 5.4) e derivado no backend a partir de
# event_datetime_utc vs. agora -- limiares fixados a priori (nao ha, nesta
# fase, nenhuma fonte de "hora real de termino" da partida), documentados
# aqui em vez de espalhados pelo codigo:
#   - "proximo" comeca quando faltam <= STATUS_PROXIMO_WINDOW para o inicio;
#   - "iniciado" dura ate STATUS_DURACAO_MAXIMA depois do horario marcado
#     (teto generoso para cobrir partidas longas de 5 sets/coisas fora do
#     horario previsto -- nao e um relogio de partida real);
#   - antes disso e "futuro", depois disso e "encerrado".
STATUS_PROXIMO_WINDOW = timedelta(hours=2)
STATUS_DURACAO_MAXIMA = timedelta(hours=5)
