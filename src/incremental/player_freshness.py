"""Freshness por jogador da agenda (LOTE J, T7).

Chave: `player_id` (nunca nome). O status vem do resultado da coleta DAQUELE
jogador (fetch -> identidade T4 -> adapter T5 -> merge T6), não de aparições
no overlay: ser adversário na página de outro jogador nunca gera UPDATED.

Ordem de decisão (a primeira que casar):

    identidade não confiável (unresolved/fuzzy_review) -> BASE_ONLY  IDENTITY_UNRESOLVED
    sem coleta para o player_id                        -> BASE_ONLY  NOT_COLLECTED
    fetch 429/403/timeout/rede/HTTP                    -> SOURCE_UNAVAILABLE  <código>
    identidade NO_PLAYER_DATA (ou página sem dados)    -> BASE_ONLY  NO_PLAYER_DATA
    identidade MISMATCH                                -> BASE_ONLY  SLUG_IDENTITY_MISMATCH
    identidade INSUFFICIENT_EVIDENCE                   -> BASE_ONLY  IDENTITY_INSUFFICIENT_EVIDENCE
    identidade ausente/outra                           -> BASE_ONLY  IDENTITY_NOT_VERIFIED
    VERIFIED, 0 partidas pós-cutoff                    -> UPDATED    NO_MATCHES_SINCE_CUTOFF
    VERIFIED, adapter não processou o jogador          -> PARTIAL    NOT_PROCESSED
    VERIFIED, contagem do adapter != payload           -> PARTIAL    INCONSISTENT_PROCESSING:...
    VERIFIED, válidas = 0 e rejeitadas > 0             -> PARTIAL    ALL_REJECTED:<motivos>
    VERIFIED, válidas > 0 e rejeitadas > 0             -> PARTIAL    SOME_REJECTED:<motivos>
    VERIFIED, conflito no merge                        -> PARTIAL    MERGE_CONFLICT
    VERIFIED, nada incorporado nem já presente         -> PARTIAL    NOT_INCORPORATED
    VERIFIED, tudo válido e incorporado/presente       -> UPDATED    NEW_MATCHES

Datas (naive; `verified_through` em UTC):
- `sackmann_last`: última data do player_id na base (vem de agenda_players);
- `overlay_last`: última `tournament_date` do player_id no overlay efetivo;
- `verified_through`: `fetched_at` da consulta/cache válido, só com fetch OK e
  identidade VERIFIED (a última partida e o instante verificado são distintos);
- `effective_data_cutoff`: UPDATED -> verified_through; demais ->
  max(sackmann_last, overlay_last). Identidade não confiável -> NA.

Contagens ficam NA quando não se aplicam (ex.: identidade não verificada),
nunca 0 inventado. Função pura: sem rede e sem leitura de arquivos.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from . import config as cfg

UPDATED = "UPDATED"
PARTIAL = "PARTIAL"
BASE_ONLY = "BASE_ONLY"
SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
FRESHNESS_STATUSES = (UPDATED, PARTIAL, BASE_ONLY, SOURCE_UNAVAILABLE)

TRUSTED_METHODS = ("exact", "alias")
# duplicata entre páginas coletadas não é perda de cobertura (a partida entrou pela outra página)
NON_COVERAGE_REJECTIONS = ("DUPLICATE_CROSS_PLAYER",)

_FETCH_OK = ("PAGE_OK",)
_FETCH_NO_DATA = ("EMPTY_PAGE", "NO_PLAYER_DATA")
_FETCH_ERROR_CODES = {"HTTP_429": "HTTP_429", "HTTP_403": "HTTP_403", "HTTP_ERROR": "SOURCE_ERROR"}

FRESHNESS_COLUMNS = [
    "player_id", "player_name", "tour", "resolution_method", "trusted_identity",
    "sackmann_last", "overlay_last", "verified_through", "effective_data_cutoff",
    "freshness_status", "reason",
    "identity_status", "comparable_matches", "overlap_matches", "overlap_ratio",
    "n_ta_post_cutoff", "n_valid", "n_rejected", "n_incorporated_new", "n_already_present",
    "fetched_at", "cache_hit", "source_hash", "error_code", "retry_after",
    # extras (diagnóstico)
    "slug", "fetch_status", "n_merge_conflict",
]
_DATE_COLUMNS = ["sackmann_last", "overlay_last", "verified_through", "effective_data_cutoff"]
_INT_COLUMNS = ["comparable_matches", "overlap_matches", "n_ta_post_cutoff", "n_valid", "n_rejected",
                "n_incorporated_new", "n_already_present", "n_merge_conflict"]


def _ts(value: Any) -> pd.Timestamp | None:
    """Timestamp naive (UTC quando vier com fuso) ou None."""
    if value is None or (not isinstance(value, str) and pd.isna(value)) or value == "":
        return None
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts


def overlay_last_by_player(overlay_df: pd.DataFrame | None) -> dict[str, pd.Timestamp]:
    """{player_id: última tournament_date} no overlay efetivo (linhas do próprio player_id)."""
    if overlay_df is None or overlay_df.empty:
        return {}
    dates = pd.to_datetime(overlay_df["tournament_date"])
    return dates.groupby(overlay_df["player_id"].astype(str)).max().to_dict()


def incorporation_by_player(
    incoming: pd.DataFrame,
    existing: pd.DataFrame | None,
    merged: pd.DataFrame,
    conflicts: pd.DataFrame | None = None,
) -> dict[str, dict[str, int]]:
    """Contagens por player_id das linhas `incoming` (transformed_df do adapter)
    após o merge T6: nova (entrou agora), já presente (já estava no overlay) ou
    em conflito (T6 manteve o existente). Linhas ignoradas pelo merge (pré-cutoff
    ou já no Sackmann) não entram em nenhuma contagem."""
    if incoming is None or incoming.empty:
        return {}

    def _keys(df: pd.DataFrame | None) -> set[tuple[str, str]]:
        if df is None or df.empty:
            return set()
        return set(zip(df["match_id"].astype(str), df["player_id"].astype(str)))

    existing_keys, merged_keys, conflict_keys = _keys(existing), _keys(merged), _keys(conflicts)
    out: dict[str, dict[str, int]] = {}
    for key in zip(incoming["match_id"].astype(str), incoming["player_id"].astype(str)):
        c = out.setdefault(key[1], {"n_incorporated_new": 0, "n_already_present": 0, "n_merge_conflict": 0})
        if key in conflict_keys:
            c["n_merge_conflict"] += 1
        elif key in existing_keys:
            c["n_already_present"] += 1
        elif key in merged_keys:
            c["n_incorporated_new"] += 1
    return out


def _format_reasons(reasons: Mapping[str, int]) -> str:
    return ";".join(f"{k}={v}" for k, v in sorted(reasons.items()))


def _post_cutoff_count(matches: list[dict], cutoff_int: int) -> int:
    n = 0
    for m in matches:
        d = str(m.get("date") or "").strip()
        if d.isdigit() and int(d) > cutoff_int:
            n += 1
    return n


def _classify(
    agenda_row: Mapping[str, Any],
    collection: Mapping[str, Any] | None,
    identity: Mapping[str, Any] | None,
    stats: Mapping[str, Any] | None,
    incorporation: Mapping[str, int] | None,
    overlay_last: pd.Timestamp | None,
    cutoff_int: int,
) -> dict[str, Any]:
    pid = agenda_row.get("player_id")
    pid = None if pid is None or pd.isna(pid) else str(pid)
    method = agenda_row.get("resolution_method")
    trusted = bool(pid) and method in TRUSTED_METHODS
    sackmann_last = _ts(agenda_row.get("sackmann_last"))

    row: dict[str, Any] = {c: None for c in FRESHNESS_COLUMNS}
    row.update(player_id=pid, player_name=agenda_row.get("player_name"), tour=agenda_row.get("tour"),
               resolution_method=method, trusted_identity=trusted, sackmann_last=sackmann_last)

    def _done(status: str, reason: str, verified_through: pd.Timestamp | None = None) -> dict[str, Any]:
        row.update(freshness_status=status, reason=reason, verified_through=verified_through)
        if status == UPDATED:
            row["effective_data_cutoff"] = verified_through
        elif trusted:
            known = [d for d in (sackmann_last, row["overlay_last"]) if d is not None]
            row["effective_data_cutoff"] = max(known) if known else None
        return row

    if not trusted:
        return _done(BASE_ONLY, "IDENTITY_UNRESOLVED")

    row["overlay_last"] = overlay_last
    if collection is None:
        return _done(BASE_ONLY, "NOT_COLLECTED")

    fetch_status = collection.get("fetch_status")
    p_info = collection.get("player") or {}
    row.update(fetch_status=fetch_status, slug=p_info.get("slug"),
               fetched_at=_ts(collection.get("fetched_at")), cache_hit=collection.get("cache_hit"),
               source_hash=collection.get("hash") or None, retry_after=collection.get("retry_after"))

    if fetch_status == "NETWORK_ERROR":
        row["error_code"] = collection.get("error_code") or "NETWORK_ERROR"
        return _done(SOURCE_UNAVAILABLE, row["error_code"])
    if fetch_status in _FETCH_ERROR_CODES:
        row["error_code"] = _FETCH_ERROR_CODES[fetch_status]
        return _done(SOURCE_UNAVAILABLE, row["error_code"])
    if fetch_status not in _FETCH_OK + _FETCH_NO_DATA:
        row["error_code"] = "SOURCE_ERROR"
        return _done(SOURCE_UNAVAILABLE, f"SOURCE_ERROR:{fetch_status or 'UNKNOWN_FETCH_STATUS'}")

    identity = identity or {}
    if identity and identity.get("player_id") not in (None, pid):
        raise ValueError(f"identidade de {identity.get('player_id')} associada a {pid}")
    id_status = identity.get("identity_status")
    row.update(identity_status=id_status, comparable_matches=identity.get("comparable_matches"),
               overlap_matches=identity.get("overlap_matches"), overlap_ratio=identity.get("overlap_ratio"))
    if fetch_status in _FETCH_NO_DATA or id_status == "NO_PLAYER_DATA":
        return _done(BASE_ONLY, "NO_PLAYER_DATA")

    n_post = _post_cutoff_count(collection.get("matches") or [], cutoff_int)
    row["n_ta_post_cutoff"] = n_post
    if id_status == "MISMATCH":
        return _done(BASE_ONLY, "SLUG_IDENTITY_MISMATCH")
    if id_status == "INSUFFICIENT_EVIDENCE":
        return _done(BASE_ONLY, "IDENTITY_INSUFFICIENT_EVIDENCE")
    if id_status != "VERIFIED":
        return _done(BASE_ONLY, f"IDENTITY_NOT_VERIFIED:{id_status or 'MISSING'}")

    verified_through = row["fetched_at"]
    if n_post == 0:
        return _done(UPDATED, "NO_MATCHES_SINCE_CUTOFF", verified_through)
    if stats is None:
        return _done(PARTIAL, "NOT_PROCESSED", verified_through)

    if stats.get("n_post_cutoff") != n_post:  # adapter rodou sobre outro payload/cutoff
        return _done(PARTIAL, f"INCONSISTENT_PROCESSING:adapter={stats.get('n_post_cutoff')},payload={n_post}",
                     verified_through)
    rejected = {k: v for k, v in (stats.get("rejected_reasons") or {}).items() if k not in NON_COVERAGE_REJECTIONS}
    n_valid = int(stats.get("n_valid", 0)) + int(stats.get("n_duplicate", 0))
    n_rejected = sum(rejected.values())
    inc = incorporation or {"n_incorporated_new": 0, "n_already_present": 0, "n_merge_conflict": 0}
    row.update(n_valid=n_valid, n_rejected=n_rejected, **inc)

    if n_rejected and n_valid == 0:
        return _done(PARTIAL, f"ALL_REJECTED:{_format_reasons(rejected)}", verified_through)
    if n_rejected:
        return _done(PARTIAL, f"SOME_REJECTED:{_format_reasons(rejected)}", verified_through)
    if inc["n_merge_conflict"]:
        return _done(PARTIAL, "MERGE_CONFLICT", verified_through)
    if inc["n_incorporated_new"] + inc["n_already_present"] == 0:
        return _done(PARTIAL, "NOT_INCORPORATED", verified_through)
    return _done(UPDATED, "NEW_MATCHES", verified_through)


def build_player_freshness(
    agenda: pd.DataFrame,
    collections: Mapping[str, Mapping[str, Any]] | None = None,
    per_player: Mapping[str, Mapping[str, Any]] | None = None,
    incorporation: Mapping[str, Mapping[str, int]] | None = None,
    overlay_df: pd.DataFrame | None = None,
    identities: Mapping[str, Mapping[str, Any]] | None = None,
    cutoff: str | None = None,
) -> pd.DataFrame:
    """Uma linha por linha da agenda (`agenda_players`), na ordem canônica.

    - `collections`: {player_id: payload de `fetch_player_page`} (pode trazer `identity`);
    - `identities`: {player_id: resultado de `verify_identity`} (prevalece sobre o do payload);
    - `per_player`: `process_tennis_abstract_matches(...)["per_player"]`;
    - `incorporation`: `incorporation_by_player(...)` do merge T6;
    - `overlay_df`: overlay efetivo após o merge (para `overlay_last`)."""
    collections, per_player = collections or {}, per_player or {}
    incorporation, identities = incorporation or {}, identities or {}
    cutoff_int = int((cutoff or cfg.TA_BASE_CUTOFF).replace("-", ""))
    last_overlay = overlay_last_by_player(overlay_df)

    rows = []
    for rec in agenda.to_dict("records"):
        pid = rec.get("player_id")
        pid = None if pid is None or pd.isna(pid) else str(pid)
        collection = collections.get(pid) if pid else None
        identity = identities.get(pid) if pid else None
        if identity is None and collection is not None:
            identity = collection.get("identity")
        rows.append(_classify(
            rec, collection, identity,
            per_player.get(pid) if pid else None,
            incorporation.get(pid) if pid else None,
            _ts(last_overlay.get(pid)) if pid else None,
            cutoff_int,
        ))

    out = pd.DataFrame(rows, columns=FRESHNESS_COLUMNS)
    for c in _DATE_COLUMNS + ["fetched_at"]:
        out[c] = pd.to_datetime(out[c])
    for c in _INT_COLUMNS:
        out[c] = pd.array(out[c], dtype="Int64")
    out["overlap_ratio"] = pd.array(out["overlap_ratio"], dtype="Float64")
    out["trusted_identity"] = out["trusted_identity"].astype(bool)
    missing = out["freshness_status"].isna() | out["reason"].isna()
    if missing.any():
        raise AssertionError("jogador da agenda sem freshness_status/reason")
    return out.sort_values(
        ["tour", "player_id", "player_name", "resolution_method"], na_position="last", kind="mergesort",
    ).reset_index(drop=True)
