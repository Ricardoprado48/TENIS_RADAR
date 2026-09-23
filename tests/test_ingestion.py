"""Testes basicos de integridade da Fase 1 (ingestao).

Dois grupos:
  1. Testes de unidade da logica de "nao sobrescrever silenciosamente"
     (download.fetch_and_store), usando rede simulada (sem chamadas HTTP reais).
  2. Testes de integracao sobre os dados ja baixados em data/raw/, validando
     o manifesto, a integridade dos arquivos e a consistencia de schema
     entre ATP e WTA.
"""

import csv
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ingestion import download, validate  # noqa: E402
from src.ingestion.config import PROJECT_ROOT, SOURCES, MANIFEST_JSON  # noqa: E402


class TestNoSilentOverwrite(unittest.TestCase):
    """Simula a rede para testar a logica de gravacao sem depender de internet."""

    def setUp(self):
        self.tmp_dir = Path(PROJECT_ROOT) / "data" / "raw" / "_test_scratch"
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.local_path = self.tmp_dir / "fake_matches_2099.csv"
        if self.local_path.exists():
            self.local_path.unlink()
        for f in self.tmp_dir.glob("fake_matches_2099.conflict-*.csv"):
            f.unlink()

    def tearDown(self):
        for f in self.tmp_dir.glob("fake_matches_2099*"):
            f.unlink()
        if self.tmp_dir.exists() and not any(self.tmp_dir.iterdir()):
            self.tmp_dir.rmdir()

    def _fetch(self, content_bytes: bytes):
        fake_meta = {
            "name": "fake_matches_2099.csv",
            "download_url": "https://example.invalid/fake_matches_2099.csv",
            "sha": "deadbeef",
            "size": len(content_bytes),
        }
        with mock.patch("src.ingestion.download.github_source.get_file_metadata", return_value=fake_meta), \
             mock.patch("src.ingestion.download.github_source.download_bytes", return_value=content_bytes):
            return download.fetch_and_store(
                repo="fake/repo",
                branch="main",
                remote_path="fake_matches_2099.csv",
                local_path=self.local_path,
                repo_commit_sha="0000000",
                tour="ATP",
                category="matches",
            )

    def test_first_download_writes_file(self):
        record = self._fetch(b"header\n1,2,3\n")
        self.assertEqual(record["status"], "downloaded")
        self.assertTrue(self.local_path.exists())

    def test_identical_second_download_is_noop(self):
        self._fetch(b"header\n1,2,3\n")
        original_bytes = self.local_path.read_bytes()
        record = self._fetch(b"header\n1,2,3\n")
        self.assertEqual(record["status"], "skipped_identical")
        self.assertEqual(self.local_path.read_bytes(), original_bytes)

    def test_diverging_content_never_overwrites_original(self):
        self._fetch(b"header\n1,2,3\n")
        original_bytes = self.local_path.read_bytes()
        record = self._fetch(b"header\n1,2,999\n")
        self.assertEqual(record["status"], "conflict_manual_review_required")
        # o arquivo original NAO pode ter sido alterado
        self.assertEqual(self.local_path.read_bytes(), original_bytes)
        # um arquivo de conflito separado deve existir
        conflict_path = Path(PROJECT_ROOT) / record["conflict_file"]
        self.assertTrue(conflict_path.exists())
        self.assertEqual(conflict_path.read_bytes(), b"header\n1,2,999\n")
        conflict_path.unlink()


@unittest.skipUnless(MANIFEST_JSON.exists(), "manifesto de ingestao ainda nao foi gerado")
class TestIngestedDataIntegrity(unittest.TestCase):
    """Valida os dados efetivamente baixados para data/raw/ (Fase 1 real)."""

    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST_JSON.read_text(encoding="utf-8"))

    def test_manifest_has_no_issues(self):
        self.assertEqual(self.manifest["n_issues"], 0, self.manifest["issues"])

    def test_all_expected_files_present_on_disk(self):
        for tour_key, source in SOURCES.items():
            for category, files in source["files"].items():
                for file_name in files:
                    path = source["local_dir"] / file_name
                    self.assertTrue(path.exists(), f"arquivo ausente: {path}")

    def test_manifest_sha256_matches_files_on_disk(self):
        for record in self.manifest["files"]:
            if record.get("status") not in ("downloaded", "skipped_identical"):
                continue
            local_path = Path(PROJECT_ROOT) / record["local_path"]
            expected_sha = record.get("sha256") or record.get("existing_sha256")
            self.assertEqual(download.sha256_file(local_path), expected_sha, local_path)

    def test_matches_files_have_rows_and_expected_stat_columns(self):
        stat_cols = {"w_ace", "w_df", "l_ace", "l_df", "w_svpt", "l_svpt"}
        for tour_key, source in SOURCES.items():
            for file_name in source["files"]["matches"]:
                path = source["local_dir"] / file_name
                info = validate.inspect_csv(path)
                self.assertGreater(info["n_rows"], 0, file_name)
                self.assertTrue(stat_cols.issubset(set(info["columns"])), file_name)

    def test_atp_and_wta_matches_share_identical_schema(self):
        atp_path = SOURCES["atp"]["local_dir"] / "atp_matches_2023.csv"
        wta_path = SOURCES["wta"]["local_dir"] / "wta_matches_2023.csv"
        atp_cols = validate.inspect_csv(atp_path)["columns"]
        wta_cols = validate.inspect_csv(wta_path)["columns"]
        self.assertEqual(atp_cols, wta_cols)

    def test_players_files_share_identical_schema(self):
        atp_cols = validate.inspect_csv(SOURCES["atp"]["local_dir"] / "atp_players.csv")["columns"]
        wta_cols = validate.inspect_csv(SOURCES["wta"]["local_dir"] / "wta_players.csv")["columns"]
        self.assertEqual(atp_cols, wta_cols)

    def test_rankings_schema_difference_is_the_known_one(self):
        # Diferenca documentada: WTA rankings tem uma coluna extra "tours".
        atp_cols = validate.inspect_csv(SOURCES["atp"]["local_dir"] / "atp_rankings_current.csv")["columns"]
        wta_cols = validate.inspect_csv(SOURCES["wta"]["local_dir"] / "wta_rankings_current.csv")["columns"]
        self.assertEqual(atp_cols, ["ranking_date", "rank", "player", "points"])
        self.assertEqual(wta_cols, ["ranking_date", "rank", "player", "points", "tours"])

    def test_no_ragged_rows_in_matches_files(self):
        for tour_key, source in SOURCES.items():
            for file_name in source["files"]["matches"]:
                path = source["local_dir"] / file_name
                info = validate.inspect_csv(path)
                self.assertEqual(info["ragged_rows"], 0, file_name)


if __name__ == "__main__":
    unittest.main()
