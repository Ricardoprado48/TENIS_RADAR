"""Testes da Fase 8.1 (item 10 da instrucao): ausencia de duplicatas,
compatibilidade de schema, continuidade temporal, ausencia de leakage,
identidade dos jogadores, idempotencia, preservacao dos dados historicos e
radar funcionando apos a atualizacao."""

import hashlib
import io
import unittest
from unittest import mock

import pandas as pd

from src.incremental import dedupe as dedup
from src.incremental import identity_new as ident_new
from src.incremental import merge
from src.incremental import sources as src_check
from src.incremental.config import PROCESSED_DIRS, RAW_SCHEMA_COLUMNS
from src.normalization.matches import OUTPUT_COLUMNS
from src.normalization.players import load_players
from src.radar import build as radar_build
from src.radar import sources as radar_sources


def _existing_atp():
    return pd.read_parquet(PROCESSED_DIRS["atp"] / "matches.parquet")


def _real_recent_pair(tour="atp"):
    """Retorna (winner_name, loser_name) de dois jogadores reais e
    distintos que jogaram na ultima data historica desse tour -- usados como
    fixture realista para os testes abaixo."""

    m = pd.read_parquet(PROCESSED_DIRS[tour] / "matches.parquet")
    last_date = m["tournament_date"].max()
    last_winners = m[(m["tournament_date"] == last_date) & (m["result"] == "W")]
    row = last_winners.iloc[0]
    return row["player_name"], row["opponent_name"]


def _real_recent_pair_with_ids(tour="atp"):
    m = pd.read_parquet(PROCESSED_DIRS[tour] / "matches.parquet")
    last_date = m["tournament_date"].max()
    last_winners = m[(m["tournament_date"] == last_date) & (m["result"] == "W")]
    row = last_winners.iloc[0]
    return row["player_id"], row["player_name"], row["opponent_id"], row["opponent_name"]


def _fake_raw_row(winner_name, loser_name, tourney_date=20260601, tourney_id="9999-TEST",
                   match_num=1, score="6-4 6-3", surface="Hard", tourney_name="Fase8.1 Test Event"):
    # valores numericos como int/float (nao str): `_build_perspective` faz
    # aritmetica (bpFaced - bpSaved) direto sobre estas colunas, antes da
    # conversao explicita para Int64 -- exatamente como acontece com o CSV
    # real (pd.read_csv sem dtype=str infere int64/float64 nativamente).
    return {
        "tourney_id": tourney_id, "tourney_name": tourney_name, "surface": surface,
        "tourney_level": "A", "tourney_date": int(tourney_date), "match_num": match_num,
        "round": "R32", "best_of": 3, "minutes": 120, "score": score,
        "winner_name": winner_name, "winner_hand": "R", "winner_rank": 10, "winner_rank_points": 3000,
        "loser_name": loser_name, "loser_hand": "R", "loser_rank": 50, "loser_rank_points": 800,
        "w_ace": 10, "w_df": 3, "w_svpt": 70, "w_1stIn": 45, "w_1stWon": 35,
        "w_2ndWon": 15, "w_SvGms": 12, "w_bpSaved": 3, "w_bpFaced": 4,
        "l_ace": 5, "l_df": 2, "l_svpt": 65, "l_1stIn": 40, "l_1stWon": 25,
        "l_2ndWon": 10, "l_SvGms": 11, "l_bpSaved": 2, "l_bpFaced": 3,
    }


