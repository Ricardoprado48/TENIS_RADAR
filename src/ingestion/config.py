"""Configuracao da Fase 1 - ingestao de dados historicos Sackmann (ATP/WTA).

Os repositorios originais JeffSackmann/tennis_atp, JeffSackmann/tennis_wta e
JeffSackmann/tennis_slam_pointbypoint deixaram de existir publicamente no
GitHub (confirmado em 2026-09-22: `api.github.com/repos/JeffSackmann/tennis_atp`
retorna 404 e a conta lista apenas 1 repositorio publico,
`tennis_MatchChartingProject`).

Usamos como fonte o mirror archival `Aneeshers/tennis-sackmann-archive`, que
declara ser copia dos dados originais de Jeff Sackmann (CC BY-NC-SA 4.0),
com snapshot de um commit upstream de 2026-06-25. Esse risco esta documentado
em docs/005_RELATORIO_INGESTAO_FASE1.md e deve ser revisado se/quando os
repositorios originais voltarem ao ar.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_RAW = PROJECT_ROOT / "data" / "raw"

YEARS = list(range(2022, 2027))  # 2022..2026

MIRROR_REPO = "Aneeshers/tennis-sackmann-archive"
MIRROR_BRANCH = "main"
MIRROR_LICENSE = "CC BY-NC-SA 4.0 (herdada de Jeff Sackmann / Tennis Abstract)"

SOURCES = {
    "atp": {
        "tour": "ATP",
        "mirror_dir": "atp",
        "local_dir": DATA_RAW / "sackmann_atp",
        "original_repo": "JeffSackmann/tennis_atp",
        "original_status": "indisponivel (HTTP 404 em api.github.com desde ~2026-06, confirmado 2026-09-20/22)",
        "files": {
            "matches": [f"atp_matches_{year}.csv" for year in YEARS],
            "players": ["atp_players.csv"],
            "rankings": ["atp_rankings_20s.csv", "atp_rankings_current.csv"],
            "docs": ["matches_data_dictionary.txt"],
        },
    },
    "wta": {
        "tour": "WTA",
        "mirror_dir": "wta",
        "local_dir": DATA_RAW / "sackmann_wta",
        "original_repo": "JeffSackmann/tennis_wta",
        "original_status": "indisponivel (HTTP 404 em api.github.com desde ~2026-06, confirmado 2026-09-20/22)",
        "files": {
            "matches": [f"wta_matches_{year}.csv" for year in YEARS],
            "players": ["wta_players.csv"],
            "rankings": ["wta_rankings_20s.csv", "wta_rankings_current.csv"],
            "docs": [],  # o mirror nao possui data dictionary separado para WTA
        },
    },
}

MANIFEST_JSON = DATA_RAW / "ingestion_manifest.json"
MANIFEST_MD = DATA_RAW / "ingestion_manifest.md"
