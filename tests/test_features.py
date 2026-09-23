"""Testes da Fase 3 (features point-in-time).

Grupos:
  1. Parser de score (casos reais encontrados na base + casos sinteticos).
  2. Anti-leakage em dado sintetico (item 11 da instrucao): a partida atual
     nunca entra nas proprias features; partidas futuras nunca entram;
     janelas terminam antes da data da partida; superficie usa so partidas
     anteriores da mesma superficie; ATP/WTA nunca se misturam.
  3. Reconstrucao manual de uma feature real (item 11, "testes manuais").
  4. Integracao sobre a base real gerada em data/processed/features/.
"""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.features import metrics as metrics_mod  # noqa: E402
from src.features.config import FEATURES_TOUR_DIRS  # noqa: E402
from src.features.matchup import build_matchup_table  # noqa: E402
from src.features.profile import build_player_profile  # noqa: E402
from src.features.score_parser import parse_score  # noqa: E402
from src.normalization.config import PROCESSED_DIRS  # noqa: E402


# ---------------------------------------------------------------------------
# geracao de dado sintetico no formato da tabela de partidas da Fase 2
# ---------------------------------------------------------------------------

_BASE_STAT_COLS = [
    "aces", "double_faults", "service_points", "first_serves_in",
    "first_serve_points_won", "second_serve_points_won", "service_games",
    "break_points_saved", "break_points_faced",
]


def _mirror_row(tour, match_id, date, surface, p1, p2, p1_stats, p2_stats, winner="p1"):
    """Retorna as DUAS linhas (perspectiva p1 e p2) de uma partida, no
    schema de saida da Fase 2, com devolucao espelhada corretamente."""

    def _row(pid, opp, own, opp_stats, result):
        r = {
            "match_id": match_id, "tour": tour, "tournament": "Synthetic",
            "tourney_id": match_id.split(":")[1], "tournament_date": pd.Timestamp(date),
            "round": "R32", "surface": surface, "tourney_level": "A", "best_of": 3,
            "player_id": pid, "opponent_id": opp, "player_name": pid, "opponent_name": opp,
            "player_rank": 50, "opponent_rank": 60, "player_rank_points": 1000, "opponent_rank_points": 900,
            "result": result, "score": "6-4 6-3",
        }
        for c in _BASE_STAT_COLS:
            r[c] = own[c]
        r["opponent_aces"] = opp_stats["aces"]
        r["opponent_double_faults"] = opp_stats["double_faults"]
        r["return_points"] = opp_stats["service_points"]
        r["opponent_first_serves_in"] = opp_stats["first_serves_in"]
        r["opponent_first_serve_points_won"] = opp_stats["first_serve_points_won"]
        r["opponent_second_serve_points_won"] = opp_stats["second_serve_points_won"]
        r["opponent_service_games"] = opp_stats["service_games"]
        r["break_points_created"] = opp_stats["break_points_faced"]
        r["break_points_converted"] = opp_stats["break_points_faced"] - opp_stats["break_points_saved"]
        return r

    r1 = _row(p1, p2, p1_stats, p2_stats, "W" if winner == "p1" else "L")
    r2 = _row(p2, p1, p2_stats, p1_stats, "W" if winner == "p2" else "L")
    return [r1, r2]


def _stats(aces=5, df=2, sp=60, f1in=35, f1w=25, f2w=12, svgms=10, bps=2, bpf=4):
    return {
        "aces": aces, "double_faults": df, "service_points": sp, "first_serves_in": f1in,
        "first_serve_points_won": f1w, "second_serve_points_won": f2w, "service_games": svgms,
        "break_points_saved": bps, "break_points_faced": bpf,
    }


def _build_synthetic_matches(tour="atp"):
    """Jogador P joga 5 partidas cronologicas contra R1..R5, alternando
    superficie Hard/Clay, com estatisticas DIFERENTES em cada uma (para
    poder checar somas parciais sem ambiguidade)."""

    rows = []
    surfaces = ["Hard", "Clay", "Hard", "Hard", "Clay"]
    dates = ["2023-01-01", "2023-02-01", "2023-03-01", "2023-04-01", "2023-05-01"]
    p_stats = [
        _stats(aces=2, sp=50), _stats(aces=4, sp=55), _stats(aces=6, sp=60),
        _stats(aces=3, sp=52), _stats(aces=8, sp=65),
    ]
    for i in range(5):
        opp = f"{tour.upper()}-R{i+1}"
        mid = f"{tour.upper()}:2023-100:{i+1}"
        rows += _mirror_row(
            tour.upper(), mid, dates[i], surfaces[i], f"{tour.upper()}-P", opp,
            p_stats[i], _stats(aces=3, sp=58), winner="p1",
        )
    return pd.DataFrame(rows)


