"""Testes do LOTE D (radar do dia, docs/018_PWA_ARQUITETURA.md): adapter
`api/services/radar_service.py` sobre os outputs ja produzidos pela Fase 8
(`data/outputs/phase8/*.parquet`) e o endpoint HTTP `GET /api/radar/today`.

Toda a fixture e sintetica (nunca le `data/outputs/phase8/` real) para o
teste ser deterministico e nao depender do estado atual do radar. Os
valores de probabilidade/odd usados na fixture sao inventados so para o
teste -- nunca confundir com dado de producao."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from api.main import app
from api.services import radar_service

CALENDAR_FIELDS = [
    "tour", "tournament", "round", "player_a_raw", "player_b_raw", "surface",
    "event_datetime_original", "event_timezone", "source_url", "collected_at",
]


def _prices_rows() -> list[dict]:
    common = {
        "fold": "radar_atual", "line_difficulty": "easy",
        "raw_probability": 0.5, "calibrated_probability": 0.5,
        "method_selected": "platt", "calibrator_train_n": 500,
        "cold_start": False, "insufficient_history": False,
        "calibrator_insufficient_sample": False,
    }
    return [
        # Match A (ATP, Chengdu Open) -- CONFERIR_ODDS: atende todos os criterios.
        dict(common, tour="ATP", market="aces_player", match_id="FUTURE:ATP:0",
             player_id="P1", line=5.5, side="over",
             sample_bucket_career="large_50_plus", operational_probability=0.245,
             fair_odds=4.09, extreme_probability=False, restricted=False,
             restricted_motivo=None, tournament="Chengdu Open", surface="Hard",
             match_date="2026-09-23", round="R32", player_name="sebastian baez",
             opponent_name="jenson brooksby", resolution_method_player="exact",
             resolution_method_opponent="exact", is_candidate=True, candidate_blockers=""),
        # Match A -- OBSERVAR: unico blocker e probabilidade extrema.
        dict(common, tour="ATP", market="aces_player", match_id="FUTURE:ATP:0",
             player_id="P2", line=9.5, side="over",
             sample_bucket_career="large_50_plus", operational_probability=0.03,
             fair_odds=33.3, extreme_probability=True, restricted=False,
             restricted_motivo=None, tournament="Chengdu Open", surface="Hard",
             match_date="2026-09-23", round="R32", player_name="jenson brooksby",
             opponent_name="sebastian baez", resolution_method_player="exact",
             resolution_method_opponent="exact", is_candidate=False,
             candidate_blockers="probabilidade_nao_trivial"),
        # Match A -- DESCARTADO: amostra insuficiente (nao e so probabilidade extrema).
        dict(common, tour="ATP", market="double_faults_player", match_id="FUTURE:ATP:0",
             player_id="P1", line=0.5, side="over",
             sample_bucket_career="small_1_9", operational_probability=0.6,
             fair_odds=1.67, extreme_probability=False, restricted=False,
             restricted_motivo=None, tournament="Chengdu Open", surface="Hard",
             match_date="2026-09-23", round="R32", player_name="sebastian baez",
             opponent_name="jenson brooksby", resolution_method_player="exact",
             resolution_method_opponent="exact", is_candidate=False,
             candidate_blockers="historico_suficiente"),
        # Match A -- cold_start: fair_odds NaN (pipeline nunca precifica cold start).
        dict(common, tour="ATP", market="aces_player", match_id="FUTURE:ATP:0",
             player_id="P1", line=12.5, side="over",
             sample_bucket_career="cold_start", operational_probability=0.01,
             fair_odds=float("nan"), extreme_probability=True, restricted=False,
             restricted_motivo=None, tournament="Chengdu Open", surface="Hard",
             match_date="2026-09-23", round="R32", player_name="sebastian baez",
             opponent_name="jenson brooksby", resolution_method_player="exact",
             resolution_method_opponent="exact", is_candidate=False,
             candidate_blockers="historico_suficiente,probabilidade_nao_trivial"),
        # Match A -- total_aces_match, gravado duas vezes (uma por ancora de
        # jogador) com valores identicos -- deve ser deduplicado para 1 linha,
        # player=None.
        dict(common, tour="ATP", market="total_aces_match", match_id="FUTURE:ATP:0",
             player_id="P1", line=21.5, side="over",
             sample_bucket_career="large_50_plus", operational_probability=0.4,
             fair_odds=2.5, extreme_probability=False, restricted=False,
             restricted_motivo=None, tournament="Chengdu Open", surface="Hard",
             match_date="2026-09-23", round="R32", player_name="sebastian baez",
             opponent_name="jenson brooksby", resolution_method_player="exact",
             resolution_method_opponent="exact", is_candidate=True, candidate_blockers=""),
        dict(common, tour="ATP", market="total_aces_match", match_id="FUTURE:ATP:0",
             player_id="P2", line=21.5, side="over",
             sample_bucket_career="large_50_plus", operational_probability=0.4,
             fair_odds=2.5, extreme_probability=False, restricted=False,
             restricted_motivo=None, tournament="Chengdu Open", surface="Hard",
             match_date="2026-09-23", round="R32", player_name="jenson brooksby",
             opponent_name="sebastian baez", resolution_method_player="exact",
             resolution_method_opponent="exact", is_candidate=True, candidate_blockers=""),
        # Match B (WTA, sem entrada no calendario) -- restricted=True e
        # identidade nao confiavel (fuzzy_review) -- DESCARTADO por dois
        # motivos estruturais ao mesmo tempo.
        dict(common, tour="WTA", market="aces_player", match_id="FUTURE:WTA:1",
             player_id="P3", line=4.5, side="over",
             sample_bucket_career="large_50_plus", operational_probability=0.5,
             fair_odds=2.0, extreme_probability=False, restricted=True,
             restricted_motivo="ATP aces_player em Grass", tournament="Wuhan Open",
             surface="Grass", match_date="2026-09-24", round="QF",
             player_name="iga swiatek", opponent_name="aryna sabalenka",
             resolution_method_player="fuzzy_review", resolution_method_opponent="exact",
             is_candidate=False, candidate_blockers="mercado_liberado,identidade_confiavel"),
    ]


def _resolved_rows() -> list[dict]:
    return [
        {
            "raw_match_seq": 0, "tour": "ATP", "tournament": "Chengdu Open",
            "round": "R32", "match_date": pd.Timestamp("2026-09-23"),
            "player_a_raw": "Sebastian Baez", "player_b_raw": "Jenson Brooksby",
            "player_id_a": "P1", "player_id_b": "P2",
            "usable_for_prediction": True, "is_duplicate": False,
        },
        {
            "raw_match_seq": 1, "tour": "WTA", "tournament": "Wuhan Open",
            "round": "QF", "match_date": pd.Timestamp("2026-09-24"),
            "player_a_raw": "Iga Swiatek", "player_b_raw": "Aryna Sabalenka",
            "player_id_a": "P3", "player_id_b": "P4",
            "usable_for_prediction": True, "is_duplicate": False,
        },
        # Nao usavel -- nunca deve aparecer no resultado.
        {
            "raw_match_seq": 2, "tour": "ATP", "tournament": "Descartado",
            "round": "R64", "match_date": pd.Timestamp("2026-09-23"),
            "player_a_raw": "X", "player_b_raw": "Y",
            "player_id_a": "P5", "player_id_b": "P6",
            "usable_for_prediction": False, "is_duplicate": False,
        },
    ]


def _min_odds_rows() -> list[dict]:
    rows = []
    for edge_label in ["2pct", "3pct", "5pct", "7_5pct", "10pct"]:
        rows.append({
            "match_id": "FUTURE:ATP:0", "market": "aces_player", "player_id": "P1",
            "line": 5.5, "side": "over", "edge_label": edge_label,
            "odd_minima": 4.0 + {"2pct": 0.1, "3pct": 0.2, "5pct": 0.4, "7_5pct": 0.6, "10pct": 0.9}[edge_label],
        })
    return rows


def _write_fixture(phase8_dir: Path) -> None:
    phase8_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(_prices_rows()).to_parquet(phase8_dir / "precos_por_linha.parquet", index=False)
    pd.DataFrame(_resolved_rows()).to_parquet(phase8_dir / "partidas_resolvidas.parquet", index=False)
    pd.DataFrame(_min_odds_rows()).to_parquet(phase8_dir / "odds_minimas_por_edge.parquet", index=False)


def _write_calendar_csv(calendar_dir: Path) -> None:
    calendar_dir.mkdir(parents=True, exist_ok=True)
    path = calendar_dir / "agenda_20260923.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CALENDAR_FIELDS)
        writer.writeheader()
        writer.writerow({
            "tour": "ATP", "tournament": "Chengdu Open", "round": "R32",
            "player_a_raw": "Sebastian Baez", "player_b_raw": "Jenson Brooksby",
            "surface": "Hard", "event_datetime_original": "2026-09-23T14:00:00",
            "event_timezone": "Asia/Shanghai", "source_url": "https://example.com",
            "collected_at": "2026-09-22T18:00:00Z",
        })
        writer.writerow({
            "tour": "WTA", "tournament": "Wuhan Open", "round": "QF",
            "player_a_raw": "Iga Swiatek", "player_b_raw": "Aryna Sabalenka",
            "surface": "Grass", "event_datetime_original": "2026-09-24T14:00:00",
            "event_timezone": "Asia/Shanghai", "source_url": "https://example.com/wta",
            "collected_at": "2026-09-22T18:00:00Z",
        })


def _fake_staleness_warning(tour: str) -> dict:
    days = {"ATP": 121, "WTA": 121}[tour]
    return {"historical_data_cutoff": "2026-05-25", "data_staleness_days": days}


class RadarFixtureTestCase(unittest.TestCase):
    """Base com o diretorio phase8 sintetico + calendario sintetico
    montados/desmontados a cada teste, e staleness_warning congelado (nunca
    depende de data/processed/ real)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(self._tmp.name)
        self.phase8_dir = tmp_path / "phase8"
        self.calendar_dir = tmp_path / "calendar"
        _write_fixture(self.phase8_dir)
        _write_calendar_csv(self.calendar_dir)

        self._patchers = [
            patch("api.services.radar_service.radar_cfg.PHASE8_DIR", self.phase8_dir),
            patch("src.calendar.config.CALENDAR_RAW_DIR", self.calendar_dir),
            patch("api.services.radar_service.pricing_compare.staleness_warning",
                  side_effect=_fake_staleness_warning),
            patch(
                "api.services.radar_service._now_utc",
                return_value=pd.Timestamp("2026-09-23T04:00:00Z").to_pydatetime(),
            ),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self) -> None:
        for p in self._patchers:
            p.stop()
        self._tmp.cleanup()


