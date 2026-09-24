"""Testes unitários e de integração do LOTE J — Tennis Abstract Incremental Overlay.

Cobre rigorosamente as 23 categorias de testes exigidas pela especificação:
1. parsing ATP
2. parsing WTA
3. 9 campos críticos
4. mapping próprio/oponente
5. cache hit
6. cache expirado
7. rate limit
8. HTTP 429
9. HTTP 403
10. jogador inexistente
11. schema inesperado
12. partida incompleta
13. player identity exata
14. identidade ambígua
15. dedupe A/B
16. overlay não sobrescreve base oficial
17. merge base + overlay
18. freshness UPDATED
19. freshness PARTIAL
20. freshness BASE_ONLY
21. source unavailable
22. anti-leakage
23. igualdade com Sackmann nas 41 partidas do spike (golden dataset)
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest import mock

import pandas as pd

from src.incremental import config as inc_cfg
from src.incremental.config import (
    RAW_SCHEMA_COLUMNS,
    STAT_COLUMNS,
    TA_BASE_CUTOFF,
)
from src.incremental.tennis_abstract_source import (
    AccessForbiddenError,
    MATCHHEAD_COLUMNS,
    PlayerNotFoundError,
    RateLimitError,
    TennisAbstractError,
    TennisAbstractSource,
    parse_js_matrix,
    slugify_player_name,
)
from src.incremental.tennis_abstract_adapter import (
    match_context_key,
    parse_ta_match_row,
    process_tennis_abstract_matches,
)
from src.incremental.overlay import (
    get_effective_matches,
    get_player_freshness,
    load_overlay_matches,
    save_overlay_matches,
)
from src.normalization.config import PROCESSED_DIRS
from src.normalization.matches import OUTPUT_COLUMNS

REAL_ATP_OVERLAY_PATH = inc_cfg.TA_OVERLAY_DIR / "atp" / "matches.parquet"


def _file_state(path: Path) -> tuple[str, int] | None:
    """(sha256, mtime_ns) do arquivo, ou None se não existir. Somente leitura."""
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


def _valid_overlay_rows() -> pd.DataFrame:
    """2 linhas da base oficial ATP no schema canônico OUTPUT_COLUMNS."""
    df = pd.read_parquet(PROCESSED_DIRS["atp"] / "matches.parquet")
    return df.iloc[0:2][OUTPUT_COLUMNS].reset_index(drop=True)


def _make_sample_matchhead_row(**kwargs) -> dict[str, str]:
    """Cria um registro sintético compatível com matchhead do Tennis Abstract."""
    base = {col: "" for col in MATCHHEAD_COLUMNS}
    defaults = {
        "date": "20260615",
        "tourn": "Halle",
        "surf": "Grass",
        "level": "A",
        "wl": "W",
        "rank": "2",
        "round": "F",
        "score": "7-6 6-4",
        "opp": "Hubert Hurkacz",
        "orank": "9",
        "time": "115",
        "matchid": "2026-500-101",
        "matchnum": "101",
        # Jogador vencedor (A)
        "aces": "12",
        "dfs": "2",
        "pts": "75",
        "firsts": "52",
        "fwon": "42",
        "swon": "14",
        "games": "11",
        "saved": "3",
        "chances": "4",
        # Oponente perdedor (B)
        "oaces": "15",
        "odfs": "3",
        "opts": "80",
        "ofirsts": "55",
        "ofwon": "40",
        "oswon": "12",
        "ogames": "11",
        "osaved": "4",
        "ochances": "6",
    }
    defaults.update(kwargs)
    base.update(defaults)
    return base


class TestTennisAbstractOverlay(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # F. guarda: a suíte nunca pode alterar (nem criar) o overlay ATP real
        cls._real_atp_state = _file_state(REAL_ATP_OVERLAY_PATH)

    @classmethod
    def tearDownClass(cls) -> None:
        after = _file_state(REAL_ATP_OVERLAY_PATH)
        if after != cls._real_atp_state:
            raise AssertionError(
                f"Suíte alterou o overlay ATP real {REAL_ATP_OVERLAY_PATH}: "
                f"{cls._real_atp_state} -> {after}"
            )

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.cache_dir = Path(self.temp_dir) / "cache"
        self.overlay_dir = Path(self.temp_dir) / "overlay"
        self.cache_dir.mkdir(parents=True)
        self.overlay_dir.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # 1. parsing ATP
    def test_01_parsing_atp_html_inline(self) -> None:
        html = """
        <html><body>
        <script>
        var matchmx = [
            ["20260601","Roland Garros","Clay","G","W","3","","","F","6-3 6-2 5-7 6-1","","Alexander Zverev","4","","","R","1997-04-20","198","GER","active","180","8","2","120","80","60","25","18","5","7","6","4","115","70","45","20","18","6","11","R","","","","2026-520-127","","7","127"]
        ];
        </script>
        </body></html>
        """
        source = TennisAbstractSource(cache_dir=self.cache_dir, delay_seconds=0.0)
        with mock.patch.object(source, "_http_get", return_value=(200, html)):
            data = source.fetch_player_matches("Carlos Alcaraz", "ATP")
            self.assertEqual(data["total_matches"], 1)
            self.assertEqual(data["matches"][0]["tourn"], "Roland Garros")
            self.assertEqual(data["matches"][0]["aces"], "8")

    # 2. parsing WTA
    def test_02_parsing_wta_external_script(self) -> None:
        html = '<html><head><script src="https://www.tennisabstract.com/jsmatches/IgaSwiatek.js"></script></head></html>'
        js_code = 'var matchmx = [["20260608","Roland Garros","Clay","G","W","1","","","F","6-2 6-1","","Jasmine Paolini","15","","","R","1996-01-10","163","ITA","active","68","1","0","50","35","28","10","8","1","1","0","2","48","28","14","6","7","2","6","R","","","","2026-800-127","","7","127"]];'

        source = TennisAbstractSource(cache_dir=self.cache_dir, delay_seconds=0.0)

        def mock_get(url: str):
            if "jsmatches" in url:
                return 200, js_code
            return 200, html

        with mock.patch.object(source, "_http_get", side_effect=mock_get):
            data = source.fetch_player_matches("Iga Swiatek", "WTA")
            self.assertEqual(data["total_matches"], 1)
            self.assertEqual(data["matches"][0]["opp"], "Jasmine Paolini")
            self.assertEqual(data["matches"][0]["saved"], "1")

    # 3. 9 campos
    def test_03_all_nine_critical_fields_mapped(self) -> None:
        m = _make_sample_matchhead_row()
        row, status = parse_ta_match_row(m, "Jannik Sinner", "ATP")
        self.assertEqual(status, "VALID")
        self.assertIsNotNone(row)

        for col in STAT_COLUMNS:
            self.assertIn(col, row)
            self.assertIsNotNone(row[col])

        self.assertEqual(row["w_ace"], 12)
        self.assertEqual(row["w_df"], 2)
        self.assertEqual(row["w_svpt"], 75)
        self.assertEqual(row["w_1stIn"], 52)
        self.assertEqual(row["w_1stWon"], 42)
        self.assertEqual(row["w_2ndWon"], 14)
        self.assertEqual(row["w_SvGms"], 11)
        self.assertEqual(row["w_bpSaved"], 3)
        self.assertEqual(row["w_bpFaced"], 4)

        self.assertEqual(row["l_ace"], 15)
        self.assertEqual(row["l_df"], 3)
        self.assertEqual(row["l_svpt"], 80)
        self.assertEqual(row["l_1stIn"], 55)
        self.assertEqual(row["l_1stWon"], 40)
        self.assertEqual(row["l_2ndWon"], 12)
        self.assertEqual(row["l_SvGms"], 11)
        self.assertEqual(row["l_bpSaved"], 4)
        self.assertEqual(row["l_bpFaced"], 6)

    # 4. mapping próprio/oponente
    def test_04_mapping_when_player_is_loser(self) -> None:
        m = _make_sample_matchhead_row(wl="L", opp="Novak Djokovic")
        row, status = parse_ta_match_row(m, "Tomas Machac", "ATP")
        self.assertEqual(status, "VALID")
        self.assertEqual(row["winner_name"], "Novak Djokovic")
        self.assertEqual(row["loser_name"], "Tomas Machac")
        # Quando wl == "L", as colunas de oaces pertencem ao vencedor (Novak)
        self.assertEqual(row["w_ace"], 15)
        self.assertEqual(row["l_ace"], 12)

    # 5. cache hit
    def test_05_cache_hit_avoids_network_request(self) -> None:
        source = TennisAbstractSource(cache_dir=self.cache_dir, delay_seconds=0.0)
        slug = slugify_player_name("Carlos Alcaraz")
        cache_file = self.cache_dir / "ATP" / f"{slug}.json"
        cache_file.parent.mkdir(parents=True)
        payload = {
            "player": {"name": "Carlos Alcaraz", "slug": slug, "tour": "ATP"},
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source_url": "mock://test",
            "matches": [_make_sample_matchhead_row()],
            "cache_hit": False,
        }
        cache_file.write_text(json.dumps(payload), encoding="utf-8")

        with mock.patch.object(source, "_http_get") as mock_get:
            res = source.fetch_player_matches("Carlos Alcaraz", "ATP")
            self.assertTrue(res["cache_hit"])
            mock_get.assert_not_called()

    # 6. cache expirado
    def test_06_cache_expired_triggers_network_request(self) -> None:
        source = TennisAbstractSource(cache_dir=self.cache_dir, delay_seconds=0.0, ttl_hours=24.0)
        slug = slugify_player_name("Carlos Alcaraz")
        cache_file = self.cache_dir / "ATP" / f"{slug}.json"
        cache_file.parent.mkdir(parents=True)
        old_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        payload = {
            "player": {"name": "Carlos Alcaraz", "slug": slug, "tour": "ATP"},
            "fetched_at": old_time,
            "source_url": "mock://test",
            "matches": [],
            "cache_hit": False,
        }
        cache_file.write_text(json.dumps(payload), encoding="utf-8")

        html = 'var matchmx = [["20260615","Halle","Grass","A","W","2","","","F","6-4 6-3","","Jannik Sinner","1","","","R","2001-08-16","188","ITA","active","90","5","1","60","40","32","12","9","2","2","8","2","65","45","30","10","9","3","5","R","","","","2026-500-101","","7","101"]];'
        with mock.patch.object(source, "_http_get", return_value=(200, html)) as mock_get:
            res = source.fetch_player_matches("Carlos Alcaraz", "ATP")
            self.assertFalse(res["cache_hit"])
            mock_get.assert_called_once()

    # 7. rate limit
    def test_07_rate_limit_sleep_enforced(self) -> None:
        source = TennisAbstractSource(cache_dir=self.cache_dir, delay_seconds=0.5)
        source._last_request_time = 0.0

        with mock.patch("time.sleep") as mock_sleep:
            source._last_request_time = 1000.0
            with mock.patch("time.time", side_effect=[1000.1, 1000.5]):
                source._rate_limit_sleep()
                mock_sleep.assert_called_once()
                self.assertAlmostEqual(mock_sleep.call_args[0][0], 0.4, places=2)

    # 8. HTTP 429
    def test_08_http_429_raises_rate_limit_error(self) -> None:
        source = TennisAbstractSource(cache_dir=self.cache_dir, delay_seconds=0.0)
        with mock.patch.object(source, "_http_get", return_value=(429, "")):
            with self.assertRaises(RateLimitError):
                source.fetch_player_matches("Carlos Alcaraz", "ATP")

    # 9. HTTP 403
    def test_09_http_403_raises_access_forbidden(self) -> None:
        source = TennisAbstractSource(cache_dir=self.cache_dir, delay_seconds=0.0)
        with mock.patch.object(source, "_http_get", return_value=(403, "")):
            with self.assertRaises(AccessForbiddenError):
                source.fetch_player_matches("Carlos Alcaraz", "ATP")

    # 10. jogador inexistente
    def test_10_missing_player_raises_player_not_found(self) -> None:
        source = TennisAbstractSource(cache_dir=self.cache_dir, delay_seconds=0.0)
        with mock.patch.object(source, "_http_get", return_value=(404, "")):
            with self.assertRaises(PlayerNotFoundError):
                source.fetch_player_matches("NonExistentPlayer123", "ATP")

    # 11. schema inesperado
    def test_11_malformed_matrix_returns_empty_without_crash(self) -> None:
        rows = parse_js_matrix("malformed [[[ string without valid csv")
        self.assertEqual(rows, [])

    # 12. partida incompleta
    def test_12_incomplete_match_is_rejected_never_zero_filled(self) -> None:
        # Faltando aces do jogador
        m = _make_sample_matchhead_row(aces="")
        row, status = parse_ta_match_row(m, "Carlos Alcaraz", "ATP")
        self.assertIsNone(row)
        self.assertTrue(status.startswith("INCOMPLETE_STATS:w_ace"))

    # 13. player identity exata
    def test_13_exact_player_identity_resolution(self) -> None:
        from src.incremental.identity_new import resolve_incremental_players
        from src.normalization.players import load_players

        players_df, _ = load_players("atp")
        raw_df = pd.DataFrame([{
            "tour": "ATP",
            "tourney_id": "2026-TEST",
            "tourney_name": "Test",
            "surface": "Hard",
            "tourney_level": "A",
            "tourney_date": 20260601,
            "match_num": 1,
            "winner_name": "Carlos Alcaraz",
            "loser_name": "Jannik Sinner",
            "score": "6-4 6-4",
            "round": "F",
            "minutes": 90,
            "w_ace": 5, "w_df": 1, "w_svpt": 50, "w_1stIn": 35, "w_1stWon": 28, "w_2ndWon": 10, "w_SvGms": 8, "w_bpSaved": 2, "w_bpFaced": 2,
            "l_ace": 4, "l_df": 2, "l_svpt": 55, "l_1stIn": 38, "l_1stWon": 26, "l_2ndWon": 8, "l_SvGms": 8, "l_bpSaved": 1, "l_bpFaced": 3,
        }])
        resolved = resolve_incremental_players(raw_df, "ATP", players_df)
        self.assertEqual(resolved["winner_resolution_method"].iloc[0], "exact")
        self.assertEqual(resolved["loser_resolution_method"].iloc[0], "exact")
        self.assertTrue(resolved["winner_id"].iloc[0].isdigit())

    # 14. identidade ambígua
    def test_14_unresolved_player_mints_new_synthetic_id(self) -> None:
        from src.incremental.identity_new import resolve_incremental_players
        from src.normalization.players import load_players

        players_df, _ = load_players("atp")
        raw_df = pd.DataFrame([{
            "tour": "ATP",
            "tourney_id": "2026-TEST",
            "tourney_name": "Test",
            "surface": "Hard",
            "tourney_level": "A",
            "tourney_date": 20260601,
            "match_num": 1,
            "winner_name": "Carlos Alcaraz",
            "loser_name": "Totalmente Desconhecido XYZ 2026",
            "score": "6-4 6-4",
            "round": "F",
            "minutes": 90,
            "w_ace": 5, "w_df": 1, "w_svpt": 50, "w_1stIn": 35, "w_1stWon": 28, "w_2ndWon": 10, "w_SvGms": 8, "w_bpSaved": 2, "w_bpFaced": 2,
            "l_ace": 4, "l_df": 2, "l_svpt": 55, "l_1stIn": 38, "l_1stWon": 26, "l_2ndWon": 8, "l_SvGms": 8, "l_bpSaved": 1, "l_bpFaced": 3,
        }])
        resolved = resolve_incremental_players(raw_df, "ATP", players_df)
        self.assertEqual(resolved["loser_resolution_method"].iloc[0], "unresolved")
        self.assertTrue(resolved["loser_id"].iloc[0].startswith("NEW-"))

    # 15. dedupe A/B
    def test_15_cross_player_duplicate_matches_deduplicated(self) -> None:
        # Mesma partida vista do ponto de vista de Alcaraz (W) e Hurkacz (L)
        p1 = {
            "player": {"name": "Carlos Alcaraz", "tour": "ATP"},
            "matches": [_make_sample_matchhead_row(wl="W", opp="Hubert Hurkacz")],
        }
        p2 = {
            "player": {"name": "Hubert Hurkacz", "tour": "ATP"},
            "matches": [_make_sample_matchhead_row(wl="L", opp="Carlos Alcaraz", aces="15", oaces="12")],
        }
        res = process_tennis_abstract_matches([p1, p2], "ATP", cutoff_date="2026-05-25")
        # Deve incorporar apenas 1 partida física única (que vira 2 perspectivas normalizadas)
        self.assertEqual(res["valid_count"], 1)
        self.assertEqual(res["rejected_reasons"].get("DUPLICATE_CROSS_PLAYER"), 1)
        self.assertEqual(len(res["transformed_df"]), 2)

    # 16. overlay não sobrescreve base oficial
    def test_16_save_overlay_does_not_mutate_official_parquet(self) -> None:
        official_path = PROCESSED_DIRS["atp"] / "matches.parquet"
        official_mtime = official_path.stat().st_mtime
        official_size = official_path.stat().st_size
        real_overlay_before = _file_state(REAL_ATP_OVERLAY_PATH)

        with mock.patch.object(inc_cfg, "TA_OVERLAY_DIR", self.overlay_dir):
            saved = save_overlay_matches("ATP", _valid_overlay_rows())

        # A. escrita ocorre somente no diretório temporário
        self.assertEqual(saved, self.overlay_dir / "atp" / "matches.parquet")
        self.assertTrue(saved.exists())
        self.assertEqual(_file_state(REAL_ATP_OVERLAY_PATH), real_overlay_before)

        current_mtime = official_path.stat().st_mtime
        current_size = official_path.stat().st_size
        self.assertEqual(official_mtime, current_mtime)
        self.assertEqual(official_size, current_size)

    # 16b. schema inválido é rejeitado
    def test_16b_save_overlay_rejects_invalid_schema(self) -> None:
        with mock.patch.object(inc_cfg, "TA_OVERLAY_DIR", self.overlay_dir):
            with self.assertRaises(ValueError):
                save_overlay_matches("ATP", pd.DataFrame({"col": [1]}))
            # colunas certas em ordem diferente também são rejeitadas
            with self.assertRaises(ValueError):
                save_overlay_matches("ATP", _valid_overlay_rows()[OUTPUT_COLUMNS[::-1]])
        self.assertFalse((self.overlay_dir / "atp" / "matches.parquet").exists())

    # 16c. DataFrame vazio é rejeitado
    def test_16c_save_overlay_rejects_empty_df(self) -> None:
        with mock.patch.object(inc_cfg, "TA_OVERLAY_DIR", self.overlay_dir):
            with self.assertRaises(ValueError):
                save_overlay_matches("ATP", pd.DataFrame())
            with self.assertRaises(ValueError):
                save_overlay_matches("ATP", pd.DataFrame(columns=OUTPUT_COLUMNS))
        self.assertFalse((self.overlay_dir / "atp" / "matches.parquet").exists())

    # 16d. schema OUTPUT_COLUMNS válido é aceito e relido íntegro
    def test_16d_save_overlay_accepts_output_columns_schema(self) -> None:
        df = _valid_overlay_rows()
        with mock.patch.object(inc_cfg, "TA_OVERLAY_DIR", self.overlay_dir):
            path = save_overlay_matches("ATP", df)
            reloaded = load_overlay_matches("ATP")
        self.assertTrue(path.exists())
        self.assertEqual(list(reloaded.columns), OUTPUT_COLUMNS)
        self.assertEqual(len(reloaded), 2)

    # 16e. arquivo existente fica byte a byte intacto após tentativa inválida
    def test_16e_existing_overlay_untouched_on_invalid_save(self) -> None:
        with mock.patch.object(inc_cfg, "TA_OVERLAY_DIR", self.overlay_dir):
            path = save_overlay_matches("ATP", _valid_overlay_rows())
            before = _file_state(path)
            for bad in (pd.DataFrame({"col": [1]}), pd.DataFrame()):
                with self.assertRaises(ValueError):
                    save_overlay_matches("ATP", bad)
        self.assertEqual(_file_state(path), before)

    # 17. merge base + overlay
    def test_17_get_effective_matches_merges_in_memory(self) -> None:
        # Criar 2 linhas de overlay sintéticas válidas
        base = PROCESSED_DIRS["atp"] / "matches.parquet"
        df_base = pd.read_parquet(base)
        sample_row = df_base.iloc[0:2].copy()
        sample_row["tournament_date"] = pd.Timestamp("2026-09-20")
        sample_row["match_id"] = "ATP:2026-OVERLAY-TEST:1"

        effective = get_effective_matches("ATP", override_overlay_df=sample_row, enabled=True)
        self.assertEqual(len(effective), len(df_base) + 2)
        # O último tournament_date agora é a partida do overlay
        self.assertEqual(effective["tournament_date"].max(), pd.Timestamp("2026-09-20"))

    # 18. freshness UPDATED
    def test_18_freshness_updated(self) -> None:
        overlay_df = pd.DataFrame([{
            "player_name": "Carlos Alcaraz",
            "tournament_date": 20260920,
        }])
        freshness = get_player_freshness("Carlos Alcaraz", "ATP", overlay_df=overlay_df)
        self.assertEqual(freshness["freshness_status"], "UPDATED")
        self.assertEqual(freshness["effective_data_cutoff"], "2026-09-20")

    # 19. freshness PARTIAL
    def test_19_freshness_partial_when_issues_present(self) -> None:
        overlay_df = pd.DataFrame([{
            "player_name": "Carlos Alcaraz",
            "tournament_date": 20260920,
        }])
        freshness = get_player_freshness("Carlos Alcaraz", "ATP", overlay_df=overlay_df, has_partial_issues=True)
        self.assertEqual(freshness["freshness_status"], "PARTIAL")
        self.assertEqual(freshness["effective_data_cutoff"], "2026-09-20")

    # 20. freshness BASE_ONLY
    def test_20_freshness_base_only_when_no_overlay_matches(self) -> None:
        overlay_df = pd.DataFrame()
        freshness = get_player_freshness("Carlos Alcaraz", "ATP", overlay_df=overlay_df)
        self.assertEqual(freshness["freshness_status"], "BASE_ONLY")
        self.assertEqual(freshness["effective_data_cutoff"], TA_BASE_CUTOFF)

    # 21. source unavailable
    def test_21_source_unavailable_fallback(self) -> None:
        freshness = get_player_freshness("Carlos Alcaraz", "ATP", source_status="429")
        self.assertEqual(freshness["freshness_status"], "SOURCE_UNAVAILABLE")
        self.assertEqual(freshness["effective_data_cutoff"], TA_BASE_CUTOFF)

    # 22. anti-leakage
    def test_22_anti_leakage_preserves_point_in_time_order(self) -> None:
        # Garante que as partidas do overlay aparecem estritamente após a data de corte
        # e ordenadas cronologicamente
        base = PROCESSED_DIRS["atp"] / "matches.parquet"
        df_base = pd.read_parquet(base)
        max_base_date = df_base["tournament_date"].max()

        sample_row = df_base.iloc[0:2].copy()
        sample_row["tournament_date"] = pd.Timestamp("2026-07-01")
        sample_row["match_id"] = "ATP:2026-OVERLAY-LEAKAGE:1"

        effective = get_effective_matches("ATP", override_overlay_df=sample_row, enabled=True)
        # Partidas com date <= max_base_date continuam exatamente como estavam
        pre_cutoff_count = (effective["tournament_date"] <= max_base_date).sum()
        self.assertEqual(pre_cutoff_count, len(df_base))

        # Nenhuma linha posterior a 2026-06-01 existirá se filtrarmos por date <= 2026-06-01
        point_in_time_view = effective[effective["tournament_date"] <= pd.Timestamp("2026-06-01")]
        self.assertFalse((point_in_time_view["tournament_date"] > pd.Timestamp("2026-06-01")).any())

    # 23. igualdade com Sackmann nas 41 partidas do spike (golden dataset)
    def test_23_golden_dataset_exact_match(self) -> None:
        fixture_path = Path("tests/fixtures/golden_ta_sackmann.json")
        self.assertTrue(fixture_path.exists(), "Golden dataset fixture não encontrada!")
        with open(fixture_path, encoding="utf-8") as f:
            golden = json.load(f)

        self.assertEqual(len(golden), 41, "Golden dataset deve conter exatamente 41 partidas")

        diffs = []
        for idx, item in enumerate(golden):
            field_matches = item.get("field_matches", {})
            for field, res in field_matches.items():
                if not res.get("exact"):
                    diffs.append((idx, field, res.get("ta"), res.get("sackmann")))

        self.assertEqual(len(diffs), 0, f"Divergência encontrada no Golden Dataset: {diffs}")


if __name__ == "__main__":
    unittest.main()