class TestScoreParser(unittest.TestCase):
    def test_completed_two_sets(self):
        r = parse_score("6-4 6-3")
        self.assertEqual(r.status, "completed")
        self.assertTrue(r.complete)
        self.assertEqual(r.total_games, 19)
        self.assertEqual((r.sets_won_winner, r.sets_won_loser), (2, 0))

    def test_tiebreak_counted(self):
        r = parse_score("7-6(4) 6-4")
        self.assertTrue(r.has_tiebreak)
        self.assertEqual(r.n_tiebreaks, 1)
        self.assertEqual(r.total_games, 23)

    def test_walkover(self):
        r = parse_score("W/O")
        self.assertEqual(r.status, "walkover")
        self.assertFalse(r.complete)
        self.assertIsNone(r.total_games)

    def test_retirement_mid_set_not_invented(self):
        r = parse_score("4-6 6-3 2-1 RET")
        self.assertEqual(r.status, "retired")
        self.assertFalse(r.complete)
        self.assertTrue(r.has_partial_trailing_set)
        # so os 2 sets REALMENTE concluidos entram na soma; "2-1" nao e inventado como set
        self.assertEqual(r.n_sets_completed, 2)
        self.assertEqual(r.total_games, 19)

    def test_retirement_with_suffix_code(self):
        r = parse_score("7-6(0) 0-2 RET+H61")
        self.assertEqual(r.status, "retired")
        self.assertFalse(r.complete)

    def test_default_with_period(self):
        r = parse_score("6-5 Def.")
        self.assertEqual(r.status, "defaulted")
        self.assertFalse(r.complete)

    def test_match_tiebreak_bracket_completed(self):
        r = parse_score("3-6 7-6(4) [10-2]")
        self.assertTrue(r.complete)
        self.assertTrue(r.has_match_tiebreak)
        self.assertEqual(r.n_match_tiebreaks_completed, 1)
        self.assertEqual(r.sets_won_winner, 2)

    def test_incomplete_match_tiebreak_not_invented(self):
        r = parse_score("6-2 5-7 [0-1]")
        self.assertFalse(r.complete)
        self.assertTrue(r.has_partial_trailing_set)

    def test_missing_and_garbage(self):
        self.assertEqual(parse_score(None).status, "missing")
        self.assertEqual(parse_score("").status, "missing")
        self.assertEqual(parse_score("garbage text").status, "unparseable")