class TestRadarLinesAdapter(RadarFixtureTestCase):
    def test_returns_one_line_per_price_row_except_deduplicated_match_level_market(self):
        lines = radar_service.get_radar_lines()
        # 4 linhas de Match A (aces x2, double_faults, cold_start) + 1
        # total_aces_match deduplicada + 1 linha de Match B = 6.
        self.assertEqual(len(lines), 6)

    def test_match_level_market_is_deduplicated_and_exposes_no_player(self):
        lines = radar_service.get_radar_lines()
        total_aces = [l for l in lines if l.market == "total_aces_match"]
        self.assertEqual(len(total_aces), 1)
        self.assertIsNone(total_aces[0].player)

    def test_decision_state_conferir_odds_when_is_candidate_true(self):
        lines = radar_service.get_radar_lines()
        line = next(l for l in lines if l.market == "aces_player" and l.player == "Sebastian Baez" and l.line == 5.5)
        self.assertEqual(line.decision_state, "CONFERIR_ODDS")
        self.assertEqual(line.candidate_blockers, [])

    def test_decision_state_observar_when_only_blocker_is_extreme_probability(self):
        lines = radar_service.get_radar_lines()
        line = next(l for l in lines if l.market == "aces_player" and l.player == "Jenson Brooksby")
        self.assertEqual(line.decision_state, "OBSERVAR")
        self.assertEqual(line.candidate_blockers, ["probabilidade_nao_trivial"])

    def test_decision_state_descartado_when_structural_blocker_present(self):
        lines = radar_service.get_radar_lines()
        line = next(l for l in lines if l.market == "double_faults_player")
        self.assertEqual(line.decision_state, "DESCARTADO")
        self.assertEqual(line.candidate_blockers, ["historico_suficiente"])

    def test_decision_state_descartado_when_extreme_probability_combined_with_other_blocker(self):
        lines = radar_service.get_radar_lines()
        line = next(l for l in lines if l.line == 12.5)
        self.assertEqual(line.decision_state, "DESCARTADO")

    def test_no_recalculation_values_pass_through_unchanged(self):
        """A API nunca recalcula probabilidade/odd -- os valores expostos
        devem ser exatamente os da fixture (nenhuma formula aplicada aqui)."""
        lines = radar_service.get_radar_lines()
        line = next(l for l in lines if l.market == "aces_player" and l.player == "Sebastian Baez" and l.line == 5.5)
        self.assertEqual(line.probability, 0.245)
        self.assertAlmostEqual(line.fair_odds, 4.09)

    def test_cold_start_fair_odds_is_none_not_nan(self):
        lines = radar_service.get_radar_lines()
        line = next(l for l in lines if l.line == 12.5)
        self.assertIsNone(line.fair_odds)

    def test_restricted_motivo_passed_through_when_restricted(self):
        lines = radar_service.get_radar_lines()
        line = next(l for l in lines if l.tour == "WTA")
        self.assertTrue(line.restricted)
        self.assertEqual(line.restricted_motivo, "ATP aces_player em Grass")

    def test_identity_trusted_false_when_identidade_confiavel_is_a_blocker(self):
        lines = radar_service.get_radar_lines()
        line = next(l for l in lines if l.tour == "WTA")
        self.assertFalse(line.identity_trusted)

    def test_identity_trusted_true_when_identidade_confiavel_not_blocked(self):
        lines = radar_service.get_radar_lines()
        line = next(l for l in lines if l.market == "aces_player" and l.player == "Sebastian Baez" and l.line == 5.5)
        self.assertTrue(line.identity_trusted)

    def test_player_display_uses_correctly_capitalized_raw_name(self):
        lines = radar_service.get_radar_lines()
        line = next(l for l in lines if l.market == "aces_player" and l.line == 5.5)
        # fixture usa "sebastian baez" (minusculo) em player_name -- a API
        # deve expor o nome corretamente capitalizado (player_a_raw).
        self.assertEqual(line.player, "Sebastian Baez")
        self.assertEqual(line.player_a, "Sebastian Baez")
        self.assertEqual(line.player_b, "Jenson Brooksby")

    def test_match_key_matches_the_shared_calendar_formula(self):
        from datetime import date as date_cls
        from src.calendar.match_key import build_match_key

        lines = radar_service.get_radar_lines()
        line = next(l for l in lines if l.match_id == "FUTURE:ATP:0")
        expected = build_match_key(
            tour="ATP", tournament="Chengdu Open", round_="R32",
            player_a="Sebastian Baez", player_b="Jenson Brooksby",
            match_date=date_cls(2026, 9, 23),
        )
        self.assertEqual(line.match_key, expected)

    def test_event_datetime_sao_paulo_filled_when_calendar_entry_matches(self):
        lines = radar_service.get_radar_lines()
        line = next(l for l in lines if l.match_id == "FUTURE:ATP:0")
        self.assertIsNotNone(line.event_datetime_sao_paulo)

    def test_match_without_calendar_entry_does_not_appear(self):
        with patch(
            "api.services.radar_service._active_calendar_datetimes_by_key",
            return_value={},
        ):
            lines = radar_service.get_radar_lines()
        self.assertEqual(lines, [])

    def test_unusable_match_never_appears(self):
        lines = radar_service.get_radar_lines()
        self.assertTrue(all(l.tournament != "Descartado" for l in lines))

    def test_staleness_status_derived_from_existing_policy(self):
        lines = radar_service.get_radar_lines()
        line = next(l for l in lines if l.market == "aces_player" and l.line == 5.5)
        self.assertEqual(line.staleness_status, "MUITO_DEFASADO")
        self.assertEqual(line.staleness_days, 121)
        self.assertEqual(str(line.historical_data_cutoff), "2026-05-25")

    def test_minimum_odds_uses_3pct_scenario_and_full_dict_is_available(self):
        lines = radar_service.get_radar_lines()
        line = next(l for l in lines if l.market == "aces_player" and l.line == 5.5)
        self.assertAlmostEqual(line.minimum_odds, 4.2)
        self.assertEqual(set(line.odd_minima_por_edge.keys()), {"2pct", "3pct", "5pct", "7_5pct", "10pct"})

    def test_missing_min_odds_scenario_is_none_not_missing_key(self):
        lines = radar_service.get_radar_lines()
        # Match B nao tem linhas em odds_minimas_por_edge na fixture.
        line = next(l for l in lines if l.tour == "WTA")
        self.assertIsNone(line.minimum_odds)
        self.assertTrue(all(v is None for v in line.odd_minima_por_edge.values()))


