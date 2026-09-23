"""Fonte de partidas futuras (item 1 da instrucao).

Nenhuma fonte publica e estruturada de partidas ATP/WTA (data, torneio,
tour, superficie, jogadores, rodada) se mostrou acessivel por um cliente
HTTP simples e sem bloqueio de bot neste ambiente -- ver
docs/013_RADAR_DIARIO_FASE8.md secao 1 para o registro completo da
investigacao (ESPN, ATP Tour e Sofascore retornam HTTP 403 por protecao
Akamai a clientes nao-navegador; WTA e Flashscore sao SPAs que nao
retornam nenhum dado no HTML estatico). Por isso esta fase implementa a
ingestao a partir de um ARQUIVO BRUTO local (CSV), com o mesmo contrato de
schema que uma fonte HTTP automatizada usaria se/quando uma ficar
disponivel -- cada linha preserva `source_url` e `collected_at`
(CLAUDE.md #11: preservar fonte e data de coleta), nunca inventados.

O arquivo usado nesta execucao (`data/raw/phase8/partidas_futuras_*.csv`)
foi populado com partidas reais, coletadas manualmente das paginas oficiais
ATP Tour / WTA (URLs registradas por linha) no momento da execucao desta
fase -- nao sao dados fabricados.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import config as cfg


def latest_raw_file() -> Path:
    files = sorted(cfg.PHASE8_RAW_DIR.glob("partidas_futuras_*.csv"))
    if not files:
        raise FileNotFoundError(
            f"nenhum arquivo de partidas futuras em {cfg.PHASE8_RAW_DIR} "
            "(esperado: partidas_futuras_YYYYMMDD.csv)"
        )
    return files[-1]


def load_raw_matches(path: str | Path | None = None) -> pd.DataFrame:
    """Le e valida o arquivo bruto de partidas futuras. Nao resolve
    jogadores nem calcula nada -- apenas ingestao + validacao de schema
    (item 1)."""

    if path is None:
        path = latest_raw_file()
    elif isinstance(path, str):
        path = Path(path)
    df = pd.read_csv(path, dtype=str)

    missing = [c for c in cfg.REQUIRED_RAW_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{path}: colunas obrigatorias ausentes: {missing}")

    df["tour"] = df["tour"].str.upper().str.strip()
    bad_tour = ~df["tour"].isin(cfg.TOURS)
    if bad_tour.any():
        raise ValueError(
            f"{path}: tour invalido em {int(bad_tour.sum())} linha(s): "
            f"{sorted(df.loc[bad_tour, 'tour'].unique())}"
        )

    for col in ["player_a_raw", "player_b_raw", "tournament", "round"]:
        blank = df[col].isna() | (df[col].str.strip() == "")
        if blank.any():
            raise ValueError(f"{path}: coluna '{col}' vazia em {int(blank.sum())} linha(s)")

    df["match_date"] = pd.to_datetime(df["match_date"], errors="raise")
    df["collected_at"] = pd.to_datetime(df["collected_at"], errors="raise", utc=True)
    df["surface"] = df["surface"].str.strip().str.title()

    df = df.reset_index(drop=True)
    df["raw_match_seq"] = df.index.astype(int)
    df["source_file"] = getattr(path, "name", str(path))

    return df