class TestAntiLeakage(unittest.TestCase):
    def setUp(self):
        self.matches = _build_synthetic_matches("atp")
        self.profile = build_player_profile(self.matches)
        self.p_rows = self.profile[self.profile["player_id"] == "ATP-P"].sort_values("tournament_date").reset_index(drop=True)

    def test_current_match_excluded_from_own_features(self):
        # 1a partida do jogador: nao pode haver NENHUMA partida anterior
        row0 = self.p_rows.iloc[0]
        self.assertEqual(row0["prior_matches_career"], 0)
        self.assertTrue(pd.isna(row0["player_serve_ace_rate_career"]))
        self.assertTrue(row0["player_cold_start"])

    def test_career_prior_matches_exact_count(self):
        # a k-esima partida (0-indexada) deve ter exatamente k partidas anteriores
        for k in range(5):
            self.assertEqual(self.p_rows.iloc[k]["prior_matches_career"], k)

    def test_career_ace_rate_matches_manual_sum(self):
        # partida 3 (indice 3, 0-indexada): prior = partidas 0,1,2 -> aces 2+4+6=12, sp 50+55+60=165
        row = self.p_rows.iloc[3]
        self.assertEqual(row["prior_matches_career"], 3)
        expected = (2 + 4 + 6) / (50 + 55 + 60)
        self.assertAlmostEqual(row["player_serve_ace_rate_career"], expected, places=10)

    def test_future_matches_never_leak_in(self):
        # recomputar so com as 3 primeiras partidas do jogador; a feature da
        # partida 2 (0-indexada) deve ser IDENTICA com ou sem as partidas futuras
        truncated = self.matches[self.matches["match_id"].isin(
            [f"ATP:2023-100:{i+1}" for i in range(3)]
        )].reset_index(drop=True)
        prof_trunc = build_player_profile(truncated)
        row_full = self.p_rows.iloc[2]
        row_trunc = prof_trunc[
            (prof_trunc["player_id"] == "ATP-P") & (prof_trunc["match_id"] == row_full["match_id"])
        ].iloc[0]
        self.assertEqual(row_full["prior_matches_career"], row_trunc["prior_matches_career"])
        self.assertAlmostEqual(
            row_full["player_serve_ace_rate_career"], row_trunc["player_serve_ace_rate_career"], places=10
        )

    def test_rolling_window_ends_before_match_date(self):
        # partida 4 (2023-05-01): last365d deve incluir as 4 anteriores (todas
        # dentro de 365 dias); se movermos a partida 0 para fora da janela
        # (2 anos antes), ela deve sumir do last365d mas continuar no career
        far_past = self.matches.copy()
        mask = far_past["match_id"] == "ATP:2023-100:1"
        far_past.loc[mask, "tournament_date"] = pd.Timestamp("2020-01-01")
        prof2 = build_player_profile(far_past)
        row4 = prof2[(prof2["player_id"] == "ATP-P") & (prof2["match_id"] == "ATP:2023-100:5")].iloc[0]
        self.assertEqual(row4["prior_matches_career"], 4)  # career inclui as 4
        self.assertEqual(row4["prior_matches_last365d"], 3)  # last365d exclui a de 2020

    def test_surface_career_uses_only_same_surface_prior(self):
        # partida 4 (indice 4, Clay): superficies anteriores = Hard,Clay,Hard,Hard
        # -> so 1 partida Clay anterior (indice 1)
        row4 = self.p_rows.iloc[4]
        self.assertEqual(row4["surface_prior_matches"], 1)
        expected = 4 / 55  # aces/sp da partida indice 1 (unica Clay anterior)
        self.assertAlmostEqual(row4["player_serve_ace_rate_surface_career"], expected, places=10)

    def test_last_n_window_caps_correctly(self):
        matches10 = []
        rows = []
        for i in range(15):
            mid = f"ATP:2023-200:{i+1}"
            date = pd.Timestamp("2023-01-01") + pd.Timedelta(days=10 * i)
            rows += _mirror_row(
                "ATP", mid, date, "Hard", "ATP-Q", f"ATP-S{i+1}",
                _stats(aces=1, sp=10), _stats(aces=0, sp=10), winner="p1",
            )
        matches = pd.DataFrame(rows)
        prof = build_player_profile(matches)
        q_rows = prof[prof["player_id"] == "ATP-Q"].sort_values("tournament_date").reset_index(drop=True)
        last_row = q_rows.iloc[14]  # 15a partida: 14 anteriores, last10 deve pegar so as ultimas 10
        self.assertEqual(last_row["prior_matches_career"], 14)
        self.assertEqual(last_row["prior_matches_last10"], 10)

    def test_atp_and_wta_never_mix_even_if_same_player_id_suffix(self):
        atp_matches = _build_synthetic_matches("atp")
        wta_matches = _build_synthetic_matches("wta")
        combined = pd.concat([atp_matches, wta_matches], ignore_index=True)
        prof = build_player_profile(combined)
        atp_p = prof[prof["player_id"] == "ATP-P"].sort_values("tournament_date").reset_index(drop=True)
        wta_p = prof[prof["player_id"] == "WTA-P"].sort_values("tournament_date").reset_index(drop=True)
        # mesmo com stats identicas por construcao, cada player_id (ja
        # escopado por tour na Fase 2) forma seu proprio grupo -- checagem
        # de que o motor de agregacao nao teria como misturar ATP/WTA
        # mesmo que alguem concatenasse as tabelas por engano
        self.assertEqual(atp_p.iloc[3]["prior_matches_career"], wta_p.iloc[3]["prior_matches_career"])
        self.assertAlmostEqual(
            atp_p.iloc[3]["player_serve_ace_rate_career"], wta_p.iloc[3]["player_serve_ace_rate_career"], places=10
        )
        # e as duas series continuam independentes: alterar uma partida ATP
        # nao pode mudar nada do lado WTA
        combined2 = combined.copy()
        combined2.loc[combined2["match_id"] == "ATP:2023-100:1", "aces"] = 99
        prof2 = build_player_profile(combined2)
        wta_p2 = prof2[prof2["player_id"] == "WTA-P"].sort_values("tournament_date").reset_index(drop=True)
        self.assertAlmostEqual(
            wta_p.iloc[3]["player_serve_ace_rate_career"], wta_p2.iloc[3]["player_serve_ace_rate_career"], places=10
        )