class TestSourceInvestigation(unittest.TestCase):
    def test_original_repo_check_reports_unavailable_on_404(self):
        results = src_check.check_original_sackmann_repos(status_fn=lambda repo: 404)
        self.assertTrue(all(r.status == "unavailable" for r in results))

    def test_original_repo_check_reports_adequate_on_200(self):
        results = src_check.check_original_sackmann_repos(status_fn=lambda repo: 200)
        self.assertTrue(all(r.status == "adequate" for r in results))

    def test_mirror_freshness_unchanged_sha_is_unavailable(self):
        with mock.patch.object(src_check, "_known_mirror_shas", return_value={
            "atp/atp_matches_2026.csv": {"commit_sha": "abc", "blob_sha": "sha1"},
            "wta/wta_matches_2026.csv": {"commit_sha": "abc", "blob_sha": "sha2"},
        }):
            result = src_check.check_mirror_freshness(
                head_commit_fn=lambda: "abc",
                file_meta_fn=lambda path: {"sha": "sha1" if "atp" in path else "sha2", "size": 100},
            )
        self.assertEqual(result.status, "unavailable")

    def test_mirror_freshness_changed_sha_is_adequate(self):
        with mock.patch.object(src_check, "_known_mirror_shas", return_value={
            "atp/atp_matches_2026.csv": {"commit_sha": "abc", "blob_sha": "sha1"},
            "wta/wta_matches_2026.csv": {"commit_sha": "abc", "blob_sha": "sha2"},
        }):
            result = src_check.check_mirror_freshness(
                head_commit_fn=lambda: "def",
                file_meta_fn=lambda path: {"sha": "sha1_NEW" if "atp" in path else "sha2", "size": 999},
            )
        self.assertEqual(result.status, "adequate")

    def test_candidate_repo_missing_stat_columns_is_inadequate(self):
        header = "Tournament,Date,Surface,Round,Player_1,Player_2,Winner,Rank_1,Rank_2,Score"
        result = src_check.evaluate_candidate_repo(
            "some/repo", "data.csv", header_fetch_fn=lambda r, p: header
        )
        self.assertEqual(result.status, "inadequate_schema")
        self.assertIn("w_ace", result.evidence["missing_stat_columns"])

    def test_candidate_repo_full_schema_is_adequate(self):
        header = ",".join(src_check.cfg.RAW_SCHEMA_COLUMNS)
        result = src_check.evaluate_candidate_repo(
            "some/repo", "data.csv", header_fetch_fn=lambda r, p: header
        )
        self.assertEqual(result.status, "adequate")

    def test_direct_http_endpoint_blocked_is_unavailable(self):
        results = src_check.check_direct_http_endpoints(
            urls=["https://www.atptour.com/en/-/www/rankings/singles"], status_fn=lambda url: 403
        )
        self.assertEqual(results[0].status, "unavailable")


class TestDeduplication(unittest.TestCase):
    def test_exact_match_id_duplicate_detected(self):
        existing = _existing_atp()
        last_row = existing[existing["result"] == "W"].iloc[-1]
        tourney_id_raw = last_row["tourney_id"]
        match_num = last_row["match_id"].split(":")[-1]
        raw = pd.DataFrame([_fake_raw_row(
            last_row["player_name"], last_row["opponent_name"],
            tourney_id=tourney_id_raw, match_num=match_num,
            tourney_date=last_row["tournament_date"].strftime("%Y%m%d"),
        )])
        flagged = dedup.detect_duplicates(raw, existing, "atp")
        self.assertTrue(flagged["is_duplicate_match_id"].iloc[0])
        self.assertTrue(flagged["is_duplicate"].iloc[0])

    def test_context_duplicate_detected_even_with_different_match_id(self):
        existing = _existing_atp()
        last_row = existing[existing["result"] == "W"].iloc[-1]
        raw = pd.DataFrame([_fake_raw_row(
            last_row["player_name"], last_row["opponent_name"],
            tourney_id="DIFFERENT-ID", match_num="999",
            tourney_date=last_row["tournament_date"].strftime("%Y%m%d"),
            score=str(last_row["score"]), tourney_name=str(last_row["tournament"]),
        )])
        flagged = dedup.detect_duplicates(raw, existing, "atp")
        self.assertTrue(flagged["is_duplicate_context"].iloc[0])

    def test_genuinely_new_match_not_flagged_as_duplicate(self):
        existing = _existing_atp()
        w, l = _real_recent_pair("atp")
        raw = pd.DataFrame([_fake_raw_row(w, l, tourney_date=20260601, tourney_id="9999-NEW")])
        flagged = dedup.detect_duplicates(raw, existing, "atp")
        self.assertFalse(flagged["is_duplicate"].iloc[0])


