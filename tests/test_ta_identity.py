"""Testes de slug + verificação de identidade Tennis Abstract (LOTE J, T4).

Totalmente sintéticos: sem rede (urlopen bloqueado), cache em `tmp_path`,
histórico Sackmann e política construídos em memória. A fixture de módulo
garante que cache TA, overlays reais e base Sackmann ficam intactos."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest import mock

import pandas as pd
import pytest

from src.incremental import config as inc_cfg
from src.incremental import ta_identity as ti
from src.incremental import tennis_abstract_source as tas
from src.incremental.tennis_abstract_adapter import AcceptancePolicy
from src.incremental.tennis_abstract_source import HttpResponse, TennisAbstractSource
from src.normalization.config import PROCESSED_DIRS

ALCARAZ, MENSIK, BU, SINNER = "ATP-207989", "ATP-210150", "ATP-207352", "ATP-206173"

POLICY = AcceptancePolicy(
    levels=frozenset({"A", "D", "F", "G", "M", "O"}),
    rounds=frozenset({"BR", "F", "QF", "R128", "R16", "R32", "R64", "RR", "SF"}),
)

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


# --- fixtures sintéticas -------------------------------------------------------

def _ta(matchid: str, date: str = "20250610", level: str = "A", rnd: str = "R32") -> list[str]:
    row = {c: "" for c in tas.MATCHHEAD_COLUMNS}
    row.update({"date": date, "level": level, "round": rnd, "matchid": matchid, "wl": "W",
                "opp": "Someone", "surf": "Hard", "max": "3", "score": "6-4 6-4"})
    return [row[c] for c in tas.MATCHHEAD_COLUMNS]


def _page(fullname: str | None, rows: list[list[str]] | None) -> str:
    """HTML com a mesma estrutura da página real (var fullname + matchmx inline)."""
    parts = ["<html><head><title>Tennis Abstract</title></head><body><script>"]
    if fullname is not None:
        parts.append(f"var fullname = '{fullname}';")
    if rows is not None:
        parts.append("var matchmx = [" + ",".join(json.dumps(r) for r in rows) + "];")
    parts.append('</script><script src="https://www.tennisabstract.com/jsmatches/X.js"></script></body></html>')
    return "\n".join(parts)


def _template_page(slug: str) -> str:
    """Página modelo devolvida com HTTP 200 para slug inválido (T2): sem fullname/matchmx."""
    return (f"<html><title>Tennis Abstract: {slug[1:]} Match Results, Splits, and Analysis</title>"
            f'<script src="https://www.tennisabstract.com/jsmatches/{slug}.js"></script>'
            f'<script src="https://www.tennisabstract.com/jsdoubles/{slug}.js"></script></html>')


def _history(player_id: str, match_ids: list[str], others: dict[str, str] | None = None) -> pd.DataFrame:
    """Base Sackmann mínima: 2 linhas por partida; janela 2024-01-01..2026-05-25."""
    recs = []
    for mid in match_ids:
        recs += [(mid, player_id, "2025-06-09"), (mid, "ATP-999999", "2025-06-09")]
    for mid, pid in (others or {}).items():
        recs += [(mid, pid, "2025-06-09"), (mid, "ATP-999998", "2025-06-09")]
    recs += [("ATP:2024-START:1", "ATP-1", "2024-01-01"), ("ATP:2026-END:1", "ATP-2", "2026-05-25")]
    return pd.DataFrame(recs, columns=["match_id", "player_id", "tournament_date"]).assign(
        tournament_date=lambda d: pd.to_datetime(d["tournament_date"]))


def _ids(prefix: str, n: int) -> list[str]:
    return [f"2025-{prefix}-{i}" for i in range(1, n + 1)]


def _sk(tid_num: str) -> str:
    tid, num = tid_num.rsplit("-", 1)
    return f"ATP:{tid}:{int(num)}"


def _source(tmp_path, overrides=None) -> TennisAbstractSource:
    return TennisAbstractSource(cache_dir=tmp_path / "cache", delay_seconds=0.0,
                                slug_overrides=overrides if overrides is not None else {})


def _fetch_and_verify(tmp_path, player_id, name, html, history, status=200, **kw):
    src = _source(tmp_path, kw.pop("overrides", None))
    with mock.patch.object(src, "_http_get", return_value=HttpResponse(status, html, kw.pop("headers", {}))) as get:
        payload = src.fetch_player_page(player_id, name, "ATP", **kw)
    return payload, ti.verify_identity(player_id, payload, history, POLICY), get


# --- fixtures "-like" dos casos reais do T2 ------------------------------------

def test_alcaraz_like_verified(tmp_path):
    ids = _ids("0404", 12)
    rows = [_ta(m) for m in ids]
    rows += [_ta("2025-520-901", level="G", rnd="Q2"), _ta("2025-520-902", level="G", rnd="Q3")]  # qualifying
    rows += [_ta("2025-2891-1", level="C")]                                                        # challenger
    rows += [_ta("2026-7485-1", date="20260701", level="G", rnd="R128")]                           # pós-base
    payload, res, get = _fetch_and_verify(tmp_path, ALCARAZ, "Carlos Alcaraz", _page("Carlos Alcaraz", rows),
                                          _history(ALCARAZ, [_sk(m) for m in ids]))
    assert payload["fetch_status"] == tas.PAGE_OK
    assert payload["player"]["slug"] == "CarlosAlcaraz"
    assert res["identity_status"] == ti.VERIFIED
    assert (res["comparable_matches"], res["overlap_matches"], res["overlap_ratio"]) == (12, 12, 1.0)
    assert res["excluded_from_denominator"] == {"ROUND_OUT_OF_POLICY": 2, "LEVEL_OUT_OF_POLICY": 1,
                                                "OUTSIDE_BASE_WINDOW": 1}
    get.assert_called_once()


def test_mensik_like_verified_with_davis_cup_id(tmp_path):
    ids = _ids("0339", 7) + ["2024-M-DC-2024-FLS-M-CZE-X-01-002"]
    rows = [_ta(m, date="20240915", level="D", rnd="RR") if "DC" in m else _ta(m) for m in ids]
    history = _history(MENSIK, [_sk(m) for m in ids])
    assert "ATP:2024-M-DC-2024-FLS-M-CZE-X-01:2" in set(history["match_id"])
    _, res, _ = _fetch_and_verify(tmp_path, MENSIK, "Jakub Mensik", _page("Jakub Mensik", rows), history)
    assert res["identity_status"] == ti.VERIFIED
    assert (res["comparable_matches"], res["overlap_matches"]) == (8, 8)
    assert res["slug"] == "JakubMensik" and res["slug_source"] == "generated"


def test_bu_like_verified_canonical_name_order(tmp_path):
    ids = _ids("0580", 6)
    rows = [_ta(m) for m in ids] + [_ta(f"2025-C{i}-1", level="C") for i in range(20)]
    _, res, get = _fetch_and_verify(tmp_path, BU, "Bu Yunchaokete", _page("Bu Yunchaokete", rows),
                                    _history(BU, [_sk(m) for m in ids]))
    assert "p=BuYunchaokete" in get.call_args[0][0]  # ordem "Nome Sobrenome" do players.parquet
    assert res["identity_status"] == ti.VERIFIED
    assert res["comparable_matches"] == 6
    assert res["excluded_from_denominator"] == {"LEVEL_OUT_OF_POLICY": 20}


def test_lowercase_template_page_is_no_player_data(tmp_path):
    payload, res, get = _fetch_and_verify(tmp_path, MENSIK, "Jakub Mensik", _template_page("jakubmensik"),
                                          _history(MENSIK, []), slug="jakubmensik")
    assert payload["http_status"] == 200  # slug inválido responde 200, não 404
    assert payload["fetch_status"] == tas.NO_PLAYER_DATA
    assert payload["matches"] == [] and payload["page_fullname"] is None
    assert res["identity_status"] == ti.NO_PLAYER_DATA
    get.assert_called_once()
    assert "jsmatches" not in get.call_args[0][0]
    assert not (tmp_path / "cache").exists()  # página modelo nunca vai ao cache


def test_empty_page_with_fullname_is_no_player_data(tmp_path):
    payload, res, _ = _fetch_and_verify(tmp_path, BU, "Bu Yunchaokete", _page("Bu Yunchaokete", None),
                                        _history(BU, []))
    assert payload["fetch_status"] == tas.EMPTY_PAGE
    assert payload["page_fullname"] == "Bu Yunchaokete"
    assert res["identity_status"] == ti.NO_PLAYER_DATA


# --- limiares ------------------------------------------------------------------

def _verify(ta_ids, base_ids, others=None, **row_kw):
    payload = {"player": {"player_id": ALCARAZ, "tour": "ATP", "slug": "CarlosAlcaraz"},
               "fetch_status": tas.PAGE_OK,
               "matches": [dict(zip(tas.MATCHHEAD_COLUMNS, _ta(m, **row_kw))) for m in ta_ids]}
    return ti.verify_identity(ALCARAZ, payload, _history(ALCARAZ, [_sk(m) for m in base_ids], others), POLICY)


def test_fewer_than_3_comparable_is_insufficient_not_mismatch():
    res = _verify(["2025-1-1", "2025-1-2"], base_ids=[])  # 0/2: ainda assim não é mismatch
    assert res["identity_status"] == ti.INSUFFICIENT_EVIDENCE
    assert res["comparable_matches"] == 2
    res = _verify(["2025-1-1", "2025-1-2"], base_ids=["2025-1-1", "2025-1-2"])  # 2/2
    assert res["identity_status"] == ti.INSUFFICIENT_EVIDENCE


def test_3_or_more_with_low_overlap_is_mismatch():
    ids = _ids("1", 5)
    res = _verify(ids, base_ids=ids[:3])  # 3/5 = 60%
    assert res["identity_status"] == ti.MISMATCH
    assert res["overlap_ratio"] == pytest.approx(0.6)
    assert _verify(ids[:3], base_ids=[])["identity_status"] == ti.MISMATCH  # 0/3


def test_match_in_base_but_for_other_player_is_not_overlap():
    ids = _ids("1", 3)
    res = _verify(ids, base_ids=[], others={_sk(m): SINNER for m in ids})
    assert res["overlap_matches"] == 0
    assert res["identity_status"] == ti.MISMATCH


def test_3_or_more_with_overlap_at_threshold_is_verified():
    ids = _ids("1", 5)
    res = _verify(ids, base_ids=ids[:4])  # 4/5 = exatamente 80%
    assert res["identity_status"] == ti.VERIFIED
    assert _verify(ids[:3], base_ids=ids[:3])["identity_status"] == ti.VERIFIED  # 3/3


def test_out_of_policy_rows_not_in_denominator():
    ok = _ids("1", 3)
    payload = {"player": {"player_id": ALCARAZ, "tour": "ATP"}, "fetch_status": tas.PAGE_OK, "matches": [
        dict(zip(tas.MATCHHEAD_COLUMNS, r)) for r in
        [_ta(m) for m in ok]
        + [_ta(f"2025-520-{i}", level="G", rnd=q) for i, q in enumerate(("Q1", "Q2", "Q3"), 900)]
        + [_ta("2025-9-1", level="C"), _ta("2025-9-2", level="15"), _ta("2025-9-3", level="S")]
        + [_ta("2025-9-4", rnd="ER")]
        + [_ta("2023-9-5", date="20231231"), _ta("2026-9-6", date="20260526")]
        + [_ta("semhifen"), _ta("2025-9-7", date="")]
    ]}
    res = ti.verify_identity(ALCARAZ, payload, _history(ALCARAZ, [_sk(m) for m in ok]), POLICY)
    assert res["comparable_matches"] == 3
    assert res["identity_status"] == ti.VERIFIED  # sem as excluídas no denominador: 3/3
    assert res["excluded_from_denominator"] == {
        "ROUND_OUT_OF_POLICY": 4, "LEVEL_OUT_OF_POLICY": 3, "OUTSIDE_BASE_WINDOW": 2,
        "INVALID_MATCHID": 1, "INVALID_DATE": 1,
    }


def test_duplicate_matchids_counted_once():
    ids = _ids("1", 2)
    res = _verify(ids + ids, base_ids=ids)
    assert res["comparable_matches"] == 2
    assert res["identity_status"] == ti.INSUFFICIENT_EVIDENCE


def test_payload_of_other_player_rejected():
    payload = {"player": {"player_id": SINNER, "tour": "ATP"}, "matches": []}
    with pytest.raises(ValueError):
        ti.verify_identity(ALCARAZ, payload, _history(ALCARAZ, []), POLICY)


# --- slug ----------------------------------------------------------------------

def test_override_takes_precedence_over_generated_slug(tmp_path):
    src = _source(tmp_path, overrides={BU: "SlugDeOverride"})
    with mock.patch.object(src, "_http_get", return_value=HttpResponse(200, _template_page("X"))) as get:
        payload = src.fetch_player_page(BU, "Bu Yunchaokete", "ATP")
    assert payload["player"]["slug"] == "SlugDeOverride"
    assert payload["player"]["slug_source"] == "override"
    assert get.call_args[0][0].endswith("?p=SlugDeOverride")
    assert tas.resolve_slug(BU, "Bu Yunchaokete", {BU: "SlugDeOverride"}, explicit_slug="Explicito") == (
        "Explicito", "explicit")


def test_without_override_uses_camelcase_of_canonical_name():
    assert tas.resolve_slug(MENSIK, "Jakub Mensik", {}) == ("JakubMensik", "generated")
    assert tas.resolve_slug(BU, "Bu Yunchaokete", {ALCARAZ: "Outro"}) == ("BuYunchaokete", "generated")
    assert tas.resolve_slug("ATP-1", "Tomás Martín Etcheverry", {})[0] == "TomasMartinEtcheverry"
    with pytest.raises(ValueError):
        tas.resolve_slug("ATP-1", "  ", {})


def test_overrides_csv_loading(tmp_path):
    assert tas.load_slug_overrides() == {}  # arquivo versionado: só cabeçalho (sem Coleman Wong)
    assert tas.SLUG_OVERRIDES_PATH.read_text(encoding="utf-8").splitlines() == ["player_id,slug,reason"]
    good = tmp_path / "o.csv"
    good.write_text("player_id,slug,reason\nATP-208597,SomeSlug,teste\n", encoding="utf-8")
    assert tas.load_slug_overrides(good) == {"ATP-208597": "SomeSlug"}
    assert tas.load_slug_overrides(tmp_path / "ausente.csv") == {}
    for bad in ("id,slug\nX,Y\n",
                "player_id,slug,reason\nATP-1,,x\n",
                "player_id,slug,reason\nATP-1,A B,x\n",
                "player_id,slug,reason\nATP-1,A,x\nATP-1,B,y\n"):
        good.write_text(bad, encoding="utf-8")
        with pytest.raises(ValueError):
            tas.load_slug_overrides(good)


# --- HTTP / rate limit ---------------------------------------------------------

@pytest.mark.parametrize("status,expected", [(403, tas.HTTP_403), (429, tas.HTTP_429),
                                             (404, tas.HTTP_ERROR), (500, tas.HTTP_ERROR)])
def test_http_errors_classified_explicitly_without_retry(tmp_path, status, expected):
    payload, res, get = _fetch_and_verify(tmp_path, ALCARAZ, "Carlos Alcaraz", "error code: 1015",
                                          _history(ALCARAZ, []), status=status,
                                          headers={"retry-after": "10"} if status == 429 else {})
    assert payload["fetch_status"] == expected
    assert payload["http_status"] == status
    assert payload["retry_after"] == ("10" if status == 429 else None)
    assert res["identity_status"] == ti.FETCH_FAILED
    get.assert_called_once()  # nenhuma retry, nenhuma segunda URL
    assert not (tmp_path / "cache").exists()


def test_network_error_classified(tmp_path):
    src = _source(tmp_path)
    with mock.patch.object(src, "_http_get", side_effect=tas.NetworkError("timeout")) as get:
        payload = src.fetch_player_page(ALCARAZ, "Carlos Alcaraz", "ATP")
    assert payload["fetch_status"] == tas.NETWORK_ERROR
    assert payload["http_status"] is None
    get.assert_called_once()


def test_real_http_get_captures_retry_after_from_429(tmp_path):
    import io
    import urllib.error
    from email.message import Message

    headers = Message()
    headers["Retry-After"] = "10"
    err = urllib.error.HTTPError("http://x", 429, "Too Many Requests", headers, io.BytesIO(b"error code: 1015"))
    src = _source(tmp_path)
    with mock.patch("urllib.request.urlopen", side_effect=err) as urlopen:
        payload = src.fetch_player_page(ALCARAZ, "Carlos Alcaraz", "ATP")
    urlopen.assert_called_once()
    assert payload["fetch_status"] == tas.HTTP_429
    assert payload["retry_after"] == "10"


def test_no_secondary_jsmatches_request_even_when_page_references_it(tmp_path):
    html = _page(None, None)  # só o <script src=.../jsmatches/X.js>
    src = _source(tmp_path)
    with mock.patch.object(src, "_http_get", return_value=HttpResponse(200, html)) as get:
        payload = src.fetch_player_page(ALCARAZ, "Carlos Alcaraz", "ATP")
    get.assert_called_once()
    assert payload["fetch_status"] == tas.NO_PLAYER_DATA
    assert all("jsmatches" not in c.args[0] for c in get.call_args_list)


def test_page_ok_cached_under_tmp_and_reused(tmp_path):
    html = _page("Carlos Alcaraz", [_ta("2025-1-1")])
    src = _source(tmp_path)
    with mock.patch.object(src, "_http_get", return_value=HttpResponse(200, html)) as get:
        first = src.fetch_player_page(ALCARAZ, "Carlos Alcaraz", "ATP")
        second = src.fetch_player_page(ALCARAZ, "Carlos Alcaraz", "ATP")
    get.assert_called_once()
    assert (tmp_path / "cache" / "ATP" / "CarlosAlcaraz.json").exists()
    assert second["cache_hit"] and second["fetch_status"] == tas.PAGE_OK
    assert second["player"]["player_id"] == ALCARAZ == first["player"]["player_id"]
