"""Registro pre-jogo imutavel (itens 1, 2, 3, 4, 13). Cada linha de
`forward_predictions.parquet` e uma copia congelada de uma oportunidade ja
classificada pela Fase 10 -- nenhuma probabilidade/odd/edge/classificacao e
recalculada aqui -- somada ao congelamento de versao (item 2).

Uma vez gravada, uma linha NUNCA e sobrescrita: uma nova tentativa de
registrar a MESMA oportunidade (mesmo `prediction_id`) com valores
DIFERENTES em qualquer campo imutavel e REJEITADA (item 1); com valores
IDENTICOS e apenas ignorada (reenvio seguro, mesma convencao ja usada nas
Fases 9/10 para repeticao exata da mesma observacao)."""

from __future__ import annotations

import pandas as pd

from . import config as cfg
from . import ids
from . import versioning

# campos vindos diretamente da oportunidade ja classificada pela Fase 10
# (nunca recalculados aqui).
_PASSTHROUGH_COLUMNS = [
    "tour", "tournament", "match_id", "player", "opponent", "surface_ctx",
    "market", "side", "line",
    "operational_probability", "fair_odds",
    "odd_minima_2pct", "odd_minima_3pct", "odd_minima_5pct", "odd_minima_7_5pct", "odd_minima_10pct",
    "bookmaker", "decimal_odds", "collected_at",
    "implied_probability", "model_edge", "status",
    "classification", "reasons", "alerts", "explanation",
    "sample_quality", "method_selected", "restricted", "restricted_motivo",
    "extreme_probability", "staleness_bucket", "stake_policy",
]
# campos calculados por este modulo (id + congelamento de versao, item 2) --
# `historical_data_cutoff`/`data_staleness_days` sao recalculados "agora"
# (ver versioning.py), NUNCA copiados do valor ja gravado pela Fase 10.
_COMPUTED_COLUMNS = [
    "prediction_id", "registered_at",
    "forward_version_id", "features_version", "calibration_version",
    "rules_version", "git_commit", "historical_data_cutoff", "data_staleness_days",
]
FROZEN_COLUMNS = _PASSTHROUGH_COLUMNS + _COMPUTED_COLUMNS

# item 1: campos que definem a identidade congelada de uma previsao -- uma
# tentativa de registrar o mesmo `prediction_id` com QUALQUER um destes
# diferente e uma tentativa de sobrescrita, rejeitada.
_IMMUTABLE_CHECK_FIELDS = [
    "operational_probability", "fair_odds", "decimal_odds", "model_edge",
    "classification", "sample_quality",
]


def _values_equal(a, b) -> bool:
    try:
        if a is None and b is None:
            return True
        if isinstance(a, float) or isinstance(b, float):
            fa, fb = float(a), float(b)
            if fa != fa and fb != fb:  # NaN == NaN, tratado como "igual"
                return True
            return abs(fa - fb) < 1e-9
        return a == b
    except (TypeError, ValueError):
        return a == b


def _build_frozen_row(row: dict, registered_at: str) -> dict:
    prediction_id = ids.make_prediction_id(
        row.get("bookmaker"), row.get("tour"), row.get("match_id"),
        row.get("market"), row.get("player"), row.get("side"), row.get("line"),
    )
    frozen = {col: row.get(col) for col in _PASSTHROUGH_COLUMNS}
    frozen["prediction_id"] = prediction_id
    frozen["registered_at"] = registered_at
    frozen.update(versioning.current_version_stamp(row.get("tour")))
    return frozen


def register_predictions(opportunities: pd.DataFrame, registered_at: str | None = None) -> dict:
    """item 4: registra TODAS as linhas recebidas, qualquer classificacao
    (o chamador decide o escopo via
    `inputs.load_opportunities_for_registration`)."""

    registered_at = registered_at or pd.Timestamp.now("UTC").isoformat()

    if opportunities.empty:
        return {
            "added": pd.DataFrame(columns=FROZEN_COLUMNS),
            "skipped_duplicates": [], "rejected_overwrite_attempts": [],
            "total_ledger": pd.DataFrame(columns=FROZEN_COLUMNS),
        }

    existing = (
        pd.read_parquet(cfg.FORWARD_PREDICTIONS_PATH)
        if cfg.FORWARD_PREDICTIONS_PATH.exists() else pd.DataFrame(columns=FROZEN_COLUMNS)
    )
    existing_by_id = (
        {r["prediction_id"]: r for r in existing.to_dict(orient="records")} if not existing.empty else {}
    )

    added, skipped, rejected, seen_in_batch = [], [], [], {}

    for row in opportunities.to_dict(orient="records"):
        frozen = _build_frozen_row(row, registered_at)
        pid = frozen["prediction_id"]

        prior = existing_by_id.get(pid) or seen_in_batch.get(pid)
        if prior is not None:
            changed = [f for f in _IMMUTABLE_CHECK_FIELDS if not _values_equal(prior.get(f), frozen.get(f))]
            if changed:
                rejected.append({
                    "prediction_id": pid, "changed_fields": changed,
                    "reason": (
                        f"previsao ja registrada com valores diferentes em {changed} -- "
                        "registro imutavel (item 1)"
                    ),
                })
            else:
                skipped.append(pid)
            continue

        seen_in_batch[pid] = frozen
        added.append(frozen)

    if added:
        added_df = pd.DataFrame(added)
        combined = pd.concat([existing, added_df], ignore_index=True) if not existing.empty else added_df
        cfg.PHASE11_DIR.mkdir(parents=True, exist_ok=True)
        combined.to_parquet(cfg.FORWARD_PREDICTIONS_PATH, index=False)
    else:
        combined = existing

    return {
        "added": pd.DataFrame(added, columns=FROZEN_COLUMNS) if added else pd.DataFrame(columns=FROZEN_COLUMNS),
        "skipped_duplicates": skipped,
        "rejected_overwrite_attempts": rejected,
        "total_ledger": combined,
    }


def load_predictions() -> pd.DataFrame:
    return (
        pd.read_parquet(cfg.FORWARD_PREDICTIONS_PATH)
        if cfg.FORWARD_PREDICTIONS_PATH.exists() else pd.DataFrame(columns=FROZEN_COLUMNS)
    )
