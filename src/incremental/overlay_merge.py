"""Merge incremental e escrita atômica do overlay Tennis Abstract (LOTE J, T6).

Substitui o modelo destrutivo "replace do arquivo inteiro":

    novo = existente ∪ entrada        (chave canônica: match_id, player_id)

- só no existente   -> fica (ausência numa coleta nova nunca apaga histórico);
- só na entrada     -> entra;
- nos dois, igual   -> nada muda;
- nos dois, diferente, ou jogadores diferentes para a mesma partida
                    -> fica o existente e o conflito é reportado.

O conflito é decidido por partida (não por linha) para manter a invariante de
exatamente 2 linhas por `match_id`. Entradas já presentes no Sackmann ou com
`tournament_date <= cutoff` são ignoradas e contadas.

Escrita: valida -> grava `.tmp` -> relê e revalida -> copia o arquivo atual
para `versions/matches_{run_id}.parquet` -> `os.replace`. Hash canônico igual
ao atual => não regrava. Nunca escreve em `data/processed/{tour}/`.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.normalization.config import PROCESSED_DIRS
from src.normalization.matches import OUTPUT_COLUMNS

from . import config as cfg

KEY = ["match_id", "player_id"]
_SORT = ["tournament_date", "tourney_id", "match_id", "result", "player_id"]
_SORT_ASC = [True, True, True, False, True]  # "W" antes de "L" dentro da partida

CONFLICT_COLUMNS = ["match_id", "player_id", "reason", "differing_columns", "existing_row", "incoming_row"]


def overlay_path(tour: str) -> Path:
    return cfg.TA_OVERLAY_DIR / tour.lower() / "matches.parquet"


def versions_dir(tour: str) -> Path:
    return overlay_path(tour).parent / "versions"


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def sort_canonical(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values(_SORT, ascending=_SORT_ASC).reset_index(drop=True)[OUTPUT_COLUMNS]


def _as_text(df: pd.DataFrame) -> pd.DataFrame:
    """Representação textual estável (independe de dtype/unidade de tempo)."""
    out = df[OUTPUT_COLUMNS].copy()
    out["tournament_date"] = pd.to_datetime(out["tournament_date"]).dt.strftime("%Y-%m-%d")
    return out.astype(object).where(out.notna(), "<NA>").astype(str)


def canonical_hash(df: pd.DataFrame) -> str:
    text = _as_text(sort_canonical(df)) if not df.empty else pd.DataFrame(columns=OUTPUT_COLUMNS)
    return hashlib.sha256(text.to_csv(index=False).encode("utf-8")).hexdigest()


def validate_overlay_structure(df: pd.DataFrame, tour: str) -> None:
    """Invariantes de qualquer overlay gravável. ValueError antes de escrever."""
    if df.empty:
        raise ValueError(f"overlay {tour}: DataFrame vazio, nada gravado")
    if list(df.columns) != OUTPUT_COLUMNS:
        raise ValueError(
            f"overlay {tour}: schema inválido, esperado OUTPUT_COLUMNS "
            f"({len(OUTPUT_COLUMNS)} colunas), recebido {list(df.columns)[:10]}"
        )
    if df[KEY].isna().any().any():
        raise ValueError(f"overlay {tour}: match_id/player_id nulo")
    if (df["tour"].astype(str) != tour.upper()).any():
        raise ValueError(f"overlay {tour}: linhas de outro tour")
    if df.duplicated(KEY).any():
        raise ValueError(f"overlay {tour}: (match_id, player_id) duplicado")
    per_match = df.groupby("match_id")["player_id"].agg(["size", "nunique"])
    bad = per_match[(per_match["size"] != 2) | (per_match["nunique"] != 2)]
    if not bad.empty:
        raise ValueError(
            f"overlay {tour}: partidas sem exatamente 2 linhas com player_ids distintos: "
            f"{list(bad.index[:5])}"
        )


def validate_overlay_content(df: pd.DataFrame, tour: str, cutoff: str, base_match_ids: set[str]) -> None:
    """Estrutura + regras de conteúdo do overlay operacional."""
    validate_overlay_structure(df, tour)
    if (pd.to_datetime(df["tournament_date"]) <= pd.Timestamp(cutoff)).any():
        raise ValueError(f"overlay {tour}: partidas com tournament_date <= cutoff {cutoff}")
    in_base = df["match_id"].isin(base_match_ids)
    if in_base.any():
        raise ValueError(f"overlay {tour}: partidas já presentes no Sackmann: {list(df.loc[in_base, 'match_id'][:5])}")


def read_existing_overlay(tour: str) -> pd.DataFrame | None:
    """Leitura ESTRITA do overlay atual: None se não existir; erro de leitura
    ou schema inválido levanta exceção (nunca tratado como vazio, o que
    permitiria sobrescrever histórico)."""
    path = overlay_path(tour)
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    if list(df.columns) != OUTPUT_COLUMNS:
        raise ValueError(f"overlay {tour} existente em {path} tem schema inválido; merge abortado")
    return df


def load_base_match_ids(tour: str) -> set[str]:
    base = pd.read_parquet(PROCESSED_DIRS[tour.lower()] / "matches.parquet", columns=["match_id"])
    return set(base["match_id"].astype(str))


def _row_json(row: pd.Series | None) -> str | None:
    if row is None:
        return None
    return json.dumps({k: (None if pd.isna(v) else str(v)) for k, v in row.items()}, ensure_ascii=False)


def merge_overlay(
    existing: pd.DataFrame | None,
    incoming: pd.DataFrame,
    base_match_ids: set[str],
    cutoff: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Função pura: não lê nem grava arquivos. Retorna (merged, report)."""
    if list(incoming.columns) != OUTPUT_COLUMNS:
        raise ValueError("entrada do merge fora de OUTPUT_COLUMNS")
    if incoming.duplicated(KEY).any():
        raise ValueError("entrada do merge com (match_id, player_id) duplicado")
    existing = existing if existing is not None else pd.DataFrame(columns=OUTPUT_COLUMNS)

    pre_cutoff = pd.to_datetime(incoming["tournament_date"]) <= pd.Timestamp(cutoff)
    in_base = incoming["match_id"].isin(base_match_ids) & ~pre_cutoff
    candidates = incoming[~pre_cutoff & ~in_base]

    existing_matches = set(existing["match_id"])
    added = candidates[~candidates["match_id"].isin(existing_matches)]
    overlapping = candidates[candidates["match_id"].isin(existing_matches)]

    ex_text = _as_text(existing).set_index(KEY) if not existing.empty else None
    in_text = _as_text(overlapping).set_index(KEY) if not overlapping.empty else None
    ex_rows = existing.set_index(KEY)
    in_rows = overlapping.set_index(KEY)

    conflicts, unchanged = [], 0
    for key in (in_text.index if in_text is not None else []):
        if key not in ex_text.index:
            conflicts.append({
                "match_id": key[0], "player_id": key[1], "reason": "PLAYER_SET_MISMATCH",
                "differing_columns": "", "existing_row": None, "incoming_row": _row_json(in_rows.loc[key]),
            })
            continue
        diff = [c for c in in_text.columns if in_text.at[key, c] != ex_text.at[key, c]]
        if not diff:
            unchanged += 1
            continue
        conflicts.append({
            "match_id": key[0], "player_id": key[1], "reason": "DIFFERENT_VALUES",
            "differing_columns": "|".join(diff),
            "existing_row": _row_json(ex_rows.loc[key]), "incoming_row": _row_json(in_rows.loc[key]),
        })

    frames = [f for f in (existing, added) if not f.empty]
    merged = sort_canonical(pd.concat(frames, ignore_index=True)) if frames else pd.DataFrame(columns=OUTPUT_COLUMNS)

    report = {
        "n_existing_rows": int(len(existing)),
        "n_incoming_rows": int(len(incoming)),
        "n_ignored_pre_cutoff_rows": int(pre_cutoff.sum()),
        "n_ignored_in_sackmann_rows": int(in_base.sum()),
        "n_added_rows": int(len(added)),
        "n_unchanged_rows": unchanged,
        "n_conflict_rows": len(conflicts),
        "n_merged_rows": int(len(merged)),
        "conflicts": pd.DataFrame(conflicts, columns=CONFLICT_COLUMNS),
    }
    return merged, report