class TestSchemaCompatibility(unittest.TestCase):
    def test_transformed_incremental_row_matches_output_columns(self):
        players, _ = load_players("atp")
        w, l = _real_recent_pair("atp")
        raw = pd.DataFrame([_fake_raw_row(w, l)])
        resolved = ident_new.resolve_incremental_players(raw, "atp", players)
        from src.normalization.matches import transform_raw_matches
        result = transform_raw_matches(resolved, "atp")
        table = result["table"]
        self.assertEqual(list(table.columns), OUTPUT_COLUMNS)
        self.assertEqual(len(table), 2)  # 1 partida = 2 linhas (vencedor + perdedor)

    def test_raw_schema_columns_defined_for_all_required_fields(self):
        # item 2: aces, double faults, service points, first serves in, ...
        required_substrings = ["ace", "df", "svpt", "1stIn", "1stWon", "2ndWon", "SvGms", "bpSaved", "bpFaced"]
        for s in required_substrings:
            self.assertTrue(any(s in c for c in RAW_SCHEMA_COLUMNS), f"coluna com '{s}' ausente do schema")


class TestTemporalContinuity(unittest.TestCase):
    def test_combined_table_is_chronologically_sorted(self):
        players, _ = load_players("atp")
        w, l = _real_recent_pair("atp")
        raw = pd.DataFrame([_fake_raw_row(w, l, tourney_date=20260601, tourney_id="9999-CONT")])
        result = merge.integrate_incremental("atp", raw, players)
        combined = result["combined"]
        dates = combined["tournament_date"]
        self.assertTrue((dates.diff().dropna() >= pd.Timedelta(0)).all())
        self.assertEqual(combined["tournament_date"].max().date(), pd.Timestamp("2026-06-01").date())


class TestNoLeakage(unittest.TestCase):
    def test_new_match_features_reflect_only_prior_history(self):
        players, _ = load_players("atp")
        existing = _existing_atp()
        w_id, w, l_id, l = _real_recent_pair_with_ids("atp")

        raw = pd.DataFrame([_fake_raw_row(w, l, tourney_date=20260601, tourney_id="9999-LEAK")])
        result = merge.integrate_incremental("atp", raw, players)
        combined = result["combined"]
        full = merge.rebuild_features(combined)

        new_match_id = "ATP:9999-LEAK:1"
        new_rows = full[full["match_id"] == new_match_id]
        self.assertEqual(len(new_rows), 2)

        winner_row = new_rows[new_rows["result"] == "W"].iloc[0]
        prior_matches = existing.loc[
            (existing["player_id"] == w_id) & (existing["tournament_date"] < pd.Timestamp("2026-06-01"))
        ]
        expected_ace_rate = prior_matches["aces"].sum() / prior_matches["service_points"].sum()
        self.assertAlmostEqual(
            float(winner_row["player_serve_ace_rate_career"]), float(expected_ace_rate), places=9,
        )
        self.assertEqual(int(winner_row["prior_matches_career"]), len(prior_matches))

    def test_earlier_matches_unaffected_by_new_future_dated_match(self):
        players, _ = load_players("atp")
        existing = _existing_atp()
        w, l = _real_recent_pair("atp")

        full_before = merge.rebuild_features(existing)

        raw = pd.DataFrame([_fake_raw_row(w, l, tourney_date=20260601, tourney_id="9999-LEAK2")])
        result = merge.integrate_incremental("atp", raw, players)
        full_after = merge.rebuild_features(result["combined"])

        common_ids = set(full_before["match_id"]) & set(full_after["match_id"])
        sample_id = existing.iloc[0]["match_id"]
        self.assertIn(sample_id, common_ids)

        before_row = full_before[full_before["match_id"] == sample_id].sort_values("result").reset_index(drop=True)
        after_row = full_after[full_after["match_id"] == sample_id].sort_values("result").reset_index(drop=True)
        pd.testing.assert_frame_equal(before_row, after_row)


