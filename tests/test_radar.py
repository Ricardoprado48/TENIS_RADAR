"""Testes de validacao da Fase 8 (item 10): identidade, ausencia de
leakage, jogador desconhecido, torneio/superficie, partidas repetidas,
execucao idempotente, aplicacao das restricoes, consistencia com a
Fase 7."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.normalization.config import PROCESSED_DIRS
from src.radar import build as radar_build
from src.radar import calibration_future as calib
from src.radar import candidates as cand
from src.radar import config as cfg
from src.radar import features_future as feat
from src.radar import identity as ident
from src.radar import pricing_future as pricing
from src.radar import probabilities_future as probs
from src.radar import rates_future as rates
from src.radar import sources


def _toy_players() -> pd.DataFrame:
    return pd.DataFrame({
        "player_id": ["ATP-1", "ATP-2", "ATP-3", "ATP-4"],
        "name": ["Jelena Ostapenko", "Taylah Preston", "Erika Andreeva", "Erika Andreychuk"],
        "name_first": ["Jelena", "Taylah", "Erika", "Erika"],
        "name_last": ["Ostapenko", "Preston", "Andreeva", "Andreychuk"],
    })


class TestIdentityResolution(unittest.TestCase):
    def setUp(self):
        self.idx = ident.PlayerIndex(_toy_players())

    def test_exact_match(self):
        res = self.idx.resolve("Jelena Ostapenko")
        self.assertEqual(res.method, "exact")
        self.assertEqual(res.player_id, "ATP-1")

    def test_alias_initial_lastname_match(self):
        res = self.idx.resolve("J. Ostapenko")
        self.assertEqual(res.method, "alias")
        self.assertEqual(res.player_id, "ATP-1")

    def test_fuzzy_review_for_close_but_not_exact_name(self):
        res = self.idx.resolve("Jelena Ostapenco")  # erro de digitacao proposital
        self.assertEqual(res.method, "fuzzy_review")
        self.assertEqual(res.player_id, "ATP-1")

    def test_unresolved_when_no_candidate(self):
        res = self.idx.resolve("Zzyzx Nobody")
        self.assertEqual(res.method, "unresolved")
        self.assertIsNone(res.player_id)

    def test_unresolved_when_alias_ambiguous(self):
        # "E. Andreeva" x "E. Andreychuk" -- ambos comecam com "E" e a
        # heuristica de sobrenome so bate se ambos tiverem o MESMO
        # sobrenome; aqui simulamos ambiguidade real: dois "A" de sobrenomes
        # que colidem na mesma chave de busca simplificada.
        players = pd.DataFrame({
            "player_id": ["ATP-10", "ATP-11"],
            "name": ["Elena Rybakina", "Egor Rybakina"],
            "name_first": ["Elena", "Egor"],
            "name_last": ["Rybakina", "Rybakina"],
        })
        idx = ident.PlayerIndex(players)
        res = idx.resolve("E. Rybakina")
        self.assertEqual(res.method, "unresolved")
        self.assertIsNone(res.player_id)


class TestUnknownPlayerNoPrediction(unittest.TestCase):
    def test_unresolved_excluded_from_usable_for_prediction(self):
        upcoming = pd.DataFrame({
            "raw_match_seq": [0], "source_file": ["x.csv"], "source_url": ["http://x"],
            "collected_at": [pd.Timestamp.now("UTC")], "tour": ["ATP"], "tournament": ["Test Open"],
            "surface": ["Hard"], "match_date": [pd.Timestamp("2026-09-23")], "round": ["R32"],
            "player_a_raw": ["Jelena Ostapenko"], "player_b_raw": ["Nobody Unknown"],
        })
        resolved = ident.resolve_matches(upcoming, {"ATP": _toy_players()})
        self.assertFalse(resolved.loc[0, "usable_for_prediction"])
        self.assertEqual(resolved.loc[0, "resolution_method_b"], "unresolved")


class TestDuplicateMatches(unittest.TestCase):
    def test_same_pair_same_date_flagged_duplicate(self):
        resolved = pd.DataFrame({
            "raw_match_seq": [0, 1],
            "tour": ["ATP", "ATP"],
            "match_date": [pd.Timestamp("2026-09-23"), pd.Timestamp("2026-09-23")],
            "player_id_a": ["ATP-1", "ATP-2"],
            "player_id_b": ["ATP-2", "ATP-1"],
            "usable_for_prediction": [True, True],
        })
        out = ident.flag_duplicate_matches(resolved)
        self.assertFalse(out.loc[0, "is_duplicate"])
        self.assertTrue(out.loc[1, "is_duplicate"])  # mesma dupla, ordem invertida


class TestRawSourceValidation(unittest.TestCase):
    def test_rejects_invalid_tour(self):
        import io
        csv_text = (
            "source_url,collected_at,tour,tournament,surface,match_date,round,player_a_raw,player_b_raw\n"
            "http://x,2026-09-22T00:00:00Z,ITF,Test,Hard,2026-09-23,R32,A,B\n"
        )
        with self.assertRaises(ValueError):
            sources.load_raw_matches(io.StringIO(csv_text))


class TestFeaturesNoLeakage(unittest.TestCase):
    """Consistencia point-in-time: a linha sintetica construida por
    `features_future` para uma partida REAL (tratada como se fosse futura,
    com o historico truncado antes dela) deve reproduzir EXATAMENTE as
    mesmas colunas player_serve_*/opponent_* que a Fase 3 ja calculou para
    aquela partida usando o motor de producao -- prova de que o truque de
    linha sintetica nao vaza nem perde nenhuma informacao anterior."""

    @classmethod
    def setUpClass(cls):
        cls.matches = pd.read_parquet(PROCESSED_DIRS["atp"] / "matches.parquet")
        cls.features = pd.read_parquet(
            PROCESSED_DIRS["atp"].parent / "features" / "atp" / "player_match_features.parquet"
        )

    def test_synthetic_row_matches_production_features(self):
        m = self.matches.sort_values(
            ["tournament_date", "tourney_id", "match_id", "result"],
            ascending=[True, True, True, False],
        ).reset_index(drop=True)
        # escolhe uma partida cujos dois jogadores NUNCA MAIS aparecem no
        # dataset depois dela (a ultima linha de cada um, em toda a tabela)
        # -- assim, remover so as 2 linhas dessa partida (sem truncar por
        # data, que teria empates com outras rodadas do MESMO torneio no
        # mesmo tournament_date) reproduz exatamente o conjunto de partidas
        # anteriores que a Fase 3 usou para calcular a linha real.
        m_idx = m.reset_index()  # coluna 'index' = posicao na ordenacao point-in-time
        last_idx = m_idx.groupby("player_id")["index"].max()

        target_match_id = None
        # percorre torneios mais recentes primeiro (match_id contem o
        # tourney_id, que ja esta ordenado cronologicamente na tabela).
        for match_id in reversed(m["match_id"].unique().tolist()):
            g = m_idx[m_idx["match_id"] == match_id]
            if len(g) != 2:
                continue
            ok = all(
                last_idx[pid] == idx for pid, idx in zip(g["player_id"], g["index"])
            )
            if ok:
                target_match_id = match_id
                break
        self.assertIsNotNone(target_match_id, "nao achei nenhuma partida final-de-carreira-para-os-2-jogadores")

        target = m[m["match_id"] == target_match_id].iloc[0]
        truncated = m[m["match_id"] != target_match_id].copy()
        resolved_tour = pd.DataFrame({
            "raw_match_seq": [0], "tour": ["ATP"], "tournament": [target.tournament],
            "surface": [target.surface], "match_date": [target.tournament_date], "round": [target.round],
            "player_id_a": [target.player_id], "player_id_b": [target.opponent_id],
            "resolved_name_a": [target.player_name], "resolved_name_b": [target.opponent_name],
            "player_a_raw": [target.player_name], "player_b_raw": [target.opponent_name],
            "usable_for_prediction": [True], "is_duplicate": [False],
        })
        synthetic = feat.build_synthetic_rows(resolved_tour)
        augmented = pd.concat([truncated, synthetic], ignore_index=True).sort_values(
            ["tournament_date", "tourney_id", "match_id", "result"],
            ascending=[True, True, True, False],
        ).reset_index(drop=True)

        from src.features.matchup import build_matchup_table
        from src.features.profile import build_player_profile

        full = build_matchup_table(build_player_profile(augmented))
        synth_row = full[(full["match_id"].str.startswith("FUTURE:")) & (full["player_id"] == target.player_id)].iloc[0]

        prod_row = self.features[self.features["match_id"] == target.match_id]
        prod_row = prod_row[prod_row["player_id"] == target.player_id].iloc[0]

        for col in ["player_serve_ace_rate_career", "player_serve_ace_rate_last50",
                    "opponent_return_ace_allowed_rate_career", "prior_matches_career",
                    "player_serve_double_fault_rate_career"]:
            a = synth_row[col]
            b = prod_row[col]
            if pd.isna(a) and pd.isna(b):
                continue
            self.assertAlmostEqual(float(a), float(b), places=9, msg=f"coluna {col} divergiu")


class TestSurfaceAndTournamentPreserved(unittest.TestCase):
    def test_synthetic_rows_carry_declared_surface_and_tournament(self):
        resolved_tour = pd.DataFrame({
            "raw_match_seq": [0], "tour": ["ATP"], "tournament": ["Chengdu Open"],
            "surface": ["Hard"], "match_date": [pd.Timestamp("2026-09-23")], "round": ["R32"],
            "player_id_a": ["ATP-100001"], "player_id_b": ["ATP-100002"],
            "resolved_name_a": ["Player A"], "resolved_name_b": ["Player B"],
            "player_a_raw": ["Player A"], "player_b_raw": ["Player B"],
        })
        synthetic = feat.build_synthetic_rows(resolved_tour)
        self.assertEqual(len(synthetic), 2)
        self.assertTrue((synthetic["surface"] == "Hard").all())
        self.assertTrue((synthetic["tournament"] == "Chengdu Open").all())
        self.assertEqual(set(synthetic["player_id"]), {"ATP-100001", "ATP-100002"})
        # Serve A x Return B e Serve B x Return A (CLAUDE.md #2)
        a_row = synthetic[synthetic["player_id"] == "ATP-100001"].iloc[0]
        b_row = synthetic[synthetic["player_id"] == "ATP-100002"].iloc[0]
        self.assertEqual(a_row["opponent_id"], "ATP-100002")
        self.assertEqual(b_row["opponent_id"], "ATP-100001")


class TestRestrictionApplied(unittest.TestCase):
    def test_atp_aces_player_grass_restricted_through_pricing_future(self):
        predictions = pd.DataFrame({
            "tour": ["ATP"], "market": ["aces_player"], "fold": [cfg.RADAR_FOLD_LABEL],
            "match_id": ["FUTURE:ATP:0"], "player_id": ["ATP-1"], "opponent_id": ["ATP-2"],
            "surface": ["Grass"], "tournament_date": [pd.Timestamp("2026-09-23")],
            "prior_matches_career": [40], "sample_bucket_career": ["large_50_plus"],
            "config_variant": ["matchup"], "config_window": ["surface_career"],
            "lambda": [8.0], "negbin_r": [2.0], "train_mean": [7.5],
            "line": [8.5], "line_difficulty": ["proxima_da_media"],
            "p_over_negbin": [0.4], "p_under_negbin": [0.6],
            "p_over_poisson": [0.4], "p_under_poisson": [0.6],
            "raw_probability": [0.4], "calibrated_probability": [0.55],
            "method_selected": ["platt"], "calibrator_train_n": [30000],
        })
        base, prices, min_odds = pricing.build_price_tables(predictions)
        self.assertTrue(bool(prices.loc[prices["side"] == "over", "restricted"].iloc[0]))
        self.assertFalse(np.isnan(prices.loc[prices["side"] == "over", "fair_odds"].iloc[0]))


class TestConsistencyWithPhase7(unittest.TestCase):
    """item 10: o calibrador reajustado nesta fase, para o fold vigente
    (fold_2026), tem que reproduzir EXATAMENTE a `calibrated_probability`
    que a Fase 6.1 ja gravou para linhas reais daquele fold -- prova de que
    a Fase 8 nao introduziu nenhuma divergencia na regra de calibracao."""

    @classmethod
    def setUpClass(cls):
        cls.phase6 = pd.read_parquet(
            cfg.PHASE6_PREDICTIONS_PATH, columns=["tour", "market", "fold", "p_over_negbin", "actual_over"],
        )
        cls.phase6_1 = pd.read_parquet(cfg.PHASE6_1_DIR / "previsoes_calibradas.parquet")
        cls.calibrators = calib.build_calibrators(cls.phase6)

    def test_refit_calibrator_matches_phase6_1_exactly_for_all_markets(self):
        for (tour, market), fc in self.calibrators.items():
            sample = self.phase6_1[
                (self.phase6_1["fold"] == "fold_2026") & (self.phase6_1["tour"] == tour)
                & (self.phase6_1["market"] == market)
            ].dropna(subset=["raw_probability"])
            if sample.empty:
                continue
            refit = fc.calibrator.predict(sample["raw_probability"].to_numpy(dtype="float64"))
            np.testing.assert_allclose(
                refit, sample["calibrated_probability"].to_numpy(dtype="float64"), atol=1e-12,
                err_msg=f"{tour}/{market}: calibrador reajustado da Fase 8 diverge da Fase 6.1",
            )


class TestIdempotentExecution(unittest.TestCase):
    def test_running_pipeline_twice_gives_identical_prices(self):
        raw_path = sources.latest_raw_file()
        summary1 = radar_build.run(str(raw_path))
        prices1 = pd.read_parquet(cfg.PHASE8_DIR / "precos_por_linha.parquet")
        summary2 = radar_build.run(str(raw_path))
        prices2 = pd.read_parquet(cfg.PHASE8_DIR / "precos_por_linha.parquet")

        self.assertEqual(summary1["n_price_rows"], summary2["n_price_rows"])
        pd.testing.assert_frame_equal(
            prices1.sort_values(["market", "match_id", "player_id", "line", "side"]).reset_index(drop=True),
            prices2.sort_values(["market", "match_id", "player_id", "line", "side"]).reset_index(drop=True),
        )


if __name__ == "__main__":
    unittest.main()
