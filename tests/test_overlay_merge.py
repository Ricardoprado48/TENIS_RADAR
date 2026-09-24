"""Testes do merge incremental do overlay (LOTE J, T6).

Todo teste grava somente em `tmp_path` (TA_OVERLAY_DIR redirecionado). A
fixture de módulo garante que overlays reais e a base Sackmann ficam
byte a byte intactos."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from src.incremental import config as inc_cfg
from src.incremental import overlay_merge as om
from src.incremental.overlay import save_overlay_matches
from src.normalization.config import PROCESSED_DIRS
from src.normalization.matches import OUTPUT_COLUMNS

CUTOFF = "2026-05-25"
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


@pytest.fixture(scope="module", autouse=True)
def real_files_untouched():
    before = {p: _state(p) for p in REAL_PATHS}
    yield
    after = {p: _state(p) for p in REAL_PATHS}
    assert after == before, "suíte alterou overlay real ou base Sackmann"


@pytest.fixture(autouse=True)
def overlay_dir(tmp_path, monkeypatch):
    d = tmp_path / "overlay"
    monkeypatch.setattr(inc_cfg, "TA_OVERLAY_DIR", d)
    return d


@pytest.fixture(scope="module")
def template() -> pd.DataFrame:
    base = pd.read_parquet(PROCESSED_DIRS["atp"] / "matches.parquet")
    return base.iloc[0:2][OUTPUT_COLUMNS].reset_index(drop=True)  # 1 partida: W + L


def _match(template, n: int, date: str = "2026-07-01", p1: str = "ATP-900001",
           p2: str = "ATP-900002", aces: int = 5) -> pd.DataFrame:
    df = template.copy()
    df["match_id"] = f"ATP:2026-TEST:{n}"
    df["tourney_id"] = "2026-TEST"
    df["tournament_date"] = pd.Timestamp(date)
    df["player_id"] = [p1, p2]
    df["opponent_id"] = [p2, p1]
    df["aces"] = pd.array([aces, aces + 1], dtype="Int64")
    return df


def _cat(*frames) -> pd.DataFrame:
    return pd.concat(frames, ignore_index=True)


def _save(df, run_id="r1", base_ids=frozenset()):
    return om.merge_and_save("ATP", df, run_id=run_id, cutoff=CUTOFF, base_match_ids=set(base_ids))


def _keys(df):
    return set(zip(df["match_id"], df["player_id"]))


# 1
def test_smaller_collection_never_removes_history(template):
    _save(_cat(_match(template, 1), _match(template, 2), _match(template, 3)), "r1")
    res = _save(_match(template, 3), "r2")
    current = pd.read_parquet(om.overlay_path("ATP"))
    assert len(current) == 6
    assert res["written"] is False  # nada novo: conteúdo idêntico


# 2
def test_identical_row_not_duplicated(template):
    _save(_match(template, 1), "r1")
    res = _save(_cat(_match(template, 1), _match(template, 2)), "r2")
    current = pd.read_parquet(om.overlay_path("ATP"))
    assert len(current) == 4
    assert res["report"]["n_unchanged_rows"] == 2
    assert res["report"]["n_added_rows"] == 2


# 3 + 4
def test_conflict_keeps_existing_and_is_reported(template):
    _save(_match(template, 1, aces=5), "r1")
    res = _save(_match(template, 1, aces=40), "r2")
    current = pd.read_parquet(om.overlay_path("ATP"))
    assert sorted(current["aces"].tolist()) == [5, 6]
    conflicts = res["report"]["conflicts"]
    assert len(conflicts) == 2
    assert list(conflicts.columns) == om.CONFLICT_COLUMNS
    assert set(conflicts["reason"]) == {"DIFFERENT_VALUES"}
    assert conflicts["differing_columns"].str.contains("aces").all()
    assert conflicts["existing_row"].notna().all() and conflicts["incoming_row"].notna().all()


def test_player_set_mismatch_is_conflict_not_third_row(template):
    _save(_match(template, 1, p2="ATP-900002"), "r1")
    res = _save(_match(template, 1, p2="ATP-NEW-SOMEONE"), "r2")
    current = pd.read_parquet(om.overlay_path("ATP"))
    assert len(current) == 2
    assert "PLAYER_SET_MISMATCH" in set(res["report"]["conflicts"]["reason"])


# 5 + 6
def test_duplicate_key_and_incomplete_match_rejected(template):
    dup = _cat(_match(template, 1), _match(template, 1).iloc[[0]])
    with pytest.raises(ValueError):
        _save(dup)
    with pytest.raises(ValueError, match="2 linhas"):
        _save(_match(template, 1).iloc[[0]])
    same_player = _match(template, 1, p1="ATP-900001", p2="ATP-900001")
    with pytest.raises(ValueError):
        _save(same_player)
    assert not om.overlay_path("ATP").exists()


# 7 + 8
def test_validation_failure_leaves_file_and_no_tmp(template):
    _save(_match(template, 1), "r1")
    path = om.overlay_path("ATP")
    before = _state(path)
    with pytest.raises(ValueError):
        _save(_match(template, 2).iloc[[0]], "r2")
    with pytest.raises(ValueError):
        save_overlay_matches("ATP", pd.DataFrame({"col": [1]}))
    assert _state(path) == before
    assert not list(path.parent.glob("*.tmp"))


def test_tmp_removed_when_write_fails_midway(template, monkeypatch):
    _save(_match(template, 1), "r1")
    path = om.overlay_path("ATP")
    before = _state(path)

    def boom(*a, **k):
        raise OSError("falha simulada no replace")

    monkeypatch.setattr(om.os, "replace", boom)
    with pytest.raises(OSError):
        _save(_cat(_match(template, 1), _match(template, 2)), "r2")
    assert _state(path) == before
    assert not list(path.parent.glob("*.tmp"))


# 9
def test_same_hash_not_rewritten(template):
    _save(_match(template, 1), "r1")
    path = om.overlay_path("ATP")
    before = _state(path)
    res = _save(_match(template, 1), "r2")
    assert res["written"] is False
    assert _state(path) == before
    assert not (om.versions_dir("ATP") / "matches_r2.parquet").exists()


def test_backup_version_created_before_replace(template):
    _save(_match(template, 1), "r1")
    assert not om.versions_dir("ATP").exists()  # 1ª escrita: nada a preservar
    res = _save(_match(template, 2), "r2")
    backup = om.versions_dir("ATP") / "matches_r2.parquet"
    assert res["backup_path"] == backup
    assert len(pd.read_parquet(backup)) == 2  # estado anterior ao run r2
    assert len(pd.read_parquet(om.overlay_path("ATP"))) == 4


def test_existing_version_never_overwritten(template):
    _save(_match(template, 1), "r1")
    _save(_match(template, 2), "r2")
    with pytest.raises(ValueError, match="já existe"):
        _save(_match(template, 3), "r2")
    assert len(pd.read_parquet(om.overlay_path("ATP"))) == 4


def test_direct_save_cannot_shrink_existing_overlay(template):
    save_overlay_matches("ATP", _cat(_match(template, 1), _match(template, 2)), run_id="r1")
    with pytest.raises(ValueError, match="removeria"):
        save_overlay_matches("ATP", _match(template, 2), run_id="r2")
    assert len(pd.read_parquet(om.overlay_path("ATP"))) == 4


def test_sackmann_and_pre_cutoff_rows_ignored(template):
    res = _save(
        _cat(_match(template, 1), _match(template, 2, date="2026-05-25"), _match(template, 3)),
        base_ids={"ATP:2026-TEST:3"},
    )
    current = pd.read_parquet(om.overlay_path("ATP"))
    assert set(current["match_id"]) == {"ATP:2026-TEST:1"}
    assert res["report"]["n_ignored_pre_cutoff_rows"] == 2
    assert res["report"]["n_ignored_in_sackmann_rows"] == 2


def test_nothing_valid_to_write_does_not_create_file(template):
    res = _save(_match(template, 1, date="2026-01-01"))
    assert res["written"] is False
    assert not om.overlay_path("ATP").exists()


def test_invalid_existing_overlay_aborts_merge(template):
    path = om.overlay_path("ATP")
    path.parent.mkdir(parents=True)
    pd.DataFrame({"col": [1]}).to_parquet(path)  # reproduz o overlay ATP corrompido
    before = _state(path)
    with pytest.raises(ValueError, match="schema inválido"):
        _save(_match(template, 1))
    assert _state(path) == before


def test_deterministic_order_and_hash(template):
    a = _cat(_match(template, 2, date="2026-08-01"), _match(template, 1))
    b = a.iloc[::-1].reset_index(drop=True)
    assert om.canonical_hash(a) == om.canonical_hash(b)
    _save(b)
    current = pd.read_parquet(om.overlay_path("ATP"))
    assert current["match_id"].tolist() == ["ATP:2026-TEST:1"] * 2 + ["ATP:2026-TEST:2"] * 2
    assert current["result"].tolist() == ["W", "L", "W", "L"]


# 10
def test_real_sackmann_ids_used_and_base_unchanged(template):
    base_path = PROCESSED_DIRS["atp"] / "matches.parquet"
    before = _state(base_path)
    in_base = template.copy()
    in_base["tournament_date"] = pd.Timestamp("2026-07-01")  # passa o cutoff, mas match_id é do Sackmann
    res = om.merge_and_save("ATP", _cat(in_base, _match(template, 1)), run_id="r1", cutoff=CUTOFF)
    assert res["report"]["n_ignored_in_sackmann_rows"] == 2
    assert set(pd.read_parquet(om.overlay_path("ATP"))["match_id"]) == {"ATP:2026-TEST:1"}
    assert _state(base_path) == before


# 11 + 12
def test_writes_only_under_tmp_path(template, tmp_path):
    res = _save(_match(template, 1))
    assert Path(res["path"]).is_relative_to(tmp_path)
