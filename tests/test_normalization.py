"""Testes da Fase 2 (normalizacao).

Dois grupos:
  1. Testes de unidade das transformacoes puras (matches/players/rankings),
     usando DataFrames/CSVs sinteticos pequenos -- sem depender dos dados
     reais baixados na Fase 1.
  2. Testes de integracao sobre a base real ja normalizada em
     data/processed/, quando ela existir.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.normalization import matches, players, rankings, validate  # noqa: E402
from src.normalization.config import PROCESSED_DIRS, REPORTS_DIR  # noqa: E402


def _synthetic_raw_matches() -> pd.DataFrame:
    """Duas partidas sinteticas: uma com stats completos, outra com stats
    parcialmente ausentes (para testar que ausencia != zero)."""
    return pd.DataFrame([
        {
            "tourney_id": "2024-TEST", "tourney_name": "Synthetic Open", "surface": "Hard",
            "draw_size": 32, "tourney_level": "A", "tourney_date": 20240603, "match_num": 1,
            "winner_id": 1001, "winner_seed": None, "winner_entry": None, "winner_name": "Alice",
            "winner_hand": "R", "winner_ht": 175, "winner_ioc": "USA", "winner_age": 25.0,
            "loser_id": 1002, "loser_seed": None, "loser_entry": None, "loser_name": "Bea",
            "loser_hand": "L", "loser_ht": 180, "loser_ioc": "GBR", "loser_age": 27.0,
            "score": "6-4 6-3", "best_of": 3, "round": "F", "minutes": 90,
            "w_ace": 8, "w_df": 2, "w_svpt": 60, "w_1stIn": 40, "w_1stWon": 30, "w_2ndWon": 12,
            "w_SvGms": 10, "w_bpSaved": 3, "w_bpFaced": 5,
            "l_ace": 3, "l_df": 4, "l_svpt": 58, "l_1stIn": 35, "l_1stWon": 22, "l_2ndWon": 10,
            "l_SvGms": 9, "l_bpSaved": 2, "l_bpFaced": 6,
            "winner_rank": 5, "winner_rank_points": 3000, "loser_rank": 40, "loser_rank_points": 800,
        },
        {
            "tourney_id": "2024-TEST", "tourney_name": "Synthetic Open", "surface": "Hard",
            "draw_size": 32, "tourney_level": "A", "tourney_date": 20240603, "match_num": 2,
            "winner_id": 1003, "winner_seed": None, "winner_entry": None, "winner_name": "Cid",
            "winner_hand": "R", "winner_ht": 188, "winner_ioc": "BRA", "winner_age": 22.0,
            "loser_id": 1004, "loser_seed": None, "loser_entry": None, "loser_name": "Dan",
            "loser_hand": "R", "loser_ht": 183, "loser_ioc": "ARG", "loser_age": 29.0,
            # estatisticas de saque ausentes (walkover/sem stats reportadas)
            "score": "W/O", "best_of": 3, "round": "R32", "minutes": None,
            "w_ace": None, "w_df": None, "w_svpt": None, "w_1stIn": None, "w_1stWon": None,
            "w_2ndWon": None, "w_SvGms": None, "w_bpSaved": None, "w_bpFaced": None,
            "l_ace": None, "l_df": None, "l_svpt": None, "l_1stIn": None, "l_1stWon": None,
            "l_2ndWon": None, "l_SvGms": None, "l_bpSaved": None, "l_bpFaced": None,
            "winner_rank": 90, "winner_rank_points": 300, "loser_rank": None, "loser_rank_points": None,
        },
    ])


def _build_synthetic_table() -> pd.DataFrame:
    raw = matches._preprocess(_synthetic_raw_matches(), "atp")
    w = matches._build_perspective(raw, "atp", is_winner=True)
    l = matches._build_perspective(raw, "atp", is_winner=False)
    table = pd.concat([w, l], ignore_index=True)
    for col in matches.INT_COLUMNS:
        table[col] = pd.array(pd.to_numeric(table[col], errors="coerce"), dtype="Int64")
    return table[matches.OUTPUT_COLUMNS]


class TestMatchTransformation(unittest.TestCase):
    def setUp(self):
        self.table = _build_synthetic_table()

    def test_exactly_two_rows_per_match(self):
        counts = self.table.groupby("match_id").size()
        self.assertTrue((counts == 2).all())
        self.assertEqual(len(counts), 2)

    def test_match_id_is_stable_and_tour_scoped(self):
        ids = set(self.table["match_id"])
        self.assertEqual(ids, {"ATP:2024-TEST:1", "ATP:2024-TEST:2"})

    def test_opponent_stats_are_correctly_mirrored(self):
        result = validate.check_opponent_mirroring(self.table)
        self.assertEqual(result["n_field_mismatches_total"], 0, result["mismatches_by_field_pair"])

    def test_break_points_converted_arithmetic(self):
        row = self.table[(self.table["match_id"] == "ATP:2024-TEST:1") & (self.table["result"] == "W")].iloc[0]
        # winner devolveu contra o saque do perdedor: l_bpFaced(6) - l_bpSaved(2) = 4
        self.assertEqual(row["break_points_converted"], 4)
        self.assertEqual(row["break_points_created"], 6)

    def test_missing_stats_are_null_not_zero(self):
        rows = self.table[self.table["match_id"] == "ATP:2024-TEST:2"]
        self.assertTrue(rows["aces"].isna().all())
        self.assertTrue(rows["opponent_aces"].isna().all())
        self.assertTrue(rows["break_points_converted"].isna().all())
        # rank do perdedor tambem estava ausente na fonte
        loser_row = rows[rows["result"] == "L"].iloc[0]
        self.assertTrue(pd.isna(loser_row["player_rank"]))

    def test_player_and_opponent_id_are_tour_scoped(self):
        self.assertTrue(self.table["player_id"].str.startswith("ATP-").all())
        self.assertTrue(self.table["opponent_id"].str.startswith("ATP-").all())

    def test_ids_check_reports_no_issues(self):
        result = validate.check_ids(self.table)
        self.assertEqual(result["n_missing_player_id"], 0)
        self.assertEqual(result["n_missing_opponent_id"], 0)
        self.assertEqual(result["n_missing_match_id"], 0)
        self.assertEqual(result["n_match_ids_with_more_than_one_winner_row"], 0)


class TestCanonicalPlayerId(unittest.TestCase):
    def test_same_raw_id_different_tour_is_different_player(self):
        self.assertNotEqual(
            players.canonical_player_id("atp", 100001),
            players.canonical_player_id("wta", 100001),
        )

    def test_format(self):
        self.assertEqual(players.canonical_player_id("atp", 100001), "ATP-100001")
        self.assertEqual(players.canonical_player_id("wta", 200000), "WTA-200000")


class TestRankingsToursColumn(unittest.TestCase):
    """A coluna `tours` existe so no WTA bruto (achado da Fase 1). A Fase 2
    deve unificar o schema sem inventar dado nem descartar informacao."""

    def test_tours_is_null_for_atp_and_preserved_for_wta(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            atp_csv = tmp_path / "atp_r.csv"
            wta_csv = tmp_path / "wta_r.csv"
            atp_csv.write_text("ranking_date,rank,player,points\n20240101,1,1001,5000\n", encoding="utf-8")
            wta_csv.write_text("ranking_date,rank,player,points,tours\n20240101,1,2001,5200,12\n", encoding="utf-8")

            with mock.patch.object(rankings, "RAW_DIRS", {"atp": tmp_path, "wta": tmp_path}), \
                 mock.patch.object(rankings, "RANKINGS_FILES", {"atp": ["atp_r.csv"], "wta": ["wta_r.csv"]}):
                atp_df = rankings.load_rankings("atp")
                wta_df = rankings.load_rankings("wta")

            self.assertTrue(atp_df["tours"].isna().all())
            self.assertEqual(wta_df["tours"].iloc[0], 12)
            self.assertEqual(atp_df["player_id"].iloc[0], "ATP-1001")
            self.assertEqual(wta_df["player_id"].iloc[0], "WTA-2001")


@unittest.skipUnless(
    (PROCESSED_DIRS["atp"] / "matches.parquet").exists() and (PROCESSED_DIRS["wta"] / "matches.parquet").exists(),
    "base processada da Fase 2 ainda nao foi gerada",
)
class TestProcessedDataIntegration(unittest.TestCase):
    """Valida a base real produzida em data/processed/ pela Fase 2."""

    @classmethod
    def setUpClass(cls):
        cls.atp = pd.read_parquet(PROCESSED_DIRS["atp"] / "matches.parquet")
        cls.wta = pd.read_parquet(PROCESSED_DIRS["wta"] / "matches.parquet")
        cls.combined = pd.concat([cls.atp, cls.wta], ignore_index=True)

    def test_two_rows_per_match_atp_and_wta(self):
        for table, name in [(self.atp, "ATP"), (self.wta, "WTA")]:
            result = validate.check_two_rows_per_match(table)
            self.assertEqual(result["n_matches_with_wrong_row_count"], 0, name)

    def test_opponent_mirroring_atp_and_wta(self):
        for table, name in [(self.atp, "ATP"), (self.wta, "WTA")]:
            result = validate.check_opponent_mirroring(table)
            self.assertEqual(result["n_field_mismatches_total"], 0, (name, result["mismatches_by_field_pair"]))

    def test_no_missing_ids(self):
        for table, name in [(self.atp, "ATP"), (self.wta, "WTA")]:
            result = validate.check_ids(table)
            self.assertEqual(result["n_missing_player_id"], 0, name)
            self.assertEqual(result["n_missing_opponent_id"], 0, name)
            self.assertEqual(result["n_missing_match_id"], 0, name)

    def test_atp_and_wta_player_ids_never_collide(self):
        atp_players = pd.read_parquet(PROCESSED_DIRS["atp"] / "players.parquet")
        wta_players = pd.read_parquet(PROCESSED_DIRS["wta"] / "players.parquet")
        overlap = set(atp_players["player_id"]) & set(wta_players["player_id"])
        self.assertEqual(overlap, set())

    def test_atp_rankings_tours_all_null_wta_has_values(self):
        atp_r = pd.read_parquet(PROCESSED_DIRS["atp"] / "rankings.parquet")
        wta_r = pd.read_parquet(PROCESSED_DIRS["wta"] / "rankings.parquet")
        self.assertTrue(atp_r["tours"].isna().all())
        self.assertTrue(wta_r["tours"].notna().any())

    def test_stat_columns_are_nullable_not_zero_filled(self):
        # coluna deve aceitar <NA>; confirma que dtype e nullable (nao float64 com NaN->0 silencioso)
        self.assertEqual(str(self.combined["aces"].dtype), "Int64")
        self.assertGreater(int(self.combined["aces"].isna().sum()), 0)

    def test_reports_were_generated(self):
        self.assertTrue((REPORTS_DIR / "null_report.csv").exists())
        self.assertTrue((REPORTS_DIR / "usable_matches_report.csv").exists())
        self.assertTrue((REPORTS_DIR / "phase2_diagnostics.json").exists())

    def test_raw_files_untouched_marker(self):
        # a Fase 2 nunca deve escrever em data/raw/; checagem indireta:
        # o manifesto da Fase 1 continua existindo e com 0 issues.
        import json
        from src.ingestion.config import MANIFEST_JSON
        manifest = json.loads(MANIFEST_JSON.read_text(encoding="utf-8"))
        self.assertEqual(manifest["n_issues"], 0)


if __name__ == "__main__":
    unittest.main()