class TestPlayerIdentity(unittest.TestCase):
    def test_existing_player_resolves_exact(self):
        players, _ = load_players("atp")
        w, l = _real_recent_pair("atp")
        raw = pd.DataFrame([_fake_raw_row(w, l)])
        resolved = ident_new.resolve_incremental_players(raw, "atp", players)
        self.assertEqual(resolved["winner_resolution_method"].iloc[0], "exact")
        self.assertEqual(resolved["loser_resolution_method"].iloc[0], "exact")

    def test_unknown_player_gets_new_synthetic_id_never_reuses_existing(self):
        players, _ = load_players("atp")
        _, real_opponent = _real_recent_pair("atp")
        raw = pd.DataFrame([_fake_raw_row("Zzznonexistent Playerxyz", real_opponent)])
        resolved = ident_new.resolve_incremental_players(raw, "atp", players)
        self.assertEqual(resolved["winner_resolution_method"].iloc[0], "unresolved")
        new_id = resolved["winner_id"].iloc[0]
        self.assertTrue(new_id.startswith("NEW-"))
        self.assertNotIn(new_id, set(players["player_id_raw"]))

    def test_two_unknown_players_get_distinct_ids(self):
        players, _ = load_players("atp")
        raw = pd.DataFrame([
            _fake_raw_row("Zzzalpha Nobody", "Zzzbeta Nobody", tourney_id="9999-A", match_num="1"),
        ])
        resolved = ident_new.resolve_incremental_players(raw, "atp", players)
        self.assertNotEqual(resolved["winner_id"].iloc[0], resolved["loser_id"].iloc[0])


class TestIdempotentIncrementalRun(unittest.TestCase):
    def test_second_run_detects_already_incorporated_match_as_duplicate(self):
        players, _ = load_players("atp")
        w, l = _real_recent_pair("atp")
        raw = pd.DataFrame([_fake_raw_row(w, l, tourney_date=20260601, tourney_id="9999-IDEMP")])

        first = merge.integrate_incremental("atp", raw, players)
        self.assertEqual(first["diagnostics"]["n_new_matches_incorporated"], 1)

        existing_after_first = _existing_atp()

        def fake_load(tour):
            return first["combined"]

        with mock.patch.object(merge, "load_existing_matches", side_effect=fake_load):
            second = merge.integrate_incremental("atp", raw, players)

        self.assertEqual(second["diagnostics"]["n_new_matches_incorporated"], 0)
        self.assertEqual(second["diagnostics"]["n_duplicates_skipped"], 1)


class TestHistoricalDataPreserved(unittest.TestCase):
    def test_integrate_incremental_never_writes_to_processed_dir(self):
        path = PROCESSED_DIRS["atp"] / "matches.parquet"
        before_hash = hashlib.sha256(path.read_bytes()).hexdigest()

        players, _ = load_players("atp")
        w, l = _real_recent_pair("atp")
        raw = pd.DataFrame([_fake_raw_row(w, l, tourney_date=20260601, tourney_id="9999-PRESERVE")])
        merge.integrate_incremental("atp", raw, players)
        merge.rebuild_features(_existing_atp())

        after_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(before_hash, after_hash)


class TestRadarAfterUpdate(unittest.TestCase):
    def test_radar_runs_against_override_historical_base_with_real_new_match(self):
        import tempfile
        from pathlib import Path

        players, _ = load_players("atp")
        w, l = _real_recent_pair("atp")
        raw = pd.DataFrame([_fake_raw_row(w, l, tourney_date=20260601, tourney_id="9999-RADAR")])
        result = merge.integrate_incremental("atp", raw, players)
        self.assertEqual(result["diagnostics"]["n_new_matches_incorporated"], 1)

        with tempfile.TemporaryDirectory() as tmp:
            override_path = Path(tmp) / "atp_matches.parquet"
            result["combined"].to_parquet(override_path, index=False)
            out_dir = Path(tmp) / "radar_out"

            summary = radar_build.run(
                raw_path=str(radar_sources.latest_raw_file()),
                historical_overrides={"ATP": override_path},
                output_dir=out_dir,
            )
            self.assertGreater(summary["n_matches_raw"], 0)
            self.assertTrue((out_dir / "phase8_summary.json").exists())


if __name__ == "__main__":
    unittest.main()
