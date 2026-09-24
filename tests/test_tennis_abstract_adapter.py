"""Testes do adapter endurecido do Tennis Abstract (LOTE J, T5).

Somente leitura: usa a base Sackmann, players.parquet e o cache TA existente,
nunca escreve em overlay ou cache."""

from __future__ import annotations

import json
import unittest

import pandas as pd

from src.incremental import config as inc_cfg
from src.incremental import identity_new as ident_new
from src.incremental.tennis_abstract_adapter import (
    AcceptancePolicy,
    CollectedPlayer,
    load_acceptance_policy,
    parse_matchid,
    parse_ta_match_row,
    process_tennis_abstract_matches,
)
from src.incremental.tennis_abstract_source import MATCHHEAD_COLUMNS
from src.normalization.config import PROCESSED_DIRS
from src.normalization.matches import OUTPUT_COLUMNS

ALCARAZ_ID, SINNER_ID = "ATP-207989", "ATP-206173"
ALCARAZ_CACHE = inc_cfg.TA_CACHE_DIR / "ATP" / "CarlosAlcaraz.json"


def _players_atp() -> pd.DataFrame:
    return pd.read_parquet(PROCESSED_DIRS["atp"] / "players.parquet")


def _row(**kwargs) -> dict[str, str]:
    base = {col: "" for col in MATCHHEAD_COLUMNS}
    base.update({
        "date": "20260615", "tourn": "Halle", "surf": "Grass", "level": "A", "wl": "W",
        "rank": "2", "round": "F", "score": "7-6(4) 6-4", "max": "3",
        "opp": "Jannik Sinner", "orank": "1", "ohand": "L", "time": "115",
        "matchid": "2026-500-101",
        "aces": "12", "dfs": "2", "pts": "75", "firsts": "52", "fwon": "42", "swon": "14",
        "games": "11", "saved": "3", "chances": "4",
        "oaces": "15", "odfs": "3", "opts": "80", "ofirsts": "55", "ofwon": "40", "oswon": "12",
        "ogames": "11", "osaved": "4", "ochances": "6",
    })
    base.update(kwargs)
    return base


