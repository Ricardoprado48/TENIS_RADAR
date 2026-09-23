"""Testes do LOTE C (calendario, docs/018_PWA_ARQUITETURA.md secoes 4.1,
4.2, 5): validacao de schema de data/raw/calendar/agenda_*.csv, conversao
de fuso horario (original -> UTC -> America/Sao_Paulo), derivacao de
status, filtragem por data/tour/torneio, e o teste do risco R1 (match_key
estavel entre execucoes, independente de posicao/ordem das linhas)."""

from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from src.calendar.manual_provider import ManualFileCalendarProvider, _derive_status
from src.calendar.match_key import build_match_key

FIELDS = [
    "tour", "tournament", "round", "player_a_raw", "player_b_raw", "surface",
    "event_datetime_original", "event_timezone", "source_url", "collected_at",
]

ROW_SHANGHAI = {
    # Exemplo literal da secao 4.2 do docs/018: 14:00 Asia/Shanghai vira
    # 06:00 UTC e 03:00 America/Sao_Paulo no mesmo dia civil do torneio.
    "tour": "ATP",
    "tournament": "Shanghai Masters",
    "round": "R32",
    "player_a_raw": "Novak Djokovic",
    "player_b_raw": "Carlos Alcaraz",
    "surface": "Hard",
    "event_datetime_original": "2026-09-23T14:00:00",
    "event_timezone": "Asia/Shanghai",
    "source_url": "https://example.com/shanghai",
    "collected_at": "2026-09-22T18:00:00Z",
}

ROW_WUHAN = {
    "tour": "WTA",
    "tournament": "Wuhan Open",
    "round": "QF",
    "player_a_raw": "Iga Swiatek",
    "player_b_raw": "Aryna Sabalenka",
    "surface": "Hard",
    "event_datetime_original": "2026-09-24T10:00:00",
    "event_timezone": "Asia/Shanghai",
    "source_url": "https://example.com/wuhan",
    "collected_at": "2026-09-22T18:05:00Z",
}


def _write_csv(directory: Path, filename: str, rows: list[dict]) -> Path:
    path = directory / filename
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