class TestMatchupSelfJoin(unittest.TestCase):
    def setUp(self):
        self.matches = _build_synthetic_matches("atp")
        self.profile = build_player_profile(self.matches)
        self.full = build_matchup_table(self.profile)

    def test_opponent_columns_mirror_opponent_own_row(self):
        for mid in self.full["match_id"].unique():
            rows = self.full[self.full["match_id"] == mid]
            r1, r2 = rows.iloc[0], rows.iloc[1]
            a = r1["opponent_serve_ace_rate_career"]
            b = r2["player_serve_ace_rate_career"]
            if pd.isna(a) and pd.isna(b):
                continue
            self.assertAlmostEqual(a, b, places=10)

    def test_comparative_matchup_columns_present_and_finite_or_nan(self):
        for w in ["career", "surface_career", "last50"]:
            col = f"matchup_ace_rate_vs_allowed_{w}"
            self.assertIn(col, self.full.columns)

    def test_opponent_adjustment_columns_present(self):
        for name in ["opponent_adjusted_ace_rate", "ace_suppression",
                     "opponent_adjusted_hold_pct", "opponent_adjusted_break_pct"]:
            for w in ["career", "last50"]:
                self.assertIn(f"{name}_{w}", self.full.columns)


class TestManualReconstructionRealData(unittest.TestCase):
    """Item 11: reconstrucao manual de uma feature real a partir das
    partidas anteriores, usando a base real (nao sintetica)."""

    @classmethod
    def setUpClass(cls):
        matches_path = PROCESSED_DIRS["atp"] / "matches.parquet"
        if not matches_path.exists():
            raise unittest.SkipTest("base da Fase 2 nao encontrada")
        cls.matches = pd.read_parquet(matches_path).sort_values(
            ["tournament_date", "tourney_id", "match_id", "result"],
            ascending=[True, True, True, False],
        ).reset_index(drop=True)
        cls.profile = build_player_profile(cls.matches)

    def test_manual_ace_rate_reconstruction(self):
        counts = self.matches["player_id"].value_counts()
        pid = counts[counts >= 30].index[0]
        sub = self.matches[self.matches["player_id"] == pid].sort_values(
            ["tournament_date", "tourney_id", "match_id"]
        ).reset_index(drop=True)
        subprof = self.profile[self.profile["player_id"] == pid].sort_values(
            ["tournament_date", "tourney_id", "match_id"]
        ).reset_index(drop=True)

        idx = 15
        prior = sub.iloc[:idx]
        manual_aces = prior["aces"].sum(skipna=True)
        manual_sp = prior["service_points"].sum(skipna=True)
        manual_rate = manual_aces / manual_sp if manual_sp > 0 else None

        row = subprof.iloc[idx]
        self.assertEqual(row["prior_matches_career"], idx)
        if manual_sp > 0:
            self.assertAlmostEqual(row["player_serve_ace_rate_career"], manual_rate, places=10)
        else:
            self.assertTrue(pd.isna(row["player_serve_ace_rate_career"]))


@unittest.skipUnless(
    (FEATURES_TOUR_DIRS["atp"] / "player_match_features.parquet").exists()
    and (FEATURES_TOUR_DIRS["wta"] / "player_match_features.parquet").exists(),
    "base de features da Fase 3 ainda nao foi gerada",
)
class TestFeaturesIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.atp = pd.read_parquet(FEATURES_TOUR_DIRS["atp"] / "player_match_features.parquet")
        cls.wta = pd.read_parquet(FEATURES_TOUR_DIRS["wta"] / "player_match_features.parquet")

    def test_row_counts_match_phase2(self):
        atp_matches = pd.read_parquet(PROCESSED_DIRS["atp"] / "matches.parquet")
        self.assertEqual(len(self.atp), len(atp_matches))

    def test_no_atp_wta_player_id_overlap(self):
        overlap = set(self.atp["player_id"]) & set(self.wta["player_id"])
        self.assertEqual(overlap, set())

    def test_cold_start_matches_are_null_not_zero(self):
        cold = self.atp[self.atp["player_cold_start"]]
        self.assertGreater(len(cold), 0)
        self.assertTrue(cold["player_serve_ace_rate_career"].isna().all())

    def test_rate_columns_within_plausible_bounds(self):
        for c in ["player_serve_ace_rate_career", "player_serve_hold_pct_career",
                  "player_return_break_pct_career"]:
            vals = self.atp[c].dropna()
            self.assertTrue((vals >= 0).all() and (vals <= 1).all(), c)


if __name__ == "__main__":
    unittest.main()