class TestAdapterHardening(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.players = _players_atp()
        cls.policy = load_acceptance_policy("ATP")
        rec = cls.players.set_index("player_id").loc[ALCARAZ_ID]
        cls.alcaraz = CollectedPlayer(ALCARAZ_ID, str(rec["name"]), str(rec["hand"]))
        cls.sinner_hand = str(cls.players.set_index("player_id").loc[SINNER_ID, "hand"])

    def _parse(self, **kwargs):
        return parse_ta_match_row(_row(**kwargs), self.alcaraz, "ATP", self.policy)

    def _process(self, payloads, **kwargs):
        return process_tennis_abstract_matches(
            payloads, "ATP", cutoff_date="2026-05-25", players_df=self.players, policy=self.policy, **kwargs,
        )

    # --- matchid ---
    def test_missing_matchid_rejected(self) -> None:
        row, status = self._parse(matchid="", matchnum="7")
        self.assertIsNone(row)
        self.assertEqual(status, "MISSING_MATCHID")

    def test_invalid_matchid_rejected(self) -> None:
        for bad in ("2026520101", "2026-500-DC", "-12"):
            row, status = self._parse(matchid=bad)
            self.assertIsNone(row, bad)
            self.assertEqual(status, "INVALID_MATCHID", bad)

    def test_davis_cup_matchid_cut_at_last_hyphen(self) -> None:
        self.assertEqual(
            parse_matchid("2024-M-DC-2024-FLS-M-NED-ESP-01-002"),
            ("2024-M-DC-2024-FLS-M-NED-ESP-01", 2),
        )
        row, status = self._parse(matchid="2024-M-DC-2024-FLS-M-NED-ESP-01-002", level="D", round="RR",
                                  date="20260915")
        self.assertEqual(status, "VALID")
        self.assertEqual(row["tourney_id"], "2024-M-DC-2024-FLS-M-NED-ESP-01")
        self.assertEqual(row["match_num"], 2)

    def test_davis_cup_matchid_equals_sackmann_match_id(self) -> None:
        base = pd.read_parquet(PROCESSED_DIRS["atp"] / "matches.parquet", columns=["match_id"])
        tid, num = parse_matchid("2024-M-DC-2024-FLS-2-M-B-CZE-ESP-01-002")
        self.assertIn(f"ATP:{tid}:{num}", set(base["match_id"]))

    def test_regular_matchid(self) -> None:
        self.assertEqual(parse_matchid("2026-520-223"), ("2026-520", 223))

    # --- best_of / level / round vindos direto do TA ---
    def test_best_of_comes_from_max(self) -> None:
        row5, _ = self._parse(max="5", level="G", round="R128")
        row3, _ = self._parse(max="3", level="G", round="R128")
        self.assertEqual(row5["best_of"], 5)
        self.assertEqual(row3["best_of"], 3)  # nunca derivado do nível

    def test_level_and_round_preserved(self) -> None:
        row, status = self._parse(level="M", round="QF")
        self.assertEqual(status, "VALID")
        self.assertEqual(row["tourney_level"], "M")
        self.assertEqual(row["round"], "QF")

    # --- sem defaults inventados ---
    def test_no_invented_defaults(self) -> None:
        cases = {
            "surf": "MISSING_SURFACE", "round": "MISSING_ROUND", "level": "MISSING_LEVEL",
            "max": "INVALID_BEST_OF", "score": "MISSING_SCORE",
        }
        for field, reason in cases.items():
            row, status = self._parse(**{field: ""})
            self.assertIsNone(row, field)
            self.assertEqual(status, reason, field)

    def test_optional_fields_stay_missing_not_filled(self) -> None:
        row, status = self._parse(time="", orank="", ohand="")
        self.assertEqual(status, "VALID")
        self.assertIsNone(row["minutes"])
        self.assertIsNone(row["loser_rank"])
        self.assertIsNone(row["loser_hand"])

    def test_invalid_best_of_value_rejected(self) -> None:
        row, status = self._parse(max="4")
        self.assertIsNone(row)
        self.assertEqual(status, "INVALID_BEST_OF")

    # --- política de nível / rodada ---
    def test_level_out_of_policy_rejected(self) -> None:
        for lvl in ("C", "15", "S"):
            row, status = self._parse(level=lvl)
            self.assertIsNone(row, lvl)
            self.assertEqual(status, f"LEVEL_OUT_OF_POLICY:{lvl}")

    def test_qualifying_round_out_of_policy_rejected(self) -> None:
        # qualifying de Slam vem do TA como level G, max 3, round Q1-Q3
        for rnd in ("Q1", "Q2", "Q3"):
            row, status = self._parse(level="G", max="3", round=rnd)
            self.assertIsNone(row, rnd)
            self.assertEqual(status, f"ROUND_OUT_OF_POLICY:{rnd}")

    def test_policy_derived_from_base(self) -> None:
        self.assertTrue({"A", "D", "F", "G", "M", "O"} <= self.policy.levels)
        self.assertNotIn("C", self.policy.levels)
        self.assertFalse({"Q1", "Q2", "Q3", "Q4"} & self.policy.rounds)

    def test_incomplete_stats_rejected_never_zero(self) -> None:
        row, status = self._parse(ochances="")
        self.assertIsNone(row)
        self.assertTrue(status.startswith("INCOMPLETE_STATS:l_bpFaced"))

    # --- identidade ---
    def test_collected_player_uses_known_id_and_base_hand(self) -> None:
        row, _ = self._parse(wl="W")
        self.assertEqual(row["winner_id"], "207989")
        self.assertEqual(row["winner_name"], self.alcaraz.name)
        self.assertEqual(row["winner_hand"], self.alcaraz.hand)
        self.assertEqual(row["winner_resolution_method"], "collected_player_id")

    def test_player_is_not_re_resolved_by_name(self) -> None:
        # nome do payload irrelevante: id + nome canônico vêm do player_id
        payload = {"player": {"name": "qualquer grafia", "tour": "ATP", "player_id": ALCARAZ_ID},
                   "matches": [_row()]}
        res = self._process([payload])
        t = res["transformed_df"]
        own = t[t["player_id"] == ALCARAZ_ID]
        self.assertEqual(len(own), 1)
        self.assertEqual(own["player_name"].iloc[0], self.alcaraz.name)

    def test_opponent_hand_comes_from_base_when_trusted(self) -> None:
        # ohand do TA = "L", base diz a mão real do Sinner
        payload = {"player": {"tour": "ATP", "player_id": ALCARAZ_ID}, "matches": [_row(ohand="L")]}
        t = self._process([payload])["transformed_df"]
        sinner = t[t["player_id"] == SINNER_ID]
        self.assertEqual(sinner["player_hand"].iloc[0], self.sinner_hand)

    def test_unknown_player_id_rejected(self) -> None:
        payload = {"player": {"name": "Carlos Alcaraz", "tour": "ATP"}, "matches": [_row()]}
        res = self._process([payload])
        self.assertEqual(res["valid_count"], 0)
        self.assertEqual(res["rejected_reasons"], {"UNKNOWN_PLAYER_ID": 1})

    def test_fuzzy_review_not_counted_as_resolved(self) -> None:
        toy = pd.DataFrame({
            "player_id": ["ATP-1"], "player_id_raw": ["1"], "name": ["Jelena Ostapenko"],
            "name_first": ["Jelena"], "name_last": ["Ostapenko"],
        })
        res = ident_new.resolve_player_names(pd.Series(["Jelena Ostapenco"]), toy)
        self.assertEqual(res["method"].iloc[0], "fuzzy_review")
        self.assertTrue(res["id_raw"].iloc[0].startswith("NEW-"))
        self.assertNotEqual(res["id_raw"].iloc[0], "1")

    def test_fuzzy_review_in_resolve_incremental_players_gets_new_id(self) -> None:
        toy = pd.DataFrame({
            "player_id": ["ATP-1", "ATP-2"], "player_id_raw": ["1", "2"],
            "name": ["Jelena Ostapenko", "Taylah Preston"],
            "name_first": ["Jelena", "Taylah"], "name_last": ["Ostapenko", "Preston"],
        })
        raw = pd.DataFrame([{"winner_name": "Jelena Ostapenco", "loser_name": "Taylah Preston"}])
        out = ident_new.resolve_incremental_players(raw, "ATP", toy)
        self.assertEqual(out["winner_resolution_method"].iloc[0], "fuzzy_review")
        self.assertTrue(out["winner_id"].iloc[0].startswith("NEW-"))
        self.assertEqual(out["loser_id"].iloc[0], "2")

    # --- dedupe por match_id, independente de nome/case ---
    def test_cross_player_duplicate_with_case_variation(self) -> None:
        a = {"player": {"tour": "ATP", "player_id": ALCARAZ_ID},
             "matches": [_row(wl="W", opp="JANNIK SINNER")]}
        b = {"player": {"tour": "ATP", "player_id": SINNER_ID},
             "matches": [_row(wl="L", opp="carlos alcaraz", aces="15", dfs="3", pts="80", firsts="55",
                              fwon="40", swon="12", games="11", saved="4", chances="6",
                              oaces="12", odfs="2", opts="75", ofirsts="52", ofwon="42", oswon="14",
                              ogames="11", osaved="3", ochances="4", rank="1", orank="2")]}
        res = self._process([a, b])
        self.assertEqual(res["valid_count"], 1)
        self.assertEqual(res["rejected_reasons"].get("DUPLICATE_CROSS_PLAYER"), 1)
        self.assertNotIn("DUPLICATE_CONFLICT", res["rejected_reasons"])
        t = res["transformed_df"]
        self.assertEqual(len(t), 2)
        self.assertEqual(set(t["player_id"]), {ALCARAZ_ID, SINNER_ID})
        self.assertEqual(t["match_id"].nunique(), 1)

    def test_duplicate_fills_opponent_id_from_collected_page(self) -> None:
        # nome irreconhecível na página do Alcaraz; a página do Sinner traz o id
        a = {"player": {"tour": "ATP", "player_id": ALCARAZ_ID},
             "matches": [_row(wl="W", opp="Zzz Irreconhecivel")]}
        b = {"player": {"tour": "ATP", "player_id": SINNER_ID},
             "matches": [_row(wl="L", opp="Carlos Alcaraz")]}
        t = self._process([a, b])["transformed_df"]
        self.assertEqual(set(t["player_id"]), {ALCARAZ_ID, SINNER_ID})

    def test_duplicate_with_different_stats_flagged_conflict(self) -> None:
        a = {"player": {"tour": "ATP", "player_id": ALCARAZ_ID}, "matches": [_row(wl="W")]}
        b = {"player": {"tour": "ATP", "player_id": SINNER_ID},
             "matches": [_row(wl="L", opp="Carlos Alcaraz", aces="99")]}
        res = self._process([a, b])
        self.assertEqual(res["rejected_reasons"].get("DUPLICATE_CONFLICT"), 1)
        self.assertEqual(res["valid_count"], 1)

    def test_per_player_counts(self) -> None:
        payload = {"player": {"tour": "ATP", "player_id": ALCARAZ_ID}, "matches": [
            _row(), _row(matchid="2026-500-102", level="C"), _row(date="20260101", matchid="2026-1-1"),
        ]}
        stats = self._process([payload])["per_player"][ALCARAZ_ID]
        self.assertEqual(stats["n_post_cutoff"], 2)
        self.assertEqual(stats["n_valid"], 1)
        self.assertEqual(stats["rejected_reasons"], {"LEVEL_OUT_OF_POLICY:C": 1})

    def test_output_schema(self) -> None:
        payload = {"player": {"tour": "ATP", "player_id": ALCARAZ_ID}, "matches": [_row()]}
        t = self._process([payload])["transformed_df"]
        self.assertEqual(list(t.columns), OUTPUT_COLUMNS)


@unittest.skipUnless(ALCARAZ_CACHE.exists(), "cache TA do Alcaraz ausente")
class TestAdapterOnRealCache(unittest.TestCase):
    def test_alcaraz_post_cutoff_matches(self) -> None:
        payload = json.loads(ALCARAZ_CACHE.read_text(encoding="utf-8"))
        payload["player"]["player_id"] = ALCARAZ_ID
        res = process_tennis_abstract_matches([payload], "ATP", cutoff_date="2026-05-25",
                                              players_df=_players_atp())
        t = res["transformed_df"]
        own = t[t["player_id"] == ALCARAZ_ID]
        self.assertEqual(res["total_post_cutoff"], res["valid_count"] + res["rejected_count"])
        self.assertTrue((own["tourney_level"] == "G").all())
        self.assertTrue((own["best_of"] == 5).all())  # Slams masculinos: max=5 no TA
        self.assertTrue(own["match_id"].is_unique)
        self.assertTrue((t.groupby("match_id").size() == 2).all())


if __name__ == "__main__":
    unittest.main()