def write_overlay_atomic(tour: str, df: pd.DataFrame, run_id: str | None = None) -> dict[str, Any]:
    """Grava `df` como overlay do tour de forma atômica e versionada.

    Recusa (ValueError, sem tocar no arquivo atual) estrutura inválida ou
    qualquer escrita que removeria linhas já existentes."""
    validate_overlay_structure(df, tour)
    run_id = run_id or new_run_id()
    new_df = sort_canonical(df)
    new_hash = canonical_hash(new_df)

    path = overlay_path(tour)
    current = read_existing_overlay(tour)
    previous_hash = canonical_hash(current) if current is not None else None
    result = {"path": path, "written": False, "backup_path": None,
              "content_hash": new_hash, "previous_hash": previous_hash, "run_id": run_id}
    if new_hash == previous_hash:
        return result

    if current is not None:
        current_keys = set(map(tuple, current[KEY].astype(str).values))
        new_keys = set(map(tuple, new_df[KEY].astype(str).values))
        missing = current_keys - new_keys
        if missing:
            raise ValueError(
                f"overlay {tour}: escrita removeria {len(missing)} linha(s) existente(s); "
                f"use o merge incremental (ex.: {sorted(missing)[:3]})"
            )

    tmp = path.with_name(path.name + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        new_df.to_parquet(tmp, index=False)
        reread = pd.read_parquet(tmp)
        validate_overlay_structure(reread, tour)
        if canonical_hash(reread) != new_hash:
            raise ValueError(f"overlay {tour}: conteúdo relido do .tmp difere do esperado")
        if current is not None:
            backup = versions_dir(tour) / f"matches_{run_id}.parquet"
            if backup.exists():
                raise ValueError(f"overlay {tour}: versão {backup.name} já existe")
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)
            result["backup_path"] = backup
        os.replace(tmp, path)
        result["written"] = True
    finally:
        if tmp.exists():
            tmp.unlink()
    return result


def merge_and_save(
    tour: str,
    incoming: pd.DataFrame,
    run_id: str | None = None,
    cutoff: str | None = None,
    base_match_ids: set[str] | None = None,
) -> dict[str, Any]:
    """existente ∪ entrada -> valida -> grava (atômico) se algo mudou."""
    cutoff = cutoff or cfg.TA_BASE_CUTOFF
    if base_match_ids is None:
        base_match_ids = load_base_match_ids(tour)
    existing = read_existing_overlay(tour)
    merged, report = merge_overlay(existing, incoming, base_match_ids, cutoff)
    if merged.empty:
        return {"report": report, "path": overlay_path(tour), "written": False, "backup_path": None,
                "content_hash": None, "previous_hash": None, "run_id": run_id}
    validate_overlay_content(merged, tour, cutoff, base_match_ids)
    return {"report": report, **write_overlay_atomic(tour, merged, run_id)}
