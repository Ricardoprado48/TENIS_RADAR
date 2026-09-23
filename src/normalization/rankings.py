"""Normalizacao do historico de rankings (ATP/WTA), point-in-time.

Trata a diferenca de schema encontrada na Fase 1 (docs/005, secao 3): o WTA
tem uma coluna extra `tours` que o ATP nao tem. Em vez de descartar a coluna
(perderia informacao) ou inventar um valor para o ATP (inventaria dado que
nao existe), a coluna `tours` e mantida no schema unificado e fica NULL
(pandas <NA>) para todas as linhas ATP -- ausencia real de dado, nao zero.
"""

import pandas as pd

from .config import RANKINGS_FILES, RAW_DIRS
from .players import canonical_player_id


def load_rankings(tour: str) -> pd.DataFrame:
    raw_dir = RAW_DIRS[tour]
    frames = []
    for file_name in RANKINGS_FILES[tour]:
        df = pd.read_csv(raw_dir / file_name)
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)

    if "tours" not in df.columns:
        df["tours"] = pd.NA
    df["tours"] = pd.array(df["tours"], dtype="Int64")

    df["tour"] = tour.upper()
    df["ranking_date"] = pd.to_datetime(df["ranking_date"], format="%Y%m%d", errors="coerce")
    df["player_id"] = [canonical_player_id(tour, pid) for pid in df["player"]]
    df["rank"] = pd.array(df["rank"], dtype="Int64")
    df["points"] = pd.array(df["points"], dtype="Int64")

    df = df.rename(columns={"player": "player_id_raw"})
    df["player_id_raw"] = df["player_id_raw"].astype("string")

    df = df[["ranking_date", "tour", "player_id", "player_id_raw", "rank", "points", "tours"]]
    df = df.sort_values(["ranking_date", "rank"]).reset_index(drop=True)

    return df