class TestRadarLinesEmptyState(unittest.TestCase):
    def test_missing_precos_por_linha_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            phase8_dir = Path(tmp) / "phase8"  # nunca criado
            with patch("api.services.radar_service.radar_cfg.PHASE8_DIR", phase8_dir):
                self.assertEqual(radar_service.get_radar_lines(), [])

    def test_staleness_lookup_failure_never_crashes_the_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            phase8_dir = tmp_path / "phase8"
            calendar_dir = tmp_path / "calendar"

            _write_fixture(phase8_dir)
            _write_calendar_csv(calendar_dir)

            with patch("api.services.radar_service.radar_cfg.PHASE8_DIR", phase8_dir), \
                 patch("src.calendar.config.CALENDAR_RAW_DIR", calendar_dir), \
                 patch(
                     "api.services.radar_service._now_utc",
                     return_value=pd.Timestamp("2026-09-23T04:00:00Z").to_pydatetime(),
                 ), \
                 patch("api.services.radar_service.pricing_compare.staleness_warning",
                       side_effect=FileNotFoundError("base historica indisponivel no ambiente")):
                lines = radar_service.get_radar_lines()

                self.assertGreater(len(lines), 0)
                self.assertTrue(all(l.staleness_status is None for l in lines))


class TestRadarTodayEndpoint(RadarFixtureTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client = TestClient(app)

    def test_route_is_registered(self) -> None:
        paths = set(app.openapi()["paths"].keys())
        self.assertIn("/api/radar/today", paths)

    def test_returns_200_with_expected_line_count(self) -> None:
        resp = self.client.get("/api/radar/today")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 6)

    def test_response_field_set_matches_schema(self) -> None:
        resp = self.client.get("/api/radar/today")
        body = resp.json()[0]
        self.assertEqual(
            set(body.keys()),
            {
                "match_key", "match_id", "tour", "tournament", "round", "surface",
                "player_a", "player_b", "event_datetime_sao_paulo", "market",
                "player", "side", "line", "probability", "fair_odds",
                "minimum_odds", "odd_minima_por_edge", "decision_state",
                "candidate_blockers", "sample_bucket_career", "restricted",
                "restricted_motivo", "extreme_probability", "identity_trusted",
                "resolution_method_player", "resolution_method_opponent",
                "staleness_status", "staleness_days", "historical_data_cutoff",
                "effective_data_cutoff", "overlay_status",
            },
        )

    def test_decision_states_grouped_correctly_over_http(self) -> None:
        resp = self.client.get("/api/radar/today").json()
        from collections import Counter
        counts = Counter(row["decision_state"] for row in resp)
        self.assertEqual(counts["CONFERIR_ODDS"], 2)  # 5.5-line + total_aces_match deduplicada
        self.assertEqual(counts["OBSERVAR"], 1)
        self.assertEqual(counts["DESCARTADO"], 3)  # double_faults + cold_start + WTA restrita


class TestRadarTodayEmptyEndpoint(unittest.TestCase):
    def test_returns_200_empty_list_when_no_phase8_output_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            phase8_dir = Path(tmp) / "phase8"
            with patch("api.services.radar_service.radar_cfg.PHASE8_DIR", phase8_dir):
                client = TestClient(app)
                resp = client.get("/api/radar/today")
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.json(), [])


if __name__ == "__main__":
    unittest.main()

