"""Testes de `src.incremental.agenda_players` (LOTE J, T3). Somente leitura."""

from __future__ import annotations

import unittest

import pandas as pd

from src.incremental import agenda_players as ap
from src.normalization.config import PROCESSED_DIRS

ALCARAZ, SINNER, SWIATEK = "ATP-207989", "ATP-206173", "WTA-216347"


def _resolved(rows: list[tuple]) -> pd.DataFrame:
    """rows: (tour, id_a, raw_a, method_a, id_b, raw_b, method_b)."""
    return pd.DataFrame([
        {"raw_match_seq": i, "tour": t,
         "player_id_a": ia, "player_a_raw": ra, "resolution_method_a": ma,
         "player_id_b": ib, "player_b_raw": rb, "resolution_method_b": mb}
        for i, (t, ia, ra, ma, ib, rb, mb) in enumerate(rows)
    ])


class TestAgendaPlayersSynthetic(unittest.TestCase):
    def setUp(self) -> None:
        self.resolved = _resolved([
            ("ATP", ALCARAZ, "C. Alcaraz", "alias", SINNER, "Jannik Sinner", "exact"),
            ("ATP", ALCARAZ, "Carlos Alcaraz", "exact", None, "Zzz Nobody", "unresolved"),
            ("ATP", SINNER, "Jannik Sinner", "exact", None, "Qqq Nobody", "unresolved"),
            ("WTA", SWIATEK, "Iga Swiatec", "fuzzy_review", None, "Zzz Nobody", "unresolved"),
        ])
        self.out = ap.extract_agenda_players(self.resolved)

    def test_columns(self) -> None:
        self.assertEqual(list(self.out.columns), ap.AGENDA_PLAYER_COLUMNS)

    def test_repeated_player_appears_once(self) -> None:
        self.assertEqual((self.out["player_id"] == SINNER).sum(), 1)
        self.assertEqual((self.out["player_id"] == ALCARAZ).sum(), 1)
        sinner = self.out[self.out["player_id"] == SINNER].iloc[0]
        self.assertEqual(sinner["n_agenda_matches"], 2)

    def test_exact_preserved(self) -> None:
        sinner = self.out[self.out["player_id"] == SINNER].iloc[0]
        self.assertEqual(sinner["resolution_method"], "exact")
        self.assertTrue(sinner["trusted"])

    def test_alias_preserved_and_least_trusted_method_wins(self) -> None:
        alcaraz = self.out[self.out["player_id"] == ALCARAZ].iloc[0]
        self.assertEqual(alcaraz["resolution_method"], "alias")
        self.assertEqual(alcaraz["resolution_methods"], "alias|exact")
        self.assertTrue(alcaraz["trusted"])

    def test_fuzzy_review_marked_untrusted(self) -> None:
        swiatek = self.out[self.out["player_id"] == SWIATEK].iloc[0]
        self.assertEqual(swiatek["resolution_method"], "fuzzy_review")
        self.assertFalse(swiatek["trusted"])

    def test_unresolved_marked_and_not_deduplicated_by_name(self) -> None:
        unresolved = self.out[self.out["resolution_method"] == "unresolved"]
        # "Zzz Nobody" aparece em ATP e WTA e 2x no total: sem id, nunca deduplica por nome
        self.assertEqual(len(unresolved), 3)
        self.assertTrue(unresolved["player_id"].isna().all())
        self.assertFalse(unresolved["trusted"].any())

    def test_name_hand_dob_come_from_players_parquet(self) -> None:
        players = pd.read_parquet(PROCESSED_DIRS["atp"] / "players.parquet").set_index("player_id")
        alcaraz = self.out[self.out["player_id"] == ALCARAZ].iloc[0]
        self.assertEqual(alcaraz["player_name"], players.loc[ALCARAZ, "name"])
        self.assertNotEqual(alcaraz["player_name"], "C. Alcaraz")
        self.assertEqual(alcaraz["hand"], players.loc[ALCARAZ, "hand"])
        self.assertEqual(alcaraz["dob"], players.loc[ALCARAZ, "dob"])

    def test_sackmann_last_is_last_base_date(self) -> None:
        base = pd.read_parquet(PROCESSED_DIRS["atp"] / "matches.parquet", columns=["player_id", "tournament_date"])
        expected = base.loc[base["player_id"] == SINNER, "tournament_date"].max()
        sinner = self.out[self.out["player_id"] == SINNER].iloc[0]
        self.assertEqual(sinner["sackmann_last"], expected)

    def test_deterministic(self) -> None:
        again = ap.extract_agenda_players(self.resolved.iloc[::-1].reset_index(drop=True))
        pd.testing.assert_frame_equal(self.out, again)


@unittest.skipUnless(ap.RESOLVED_PATH.exists(), "partidas_resolvidas da Fase 8 ausente")
class TestAgendaPlayersRealAgenda(unittest.TestCase):
    def test_current_agenda_27_matches_54_players(self) -> None:
        resolved = pd.read_parquet(ap.RESOLVED_PATH)
        if len(resolved) != 27:
            self.skipTest(f"agenda atual mudou ({len(resolved)} partidas), teste fixado em 27")
        out = ap.load_agenda_players()
        self.assertEqual(len(out), 54)
        self.assertEqual(out["player_id"].nunique(), 54)
        self.assertEqual(out["tour"].value_counts().to_dict(), {"ATP": 38, "WTA": 16})
        self.assertTrue(out["trusted"].all())
        self.assertTrue(out["player_name"].notna().all())


if __name__ == "__main__":
    unittest.main()
