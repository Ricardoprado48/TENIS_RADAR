"""Testes de freshness por jogador (LOTE J, T7).

Sintéticos: sem rede (urlopen bloqueado), sem leitura de cache/overlay/base
reais para as decisões; a fixture de módulo garante que cache TA, overlays
reais e base Sackmann ficam intactos."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest import mock

import pandas as pd
import pytest

from src.incremental import config as inc_cfg
from src.incremental import player_freshness as pf
from src.incremental import ta_identity as ti
from src.incremental.agenda_players import AGENDA_PLAYER_COLUMNS
from src.incremental.overlay_merge import merge_overlay
from src.incremental.tennis_abstract_adapter import AcceptancePolicy, process_tennis_abstract_matches
from src.incremental.tennis_abstract_source import MATCHHEAD_COLUMNS, HttpResponse, TennisAbstractSource
from src.normalization.config import PROCESSED_DIRS

CUTOFF = "2026-05-25"
FETCHED = "2026-09-24T18:00:00+00:00"
FETCHED_TS = pd.Timestamp("2026-09-24 18:00:00")
SACK_LAST = pd.Timestamp("2026-05-18")
A, B, C = "ATP-900001", "ATP-900002", "ATP-900003"

REAL_PATHS = [
    inc_cfg.TA_OVERLAY_DIR / "atp" / "matches.parquet",
    inc_cfg.TA_OVERLAY_DIR / "wta" / "matches.parquet",
    PROCESSED_DIRS["atp"] / "matches.parquet",
    PROCESSED_DIRS["wta"] / "matches.parquet",
]


def _state(path: Path):
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


def _cache_listing():
    d = inc_cfg.TA_CACHE_DIR
    return sorted((str(p), p.stat().st_mtime_ns) for p in d.rglob("*")) if d.exists() else []


@pytest.fixture(scope="module", autouse=True)
def real_files_untouched():
    before = ({p: _state(p) for p in REAL_PATHS}, _cache_listing())
    yield
    after = ({p: _state(p) for p in REAL_PATHS}, _cache_listing())
    assert after == before, "suíte alterou cache TA, overlay real ou base Sackmann"


@pytest.fixture(autouse=True)
def no_network():
    with mock.patch("urllib.request.urlopen", side_effect=AssertionError("rede real proibida nos testes")):
        yield


# --- construtores ---------------------------------------------------------------

def _agenda(*rows) -> pd.DataFrame:
    """rows: (player_id, name, method[, sackmann_last])."""
    recs = []
    for r in rows:
        pid, name, method = r[:3]
        recs.append({
            "player_id": pid, "player_name": name, "tour": "ATP", "hand": "R", "dob": None,
            "resolution_method": method, "resolution_methods": method,
            "trusted": method in ("exact", "alias"), "raw_names": name, "n_agenda_matches": 1,
            "sackmann_last": r[3] if len(r) > 3 else (SACK_LAST if pid else pd.NaT),
        })
    return pd.DataFrame(recs, columns=AGENDA_PLAYER_COLUMNS)


def _m(date: str = "20260610") -> dict:
    return {"date": date, "matchid": "x"}


def _collection(pid: str, fetch_status: str = "PAGE_OK", matches=None, identity: str | None = "VERIFIED",
                **extra) -> dict:
    col = {"player": {"player_id": pid, "slug": "Slug", "tour": "ATP"}, "fetch_status": fetch_status,
           "http_status": 200, "retry_after": None, "fetched_at": FETCHED, "cache_hit": False,
           "hash": "abc", "matches": matches if matches is not None else [], "error": None, "error_code": None}
    col.update(extra)
    if identity is not None:
        col["identity"] = {"player_id": pid, "identity_status": identity, "comparable_matches": 10,
                           "overlap_matches": 10 if identity == "VERIFIED" else 2,
                           "overlap_ratio": 1.0 if identity == "VERIFIED" else 0.2}
    return col


def _stats(n_post, n_valid, rejected=None, n_dup=0) -> dict:
    return {"n_post_cutoff": n_post, "n_valid": n_valid, "n_duplicate": n_dup,
            "rejected_reasons": rejected or {}}


def _one(agenda_row, collection=None, stats=None, inc=None, overlay_df=None) -> pd.Series:
    pid = agenda_row[0]
    out = pf.build_player_freshness(
        _agenda(agenda_row),
        collections={pid: collection} if collection else None,
        per_player={pid: stats} if stats else None,
        incorporation={pid: inc} if inc else None,
        overlay_df=overlay_df, cutoff=CUTOFF,
    )
    assert len(out) == 1
    return out.iloc[0]


def _overlay(rows) -> pd.DataFrame:
    """rows: (match_id, player_id, date)."""
    return pd.DataFrame(rows, columns=["match_id", "player_id", "tournament_date"]).assign(
        tournament_date=lambda d: pd.to_datetime(d["tournament_date"]))


NEW = {"n_incorporated_new": 2, "n_already_present": 0, "n_merge_conflict": 0}


# --- casos A-F -------------------------------------------------------------------

def test_01_verified_new_matches_updated():
    r = _one((A, "Aa", "exact"), _collection(A, matches=[_m(), _m("20260620"), _m("20260101")]),
             _stats(2, 2), NEW, _overlay([("M1", A, "2026-06-10"), ("M2", A, "2026-06-20")]))
    assert (r.freshness_status, r.reason) == ("UPDATED", "NEW_MATCHES")
    assert r.n_ta_post_cutoff == 2 and r.n_valid == 2 and r.n_rejected == 0
    assert r.n_incorporated_new == 2 and r.n_already_present == 0
    assert r.overlay_last == pd.Timestamp("2026-06-20")


def test_01b_verified_already_present_is_updated():
    inc = {"n_incorporated_new": 0, "n_already_present": 1, "n_merge_conflict": 0}
    r = _one((A, "Aa", "alias"), _collection(A, matches=[_m()]), _stats(1, 1), inc)
    assert (r.freshness_status, r.reason) == ("UPDATED", "NEW_MATCHES")


def test_02_verified_no_matches_since_cutoff():
    r = _one((A, "Aa", "exact"), _collection(A, matches=[_m("20260101")]))
    assert (r.freshness_status, r.reason) == ("UPDATED", "NO_MATCHES_SINCE_CUTOFF")
    assert r.n_ta_post_cutoff == 0
    assert r.verified_through == FETCHED_TS
    assert r.effective_data_cutoff == FETCHED_TS
    assert pd.isna(r.n_valid)  # adapter não tinha o que processar: NA, não 0 inventado


def test_03_some_rejected_partial():
    r = _one((A, "Aa", "exact"), _collection(A, matches=[_m()] * 3),
             _stats(3, 1, {"INCOMPLETE_STATS:w_ace": 1, "LEVEL_OUT_OF_POLICY:C": 1}), NEW)
    assert r.freshness_status == "PARTIAL"
    assert r.reason == "SOME_REJECTED:INCOMPLETE_STATS:w_ace=1;LEVEL_OUT_OF_POLICY:C=1"
    assert (r.n_valid, r.n_rejected) == (1, 2)


def test_04_all_rejected_partial():
    r = _one((A, "Aa", "exact"), _collection(A, matches=[_m()] * 2), _stats(2, 0, {"ROUND_OUT_OF_POLICY:Q1": 2}))
    assert (r.freshness_status, r.reason) == ("PARTIAL", "ALL_REJECTED:ROUND_OUT_OF_POLICY:Q1=2")
    assert (r.n_valid, r.n_rejected) == (0, 2)


def test_cross_player_duplicate_is_not_a_rejection():
    r = _one((A, "Aa", "exact"), _collection(A, matches=[_m()]),
             _stats(1, 0, {"DUPLICATE_CROSS_PLAYER": 1}, n_dup=1),
             {"n_incorporated_new": 1, "n_already_present": 0, "n_merge_conflict": 0})
    assert (r.freshness_status, r.reason) == ("UPDATED", "NEW_MATCHES")
    assert (r.n_valid, r.n_rejected) == (1, 0)


@pytest.mark.parametrize("fetch_status,extra,reason", [
    ("HTTP_429", {"http_status": 429, "retry_after": "10"}, "HTTP_429"),
    ("HTTP_403", {"http_status": 403}, "HTTP_403"),
    ("NETWORK_ERROR", {"http_status": None, "error_code": "TIMEOUT"}, "TIMEOUT"),
    ("NETWORK_ERROR", {"http_status": None, "error_code": "NETWORK_ERROR"}, "NETWORK_ERROR"),
    ("HTTP_ERROR", {"http_status": 500}, "SOURCE_ERROR"),
])
def test_05_06_07_source_unavailable(fetch_status, extra, reason):
    ov = _overlay([("M1", A, "2026-06-10")])
    r = _one((A, "Aa", "exact"), _collection(A, fetch_status, identity="FETCH_FAILED", **extra), overlay_df=ov)
    assert (r.freshness_status, r.reason, r.error_code) == ("SOURCE_UNAVAILABLE", reason, reason)
    assert pd.isna(r.verified_through)
    assert r.effective_data_cutoff == pd.Timestamp("2026-06-10")  # freshness histórica preservada
    if fetch_status == "HTTP_429":
        assert r.retry_after == "10"


def test_08_no_player_data_base_only():
    for fetch_status, identity in (("NO_PLAYER_DATA", "NO_PLAYER_DATA"), ("EMPTY_PAGE", "NO_PLAYER_DATA")):
        r = _one((A, "Aa", "exact"), _collection(A, fetch_status, identity=identity))
        assert (r.freshness_status, r.reason) == ("BASE_ONLY", "NO_PLAYER_DATA")
        assert pd.isna(r.verified_through) and pd.isna(r.n_ta_post_cutoff)


def test_09_mismatch_base_only():
    r = _one((A, "Aa", "exact"), _collection(A, matches=[_m()], identity="MISMATCH"), _stats(1, 0))
    assert (r.freshness_status, r.reason) == ("BASE_ONLY", "SLUG_IDENTITY_MISMATCH")
    assert pd.isna(r.n_incorporated_new) and pd.isna(r.verified_through)


def test_10_insufficient_evidence_is_not_mismatch():
    r = _one((A, "Aa", "exact"), _collection(A, matches=[_m()], identity="INSUFFICIENT_EVIDENCE"))
    assert (r.freshness_status, r.reason) == ("BASE_ONLY", "IDENTITY_INSUFFICIENT_EVIDENCE")
    assert r.identity_status == "INSUFFICIENT_EVIDENCE"
    assert r.reason != "SLUG_IDENTITY_MISMATCH"


def test_11_unresolved_base_only():
    r = _one((None, "Zzz Nobody", "unresolved", pd.NaT))
    assert (r.freshness_status, r.reason) == ("BASE_ONLY", "IDENTITY_UNRESOLVED")
    assert not r.trusted_identity and pd.isna(r.effective_data_cutoff)


def test_12_fuzzy_review_base_only_even_if_collected():
    r = _one((A, "Iga Swiatec", "fuzzy_review"), _collection(A, matches=[_m()]), _stats(1, 1), NEW,
             _overlay([("M1", A, "2026-06-10")]))
    assert (r.freshness_status, r.reason) == ("BASE_ONLY", "IDENTITY_UNRESOLVED")
    assert pd.isna(r.overlay_last) and pd.isna(r.effective_data_cutoff)


def test_identity_missing_is_not_verified():
    r = _one((A, "Aa", "exact"), _collection(A, matches=[_m()], identity=None))
    assert (r.freshness_status, r.reason) == ("BASE_ONLY", "IDENTITY_NOT_VERIFIED:MISSING")


def test_verified_but_not_incorporated_or_conflict_is_partial():
    r = _one((A, "Aa", "exact"), _collection(A, matches=[_m()]), _stats(1, 1))
    assert (r.freshness_status, r.reason) == ("PARTIAL", "NOT_INCORPORATED")
    r = _one((A, "Aa", "exact"), _collection(A, matches=[_m()]), _stats(1, 1),
             {"n_incorporated_new": 0, "n_already_present": 1, "n_merge_conflict": 1})
    assert (r.freshness_status, r.reason) == ("PARTIAL", "MERGE_CONFLICT")
    r = _one((A, "Aa", "exact"), _collection(A, matches=[_m()]))  # sem per_player
    assert (r.freshness_status, r.reason) == ("PARTIAL", "NOT_PROCESSED")


# --- regra do adversário (fim a fim, adapter + merge reais, sem rede) -----------

POLICY = AcceptancePolicy(levels=frozenset({"A"}), rounds=frozenset({"F", "SF"}))
PLAYERS = pd.DataFrame({
    "player_id": [A, B, C], "player_id_raw": ["900001", "900002", "900003"],
    "name": ["Aaa Alpha", "Bbb Beta", "Ccc Gamma"], "name_first": ["Aaa", "Bbb", "Ccc"],
    "name_last": ["Alpha", "Beta", "Gamma"], "hand": ["R", "L", "R"],
})


def _ta_row(matchid, date, opp, **kw):
    row = {c: "" for c in MATCHHEAD_COLUMNS}
    row.update({"date": date, "tourn": "Test", "surf": "Hard", "level": "A", "wl": "W", "round": "F",
                "score": "6-4 6-4", "max": "3", "opp": opp, "matchid": matchid, "time": "90",
                "aces": "5", "dfs": "1", "pts": "50", "firsts": "30", "fwon": "25", "swon": "10",
                "games": "8", "saved": "1", "chances": "2", "oaces": "3", "odfs": "2", "opts": "55",
                "ofirsts": "33", "ofwon": "22", "oswon": "9", "ogames": "8", "osaved": "3", "ochances": "5"})
    row.update(kw)
    return [row[c] for c in MATCHHEAD_COLUMNS]


def _html(name, rows):
    return f"<script>var fullname = '{name}'; var matchmx = [{','.join(json.dumps(r) for r in rows)}];</script>"


def test_13_opponent_in_overlay_but_not_collected_is_not_updated(tmp_path):
    # página de A (VERIFIED) traz 1 partida nova contra B; B não é coletado
    base_ids = [f"2025-1-{i}" for i in range(1, 5)]
    rows = [_ta_row(m, "20250610", "Someone") for m in base_ids] + [_ta_row("2026-7-1", "20260610", "Bbb Beta")]
    src = TennisAbstractSource(cache_dir=tmp_path / "cache", delay_seconds=0.0, slug_overrides={})
    with mock.patch.object(src, "_http_get", return_value=HttpResponse(200, _html("Aaa Alpha", rows))):
        payload = src.fetch_player_page(A, "Aaa Alpha", "ATP")
    history = pd.DataFrame(
        [(f"ATP:2025-1:{i}", A, "2025-06-09") for i in range(1, 5)]
        + [("ATP:2026-END:1", "ATP-1", CUTOFF)], columns=["match_id", "player_id", "tournament_date"],
    ).assign(tournament_date=lambda d: pd.to_datetime(d["tournament_date"]))
    identity = ti.verify_identity(A, payload, history, POLICY)
    assert identity["identity_status"] == "VERIFIED"
    payload = ti.attach_identity(payload, identity)

    adapted = process_tennis_abstract_matches([payload], "ATP", cutoff_date=CUTOFF, players_df=PLAYERS,
                                              policy=POLICY)
    merged, report = merge_overlay(None, adapted["transformed_df"], set(), CUTOFF)
    inc = pf.incorporation_by_player(adapted["transformed_df"], None, merged, report["conflicts"])
    assert set(merged["player_id"]) == {A, B}  # B está no overlay, como adversário

    out = pf.build_player_freshness(
        _agenda((A, "Aaa Alpha", "exact"), (B, "Bbb Beta", "exact"), (C, "Ccc Gamma", "exact")),
        collections={A: payload}, per_player=adapted["per_player"], incorporation=inc,
        overlay_df=merged, cutoff=CUTOFF,
    ).set_index("player_id")
    assert (out.loc[A, "freshness_status"], out.loc[A, "reason"]) == ("UPDATED", "NEW_MATCHES")
    assert out.loc[A, "n_incorporated_new"] == 1
    assert (out.loc[B, "freshness_status"], out.loc[B, "reason"]) == ("BASE_ONLY", "NOT_COLLECTED")
    assert out.loc[B, "overlay_last"] == pd.Timestamp("2026-06-10")  # dado existe, mas não é freshness
    assert out.loc[B, "effective_data_cutoff"] == pd.Timestamp("2026-06-10")
    assert pd.isna(out.loc[B, "verified_through"])
    assert (out.loc[C, "freshness_status"], out.loc[C, "reason"]) == ("BASE_ONLY", "NOT_COLLECTED")

    # rodada seguinte: mesma coleta, overlay já contém as linhas -> já presente, continua UPDATED
    merged2, report2 = merge_overlay(merged, adapted["transformed_df"], set(), CUTOFF)
    inc2 = pf.incorporation_by_player(adapted["transformed_df"], merged, merged2, report2["conflicts"])
    assert inc2[A] == {"n_incorporated_new": 0, "n_already_present": 1, "n_merge_conflict": 0}


# --- datas, cobertura, ordem -----------------------------------------------------

def test_14_overlay_last_by_player_id():
    ov = _overlay([("M1", A, "2026-06-01"), ("M1", B, "2026-06-01"), ("M2", A, "2026-07-15"),
                   ("M3", B, "2026-06-20")])
    assert pf.overlay_last_by_player(ov) == {A: pd.Timestamp("2026-07-15"), B: pd.Timestamp("2026-06-20")}
    assert pf.overlay_last_by_player(None) == {}
    assert pf.overlay_last_by_player(pd.DataFrame()) == {}


def test_15_effective_cutoff_updated_is_verified_through():
    ov = _overlay([("M1", A, "2026-06-10")])
    r = _one((A, "Aa", "exact"), _collection(A, matches=[_m()]), _stats(1, 1), NEW, ov)
    assert r.freshness_status == "UPDATED"
    assert r.verified_through == FETCHED_TS == r.effective_data_cutoff
    assert r.overlay_last == pd.Timestamp("2026-06-10")  # última partida != instante verificado


def test_15b_cache_hit_uses_cache_fetched_at():
    r = _one((A, "Aa", "exact"),
             _collection(A, matches=[_m("20260101")], cache_hit=True, fetched_at="2026-09-20T10:00:00+00:00"))
    assert r.cache_hit and r.verified_through == pd.Timestamp("2026-09-20 10:00:00")


def test_16_effective_cutoff_base_only_and_partial():
    ov = _overlay([("M1", A, "2026-06-10")])
    r = _one((A, "Aa", "exact"), _collection(A, matches=[_m()] * 2), _stats(2, 1, {"X": 1}), NEW, ov)
    assert r.freshness_status == "PARTIAL"
    assert r.verified_through == FETCHED_TS
    assert r.effective_data_cutoff == pd.Timestamp("2026-06-10")  # max(sackmann, overlay)
    r = _one((A, "Aa", "exact"), _collection(A, matches=[_m()], identity="MISMATCH"))
    assert r.effective_data_cutoff == SACK_LAST  # sem overlay
    r = _one((A, "Aa", "exact", pd.NaT))
    assert pd.isna(r.effective_data_cutoff)  # nada conhecido: NA, não inventado


def _mixed_agenda():
    return _agenda((B, "Bbb", "exact"), (None, "Zzz", "unresolved", pd.NaT), (A, "Aaa", "alias"),
                   (C, "Ccc", "fuzzy_review"), (None, "Yyy", "unresolved", pd.NaT))


def test_17_18_one_row_per_agenda_player_all_with_status():
    agenda = _mixed_agenda()
    out = pf.build_player_freshness(agenda, collections={A: _collection(A, matches=[])}, cutoff=CUTOFF)
    assert len(out) == len(agenda)
    assert list(out.columns) == pf.FRESHNESS_COLUMNS
    assert out["freshness_status"].isin(pf.FRESHNESS_STATUSES).all()
    assert out["reason"].notna().all()
    assert out["player_id"].dropna().is_unique


def test_19_deterministic_order():
    agenda = _mixed_agenda()
    cols = {A: _collection(A, matches=[]), B: _collection(B, "HTTP_429")}
    a = pf.build_player_freshness(agenda, collections=cols, cutoff=CUTOFF)
    b = pf.build_player_freshness(agenda.iloc[::-1].reset_index(drop=True), collections=cols, cutoff=CUTOFF)
    pd.testing.assert_frame_equal(a, b)
    assert a["player_id"].tolist()[:3] == [A, B, C]


def test_identity_of_other_player_rejected():
    col = _collection(A, matches=[_m()])
    col["identity"]["player_id"] = B
    with pytest.raises(ValueError):
        _one((A, "Aa", "exact"), col)


def test_timeout_classified_by_source(tmp_path):
    import urllib.error

    src = TennisAbstractSource(cache_dir=tmp_path / "cache", delay_seconds=0.0, slug_overrides={})
    with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError(TimeoutError("timed out"))):
        col = src.fetch_player_page(A, "Aaa Alpha", "ATP")
    assert (col["fetch_status"], col["error_code"]) == ("NETWORK_ERROR", "TIMEOUT")
    r = _one((A, "Aa", "exact"), col)
    assert (r.freshness_status, r.reason) == ("SOURCE_UNAVAILABLE", "TIMEOUT")