class TestRawSourceValidation(unittest.TestCase):
    def test_rejects_missing_required_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            path = tmp_path / "agenda_20260923.csv"
            with path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=[f for f in FIELDS if f != "surface"])
                writer.writeheader()
            provider = ManualFileCalendarProvider(raw_dir=tmp_path)
            with self.assertRaises(ValueError) as ctx:
                provider.list_matches(date(2026, 1, 1), date(2026, 12, 31))
            self.assertIn("surface", str(ctx.exception))

    def test_rejects_invalid_tour(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bad_row = dict(ROW_SHANGHAI, tour="ITF")
            _write_csv(tmp_path, "agenda_20260923.csv", [bad_row])
            provider = ManualFileCalendarProvider(raw_dir=tmp_path)
            with self.assertRaises(ValueError) as ctx:
                provider.list_matches(date(2026, 1, 1), date(2026, 12, 31))
            self.assertIn("tour invalido", str(ctx.exception))

    def test_rejects_invalid_surface(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bad_row = dict(ROW_SHANGHAI, surface="Carpet")
            _write_csv(tmp_path, "agenda_20260923.csv", [bad_row])
            provider = ManualFileCalendarProvider(raw_dir=tmp_path)
            with self.assertRaises(ValueError) as ctx:
                provider.list_matches(date(2026, 1, 1), date(2026, 12, 31))
            self.assertIn("surface invalida", str(ctx.exception))

    def test_rejects_blank_player_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bad_row = dict(ROW_SHANGHAI, player_a_raw="")
            _write_csv(tmp_path, "agenda_20260923.csv", [bad_row])
            provider = ManualFileCalendarProvider(raw_dir=tmp_path)
            with self.assertRaises(ValueError) as ctx:
                provider.list_matches(date(2026, 1, 1), date(2026, 12, 31))
            self.assertIn("player_a_raw", str(ctx.exception))

    def test_rejects_unknown_timezone(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bad_row = dict(ROW_SHANGHAI, event_timezone="Not/AZone")
            _write_csv(tmp_path, "agenda_20260923.csv", [bad_row])
            provider = ManualFileCalendarProvider(raw_dir=tmp_path)
            with self.assertRaises(ValueError) as ctx:
                provider.list_matches(date(2026, 1, 1), date(2026, 12, 31))
            self.assertIn("fuso horario invalido", str(ctx.exception))


class TestTimezoneConversion(unittest.TestCase):
    def test_matches_the_worked_example_from_docs_018_section_4_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_csv(tmp_path, "agenda_20260923.csv", [ROW_SHANGHAI])
            provider = ManualFileCalendarProvider(raw_dir=tmp_path)
            matches = provider.list_matches(date(2026, 1, 1), date(2026, 12, 31))
            self.assertEqual(len(matches), 1)
            m = matches[0]
            self.assertEqual(m.event_datetime_utc, datetime(2026, 9, 23, 6, 0, tzinfo=timezone.utc))
            self.assertEqual(
                m.event_datetime_sao_paulo,
                datetime(2026, 9, 23, 3, 0, tzinfo=ZoneInfo("America/Sao_Paulo")),
            )
            self.assertEqual(m.event_timezone, "Asia/Shanghai")


class TestStatusDerivation(unittest.TestCase):
    def test_futuro_well_before_start(self):
        start = datetime(2026, 9, 23, 6, 0, tzinfo=timezone.utc)
        now = start - timedelta(hours=10)
        self.assertEqual(_derive_status(start, now), "futuro")

    def test_proximo_within_window_before_start(self):
        start = datetime(2026, 9, 23, 6, 0, tzinfo=timezone.utc)
        now = start - timedelta(minutes=30)
        self.assertEqual(_derive_status(start, now), "proximo")

    def test_iniciado_right_after_start(self):
        start = datetime(2026, 9, 23, 6, 0, tzinfo=timezone.utc)
        now = start + timedelta(minutes=5)
        self.assertEqual(_derive_status(start, now), "iniciado")

    def test_iniciado_still_within_max_duration(self):
        start = datetime(2026, 9, 23, 6, 0, tzinfo=timezone.utc)
        now = start + timedelta(hours=4, minutes=59)
        self.assertEqual(_derive_status(start, now), "iniciado")

    def test_encerrado_after_max_duration(self):
        start = datetime(2026, 9, 23, 6, 0, tzinfo=timezone.utc)
        now = start + timedelta(hours=6)
        self.assertEqual(_derive_status(start, now), "encerrado")


class TestListMatchesFiltering(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        _write_csv(self.tmp_path, "agenda_20260923.csv", [ROW_SHANGHAI, ROW_WUHAN])
        self.provider = ManualFileCalendarProvider(raw_dir=self.tmp_path)

    def tearDown(self):
        self._tmp.cleanup()

    def test_date_range_filters_by_sao_paulo_calendar_day(self):
        # Shanghai 23/09 14:00 -> Sao Paulo 23/09 03:00; Wuhan 24/09 10:00 ->
        # Sao Paulo 23/09 23:00 -- as duas caem no dia 23 em Sao Paulo.
        matches = self.provider.list_matches(date(2026, 9, 23), date(2026, 9, 23))
        self.assertEqual({m.tournament for m in matches}, {"Shanghai Masters", "Wuhan Open"})

    def test_date_range_excludes_matches_outside_window(self):
        matches = self.provider.list_matches(date(2026, 9, 24), date(2026, 9, 30))
        self.assertEqual(matches, [])

    def test_filters_by_tour(self):
        matches = self.provider.list_matches(date(2026, 9, 1), date(2026, 9, 30), tour="WTA")
        self.assertEqual([m.tournament for m in matches], ["Wuhan Open"])

    def test_filters_by_tournament(self):
        matches = self.provider.list_matches(
            date(2026, 9, 1), date(2026, 9, 30), tournament="Shanghai Masters"
        )
        self.assertEqual([m.tournament for m in matches], ["Shanghai Masters"])

    def test_results_sorted_by_utc_start_time(self):
        matches = self.provider.list_matches(date(2026, 9, 1), date(2026, 9, 30))
        utcs = [m.event_datetime_utc for m in matches]
        self.assertEqual(utcs, sorted(utcs))

    def test_list_tournaments_deduplicates(self):
        tournaments = self.provider.list_tournaments(date(2026, 9, 1), date(2026, 9, 30))
        self.assertEqual(
            {(t.tour, t.tournament) for t in tournaments},
            {("ATP", "Shanghai Masters"), ("WTA", "Wuhan Open")},
        )


class TestGetMatchByKey(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        _write_csv(self.tmp_path, "agenda_20260923.csv", [ROW_SHANGHAI, ROW_WUHAN])
        self.provider = ManualFileCalendarProvider(raw_dir=self.tmp_path)

    def tearDown(self):
        self._tmp.cleanup()

    def test_get_match_returns_the_matching_row(self):
        all_matches = self.provider.list_matches(date(2026, 1, 1), date(2026, 12, 31))
        target = all_matches[0]
        found = self.provider.get_match(target.match_key)
        self.assertIsNotNone(found)
        self.assertEqual(found.match_key, target.match_key)
        self.assertEqual(found.player_a, target.player_a)

    def test_get_match_returns_none_for_unknown_key(self):
        self.assertIsNone(self.provider.get_match("chave-que-nao-existe"))


class TestMultipleFilesCombined(unittest.TestCase):
    def test_reads_and_combines_every_agenda_file_in_the_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_csv(tmp_path, "agenda_20260923.csv", [ROW_SHANGHAI])
            _write_csv(tmp_path, "agenda_20260924.csv", [ROW_WUHAN])
            provider = ManualFileCalendarProvider(raw_dir=tmp_path)
            matches = provider.list_matches(date(2026, 1, 1), date(2026, 12, 31))
            self.assertEqual(
                {m.tournament for m in matches}, {"Shanghai Masters", "Wuhan Open"}
            )


class TestRiscoR1MatchKeyEstavel(unittest.TestCase):
    """docs/018_PWA_ARQUITETURA.md risco R1 (secao 12): match_key precisa
    continuar resolvendo para a mesma partida mesmo que o radar rode de novo
    no mesmo dia (match_id do radar e reindexado, mas match_key nao pode
    mudar). Como match_key e derivado so de campos de conteudo -- nunca de
    posicao/indice de linha -- ele deve ser identico entre execucoes."""

    def test_build_match_key_is_pure_and_deterministic(self):
        key1 = build_match_key(
            tour="ATP", tournament="Shanghai Masters", round_="R32",
            player_a="Novak Djokovic", player_b="Carlos Alcaraz",
            match_date=date(2026, 9, 23),
        )
        key2 = build_match_key(
            tour="ATP", tournament="Shanghai Masters", round_="R32",
            player_a="Novak Djokovic", player_b="Carlos Alcaraz",
            match_date=date(2026, 9, 23),
        )
        self.assertEqual(key1, key2)

    def test_match_key_unaffected_by_row_order_in_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_csv(tmp_path, "agenda_original.csv", [ROW_SHANGHAI, ROW_WUHAN])
            provider_original = ManualFileCalendarProvider(raw_dir=tmp_path)
            keys_original = {
                m.tournament: m.match_key
                for m in provider_original.list_matches(date(2026, 1, 1), date(2026, 12, 31))
            }

        with tempfile.TemporaryDirectory() as tmp2:
            tmp_path2 = Path(tmp2)
            # Mesmo conteudo, ordem invertida -- simula uma nova execucao/
            # recoleta que grava as linhas em outra ordem.
            _write_csv(tmp_path2, "agenda_reexecutado.csv", [ROW_WUHAN, ROW_SHANGHAI])
            provider_rerun = ManualFileCalendarProvider(raw_dir=tmp_path2)
            keys_rerun = {
                m.tournament: m.match_key
                for m in provider_rerun.list_matches(date(2026, 1, 1), date(2026, 12, 31))
            }

        self.assertEqual(keys_original, keys_rerun)

    def test_match_key_differs_for_different_matches(self):
        key_shanghai = build_match_key(
            tour="ATP", tournament="Shanghai Masters", round_="R32",
            player_a="Novak Djokovic", player_b="Carlos Alcaraz",
            match_date=date(2026, 9, 23),
        )
        key_wuhan = build_match_key(
            tour="WTA", tournament="Wuhan Open", round_="QF",
            player_a="Iga Swiatek", player_b="Aryna Sabalenka",
            match_date=date(2026, 9, 24),
        )
        self.assertNotEqual(key_shanghai, key_wuhan)

    def test_match_key_is_a_url_safe_slug(self):
        key = build_match_key(
            tour="ATP", tournament="AITO Hangzhou Open", round_="R32",
            player_a="A. Vukic", player_b="K. Jacquet",
            match_date=date(2026, 9, 23),
        )
        self.assertRegex(key, r"^[a-z0-9]+(-[a-z0-9]+)*$")


if __name__ == "__main__":
    unittest.main()
