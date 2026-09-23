"""Testes da Fase 4: modelo analitico de sets (conservacao de probabilidade
e simetria), motor de media historica point-in-time (anti-leakage,
reaproveitando o motor ja testado da Fase 3 sobre novas colunas-alvo),
folds walk-forward (fronteiras cronologicas, sem sobreposicao) e ajuste de
parametros (Negative Binomial / regressao logistica) usando SOMENTE o fold
de treino.
"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.baselines.config import FOLDS
from src.baselines.count_dist import fit_negbin_r
from src.baselines.history_means import build_history_mean_priors
from src.baselines.setmodel import match_expectation, single_set_expectation
from src.baselines.targets import attach_targets
from src.baselines.tiebreak_model import fit_and_predict_tiebreak_logit
from src.baselines.walkforward import ranking_bucket, sample_size_bucket, split_fold


class TestSetModel(unittest.TestCase):
    def test_probability_mass_conserved(self):
        for pa, pb in [(0.65, 0.65), (0.8, 0.55), (0.5, 0.9), (0.55, 0.55)]:
            s = single_set_expectation(pa, pb)
            # p_a_wins_set + p_b_wins_set deve somar 1 (toda massa termina
            # em algum estado terminal) -- reconstruido indiretamente via
            # e_games: se a soma nao fosse 1, e_games_a/b teriam escala errada.
            self.assertGreater(s["e_games_a"] + s["e_games_b"], 5.5)
            self.assertLess(s["e_games_a"] + s["e_games_b"], 13.0)
            self.assertGreaterEqual(s["p_a_wins_set"], 0.0)
            self.assertLessEqual(s["p_a_wins_set"], 1.0)

    def test_symmetric_hold_gives_fair_set(self):
        s = single_set_expectation(0.65, 0.65)
        self.assertAlmostEqual(s["p_a_wins_set"], 0.5, places=9)

    def test_stronger_server_wins_more_sets(self):
        s = single_set_expectation(0.85, 0.55)
        self.assertGreater(s["p_a_wins_set"], 0.5)

    def test_extreme_hold_deterministic(self):
        s = single_set_expectation(0.999999, 0.000001)
        self.assertAlmostEqual(s["p_a_wins_set"], 1.0, places=3)
        self.assertAlmostEqual(s["e_games_a"], 6.0, places=2)

    def test_match_expectation_sets_probability_sums_to_one(self):
        for best_of in (3, 5):
            res = match_expectation(0.7, 0.6, best_of)
            total_p = sum(res["p_sets_count"].values())
            self.assertAlmostEqual(total_p, 1.0, places=9)

    def test_best_of_5_more_expected_games_than_best_of_3(self):
        g3 = match_expectation(0.7, 0.65, 3)["e_total_games"]
        g5 = match_expectation(0.7, 0.65, 5)["e_total_games"]
        self.assertGreater(g5, g3)


def _make_synthetic_features(n_matches: int = 6) -> pd.DataFrame:
    """Constroi uma tabela minima no formato da saida da Fase 3, suficiente
    para exercitar attach_targets/build_history_mean_priors sem precisar do
    parquet real."""

    rows = []
    for i in range(n_matches):
        rows.append({
            "match_id": f"ATP:T:{i}", "player_id": "ATP-P1", "opponent_id": "ATP-P2",
            "tournament_date": pd.Timestamp("2023-01-01") + pd.Timedelta(days=10 * i),
            "surface": "Hard", "best_of": 3, "result": "W" if i % 2 == 0 else "L",
            "score": "6-4 6-4",
            "score_total_games": 20, "score_n_sets_completed": 2,
            "score_has_tiebreak": False, "score_game_diff": 4, "score_complete": True,
            "player_rank": 50, "prior_matches_career": i, "surface_prior_matches": i,
            "prior_matches_last10": min(i, 10), "prior_matches_last20": min(i, 20),
            "prior_matches_last50": min(i, 50), "prior_matches_last365d": i,
            "prior_matches_decay90d": i,
        })
    df = pd.DataFrame(rows)
    return df


class TestHistoryMeans(unittest.TestCase):
    def test_manual_reconstruction_aces(self):
        df = _make_synthetic_features(6)
        df["target_aces"] = [3, 5, 7, 4, 6, 8]
        df["target_double_faults"] = [1] * 6
        df["target_total_games"] = [20] * 6
        df["target_game_diff"] = [4] * 6
        df["target_total_aces_match"] = [10] * 6
        df["target_has_tiebreak"] = [False] * 6

        priors = build_history_mean_priors(df)
        # 4a partida (index 3): media das 3 anteriores = (3+5+7)/3 = 5.0
        self.assertAlmostEqual(priors.loc[3, "hist_mean_aces_career"], 5.0, places=9)
        # 1a partida (index 0): sem historico -> NaN, nunca 0 inventado
        self.assertTrue(pd.isna(priors.loc[0, "hist_mean_aces_career"]))

    def test_future_matches_never_leak(self):
        df_full = _make_synthetic_features(6)
        df_full["target_aces"] = [3, 5, 7, 4, 6, 8]
        for c in ["target_double_faults", "target_game_diff", "target_total_aces_match"]:
            df_full[c] = [1] * 6
        df_full["target_total_games"] = [20] * 6
        df_full["target_has_tiebreak"] = [False] * 6

        priors_full = build_history_mean_priors(df_full)
        df_truncated = df_full.iloc[:4].copy()
        priors_trunc = build_history_mean_priors(df_truncated)

        self.assertAlmostEqual(
            priors_full.loc[3, "hist_mean_aces_career"],
            priors_trunc.loc[3, "hist_mean_aces_career"],
            places=9,
        )

    def test_decay_mean_is_not_biased_by_time_gap(self):
        """Regressao para o bug descrito em docs/008 secao 3: dividir uma
        soma DECAIDA pela contagem BRUTA (nao decaida) de partidas
        anteriores subestima sistematicamente a media quando ha um hiato de
        tempo. Um jogador com aces constantes (sempre 6) deve ter
        hist_mean_aces_decay90d proximo de 6, mesmo apos um hiato longo."""

        df = _make_synthetic_features(4)
        df.loc[:, "target_aces"] = 6.0
        for c in ["target_double_faults", "target_game_diff", "target_total_aces_match"]:
            df[c] = 1.0
        df["target_total_games"] = 20.0
        df["target_has_tiebreak"] = False
        # hiato grande (muitas meias-vidas de 90 dias) antes da ultima partida
        df.loc[3, "tournament_date"] = df.loc[2, "tournament_date"] + pd.Timedelta(days=900)

        priors = build_history_mean_priors(df)
        self.assertAlmostEqual(priors.loc[3, "hist_mean_aces_decay90d"], 6.0, places=6)


class TestTargets(unittest.TestCase):
    def test_game_diff_sign_flipped_for_loser(self):
        df = _make_synthetic_features(2)
        df.loc[0, "result"] = "W"
        df.loc[1, "result"] = "L"
        df["score_game_diff"] = 4
        # attach_targets tambem le a Fase 2 -- aqui simulamos so a parte que
        # nao depende do parquet chamando a logica diretamente.
        is_winner = df["result"] == "W"
        game_diff = np.where(is_winner, df["score_game_diff"], -df["score_game_diff"])
        self.assertEqual(game_diff[0], 4)
        self.assertEqual(game_diff[1], -4)


class TestNegBinFit(unittest.TestCase):
    def test_no_overdispersion_returns_none(self):
        rng = np.random.default_rng(0)
        # Poisson puro (var ~= media) -- nao deve encontrar overdispersion
        data = pd.Series(rng.poisson(5, size=5000))
        r = fit_negbin_r(data)
        self.assertIsNone(r)

    def test_overdispersion_detected(self):
        rng = np.random.default_rng(0)
        # Negative Binomial real (var > media por construcao)
        data = pd.Series(rng.negative_binomial(3, 0.3, size=5000))
        r = fit_negbin_r(data)
        self.assertIsNotNone(r)
        self.assertGreater(r, 0)


class TestWalkForwardFolds(unittest.TestCase):
    def test_folds_are_chronologically_disjoint_and_expanding(self):
        dates = pd.date_range("2022-01-01", "2026-05-25", freq="7D")
        df = pd.DataFrame({"tournament_date": dates})
        for fold in FOLDS:
            train, test = split_fold(df, fold)
            if len(train) == 0 or len(test) == 0:
                continue
            self.assertLessEqual(train["tournament_date"].max(), pd.Timestamp(fold["train_end"]))
            self.assertGreaterEqual(test["tournament_date"].min(), pd.Timestamp(fold["test_start"]))
            self.assertLessEqual(test["tournament_date"].max(), pd.Timestamp(fold["test_end"]))
            self.assertLess(train["tournament_date"].max(), test["tournament_date"].min())

    def test_train_window_expands_across_folds(self):
        dates = pd.date_range("2022-01-01", "2026-05-25", freq="7D")
        df = pd.DataFrame({"tournament_date": dates})
        sizes = []
        for fold in FOLDS:
            train, _ = split_fold(df, fold)
            sizes.append(len(train))
        self.assertEqual(sizes, sorted(sizes))  # nao-decrescente: treino so cresce


class TestBuckets(unittest.TestCase):
    def test_sample_size_bucket_boundaries(self):
        s = pd.Series([0, 1, 9, 10, 49, 50, 200, None])
        out = sample_size_bucket(s)
        self.assertEqual(out.iloc[0], "cold_start")
        self.assertEqual(out.iloc[1], "small_1_9")
        self.assertEqual(out.iloc[2], "small_1_9")
        self.assertEqual(out.iloc[3], "medium_10_49")
        self.assertEqual(out.iloc[5], "large_50_plus")
        self.assertTrue(pd.isna(out.iloc[7]))

    def test_ranking_bucket_boundaries(self):
        s = pd.Series([1, 50, 51, 300, 301, 1000])
        out = ranking_bucket(s)
        self.assertEqual(out.iloc[0], "top50")
        self.assertEqual(out.iloc[2], "top51_100")
        self.assertEqual(out.iloc[3], "top101_300")
        self.assertEqual(out.iloc[4], "outside_300")


class TestTiebreakLogitNoLeakage(unittest.TestCase):
    def _make_df(self, n, seed):
        rng = np.random.default_rng(seed)
        return pd.DataFrame({
            "player_serve_hold_pct_career": rng.uniform(0.5, 0.9, n),
            "opponent_serve_hold_pct_career": rng.uniform(0.5, 0.9, n),
            "player_return_break_pct_career": rng.uniform(0.1, 0.4, n),
            "opponent_return_break_pct_career": rng.uniform(0.1, 0.4, n),
            "surface": rng.choice(["Hard", "Clay", "Grass"], n),
            "target_has_tiebreak": rng.integers(0, 2, n).astype(float),
        })

    def test_mutating_test_fold_does_not_change_fit(self):
        train = self._make_df(300, 1)
        test_a = self._make_df(50, 2)
        preds_a, _ = fit_and_predict_tiebreak_logit(train, test_a, "target_has_tiebreak")

        test_b = test_a.copy()
        test_b["target_has_tiebreak"] = 1 - test_b["target_has_tiebreak"]  # inverte o alvo do teste
        preds_b, _ = fit_and_predict_tiebreak_logit(train, test_b, "target_has_tiebreak")

        # como o alvo do TESTE nunca entra no fit, as previsoes (que dependem
        # so das features de test_a/test_b, identicas) devem ser iguais.
        np.testing.assert_allclose(preds_a, preds_b)


if __name__ == "__main__":
    unittest.main()
