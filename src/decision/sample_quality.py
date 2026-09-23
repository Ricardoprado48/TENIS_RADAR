"""Classificacao objetiva de qualidade de amostra (item 5):
`sample_quality = LOW | MEDIUM | HIGH`.

Combina 4 sinais, todos ja calculados em fases anteriores (nada e
recalculado aqui, apenas comparado contra thresholds fixados em
`config.py` antes de olhar os resultados): numero de partidas anteriores,
service points acumulados, return points acumulados, e historico na mesma
superficie -- mais uma checagem de consistencia (nenhuma flag de baixa
confianca ja herdada das Fases 7/8).

Dado ausente (`NaN`/`None`) nunca e tratado como suficiente -- cai
diretamente para LOW (CLAUDE.md #23: nunca inventar)."""

from __future__ import annotations

import math

from . import config as cfg


def _is_missing(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def classify_sample_quality(
    prior_matches_career,
    prior_service_points_career,
    prior_return_points_career,
    surface_prior_matches,
    feature_consistent: bool,
) -> str:
    values = [
        prior_matches_career, prior_service_points_career,
        prior_return_points_career, surface_prior_matches,
    ]
    if any(_is_missing(v) for v in values):
        return cfg.SAMPLE_QUALITY_LOW

    if not feature_consistent:
        return cfg.SAMPLE_QUALITY_LOW

    t = cfg.SAMPLE_QUALITY_THRESHOLDS
    if (
        prior_matches_career >= t["high_min_matches"]
        and prior_service_points_career >= t["high_min_service_points"]
        and prior_return_points_career >= t["high_min_return_points"]
        and surface_prior_matches >= t["high_min_surface_matches"]
    ):
        return cfg.SAMPLE_QUALITY_HIGH

    if (
        prior_matches_career >= t["medium_min_matches"]
        and prior_service_points_career >= t["medium_min_service_points"]
        and prior_return_points_career >= t["medium_min_return_points"]
    ):
        return cfg.SAMPLE_QUALITY_MEDIUM

    return cfg.SAMPLE_QUALITY_LOW
