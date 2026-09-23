"""Tabela dimensao de jogadores, com identidade canonica por tour.

Regra (CLAUDE.md #10 e #18): manter ATP e WTA como competicoes separadas.
Os IDs numericos brutos do Sackmann NAO sao globalmente unicos entre ATP e
WTA (as faixas de player_id se sobrepoem), entao o player_id canonico usado
em todo o pipeline e f"{TOUR}-{player_id_bruto}", por exemplo "ATP-100001" e
"WTA-100001" sao jogadores diferentes.
"""

import pandas as pd

from .config import PLAYERS_FILES, RAW_DIRS


PLAYERS_DTYPES = {
    "player_id": "string",
    "name_first": "string",
    "name_last": "string",
    "hand": "string",
    "ioc": "string",
    "wikidata_id": "string",
}


def canonical_player_id(tour: str, raw_player_id) -> str:
    return f"{tour.upper()}-{raw_player_id}"


def load_players(tour: str) -> pd.DataFrame:
    raw_dir = RAW_DIRS[tour]
    frames = []
    for file_name in PLAYERS_FILES[tour]:
        df = pd.read_csv(raw_dir / file_name, dtype=PLAYERS_DTYPES)
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)

    df["tour"] = tour.upper()
    df["player_id"] = [canonical_player_id(tour, pid) for pid in df["player_id"]]
    df["player_id_raw"] = df["player_id"].str.split("-", n=1).str[1]
    df["name"] = (df["name_first"].fillna("") + " " + df["name_last"].fillna("")).str.strip()
    df["dob"] = pd.to_datetime(df["dob"], format="%Y%m%d", errors="coerce")

    df = df.rename(columns={"ioc": "country", "height": "height_cm"})
    df["height_cm"] = pd.to_numeric(df["height_cm"], errors="coerce")

    ordered_cols = [
        "player_id", "player_id_raw", "tour", "name", "name_first", "name_last",
        "hand", "dob", "country", "height_cm", "wikidata_id",
    ]
    df = df[ordered_cols]

    dup_mask = df.duplicated(subset=["player_id"], keep=False)
    n_duplicate_ids = int(dup_mask.sum())

    return df, n_duplicate_ids
