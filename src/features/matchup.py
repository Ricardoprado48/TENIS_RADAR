"""Features de confronto (Serve A x Return B / Serve B x Return A) e ajuste
por forca do adversario (Fase 3, itens 8 e 9 da instrucao).

Item 8 -- matchup: como a tabela de perfil (profile.py) ja tem 1 linha por
jogador por partida, e cada match_id tem exatamente 2 linhas (uma por
jogador), obter as colunas do ADVERSARIO naquela mesma partida e um simples
self-join por (match_id, opponent_id == player_id da outra linha) -- nao
precisa recalcular nada, so trazer as colunas player_* da linha do
adversario, renomeadas para opponent_*. Como sao os proprios valores
point-in-time do adversario (calculados em profile.py usando somente as
partidas anteriores DELE), isso nao introduz nenhum vazamento: nenhuma
informacao da partida atual entra na comparacao.

Para conter o numero de colunas, o self-join e os comparativos de matchup
sao feitos apenas para as janelas "headline" (config.HEADLINE_WINDOWS).

Item 9 -- ajuste por adversario: para cada partida anterior do jogador,
`opponent_serve_ace_rate_{w}` / `opponent_return_ace_allowed_rate_{w}` /
`opponent_serve_hold_pct_{w}` / `opponent_return_break_pct_{w}` (colunas ja
point-in-time, geradas no self-join acima) descrevem a forca do adversario
enfrentado NAQUELE momento. Fazendo a MEDIA simples dessas colunas ao longo
do historico anterior do proprio jogador (mesmo motor de janelas, agora
agregando uma media em vez de uma soma de contagens brutas), obtemos "forca
media dos adversarios enfrentados". O ajuste e a diferenca simples entre a
taxa do jogador e essa media -- metodologia mais simples possivel, sem
nenhuma dependencia de dados futuros (cada termo da media usa apenas o
estado do adversario ANTES daquela partida especifica, e a media em si so
usa partidas ANTERIORES do proprio jogador).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import HEADLINE_WINDOWS
from .rolling import compute_windowed_priors

# metricas espelhadas no self-join (todas as janelas headline, ambos os lados)
_MATCHUP_METRIC_SUFFIXES = [
    "ace_rate", "double_fault_rate", "first_serve_in_pct",
    "first_serve_points_won_pct", "second_serve_points_won_pct",
    "service_points_won_pct", "break_points_saved_pct", "hold_pct",
]
_RETURN_METRIC_SUFFIXES = [
    "ace_allowed_rate", "return_points_won_pct",
    "first_serve_return_points_won_pct", "second_serve_return_points_won_pct",
    "break_points_created_per_return_game", "break_conversion_pct", "break_pct",
]

# as 4 metricas explicitamente pedidas no item 9 (opponent adjustment)
_ADJUSTMENT_SPECS = [
    # (nome_saida, coluna_propria, coluna_forca_do_adversario_a_media, usa_complementar)
    #
    # Ace Rate x Ace Allowed Rate medem o MESMO evento (um ace do sacador =
    # um ace sofrido pelo devolvedor), entao sao comparaveis diretamente --
    # a media tour-wide de ambas converge para o mesmo valor, entao a
    # diferenca ja fica naturalmente centrada perto de 0.
    ("opponent_adjusted_ace_rate", "player_serve_ace_rate", "opponent_return_ace_allowed_rate", False),
    ("ace_suppression", "player_return_ace_allowed_rate", "opponent_serve_ace_rate", False),
    # Hold% e Break% sao EVENTOS COMPLEMENTARES do mesmo game de saque (o
    # sacador segura OU o devolvedor quebra) -- nao sao a mesma grandeza.
    # Comparar hold_pct diretamente com break_pct do adversario deslocaria
    # a diferenca para ~ (media(hold) - media(break)) ~= 0.58 em vez de
    # ficar perto de 0 (bug encontrado e corrigido durante o desenvolvimento
    # da Fase 3 -- ver docs/007). A comparacao correta usa o COMPLEMENTAR da
    # forca do adversario: "taxa de hold esperada contra devolvedores com
    # break% medio X" = 1 - X.
    ("opponent_adjusted_hold_pct", "player_serve_hold_pct", "opponent_return_break_pct", True),
    ("opponent_adjusted_break_pct", "player_return_break_pct", "opponent_serve_hold_pct", True),
]
# ace_suppression e definida como (forca do adversario - taxa do jogador),
# pois valor positivo = suprime mais aces do que o esperado (CLAUDE.md #6).
# As demais sao (taxa do jogador - forca esperada dado o adversario).
_ADJUSTMENT_INVERT = {"ace_suppression"}

# janelas usadas no ajuste por adversario (subconjunto das headline; ver
# docstring do modulo -- mantido simples de proposito)
_ADJUSTMENT_WINDOWS = ["career", "last50"]


def _headline_player_cols() -> list[str]:
    cols = []
    for w in HEADLINE_WINDOWS:
        for m in _MATCHUP_METRIC_SUFFIXES:
            cols.append(f"player_serve_{m}_{w}")
        for m in _RETURN_METRIC_SUFFIXES:
            cols.append(f"player_return_{m}_{w}")
    return cols


def add_opponent_columns(profile: pd.DataFrame) -> pd.DataFrame:
    """Self-join: para cada linha jogador-partida, anexa as colunas
    player_serve_*/player_return_* (janelas headline) DA LINHA DO
    ADVERSARIO na mesma partida, renomeadas para opponent_serve_*/
    opponent_return_*."""

    headline_cols = _headline_player_cols()
    right = profile[["match_id", "player_id"] + headline_cols].copy()
    rename_map = {"player_id": "_opp_player_id"}
    for c in headline_cols:
        rename_map[c] = c.replace("player_", "opponent_", 1)
    right = right.rename(columns=rename_map)

    merged = profile.merge(
        right, left_on=["match_id", "opponent_id"], right_on=["match_id", "_opp_player_id"], how="left",
    )
    merged = merged.drop(columns=["_opp_player_id"])
    return merged


def add_matchup_comparatives(merged: pd.DataFrame) -> pd.DataFrame:
    """Item 8: diffs simples de matchup, sem nenhuma modelagem -- apenas
    subtracao de taxas ja calculadas. Positivo favorece o `player`."""

    new_cols = {}
    for w in HEADLINE_WINDOWS:
        new_cols[f"matchup_ace_rate_vs_allowed_{w}"] = (
            merged[f"player_serve_ace_rate_{w}"] - merged[f"opponent_return_ace_allowed_rate_{w}"]
        )
        new_cols[f"matchup_hold_vs_break_{w}"] = (
            merged[f"player_serve_hold_pct_{w}"] - merged[f"opponent_return_break_pct_{w}"]
        )
        new_cols[f"matchup_opp_ace_vs_player_allowed_{w}"] = (
            merged[f"opponent_serve_ace_rate_{w}"] - merged[f"player_return_ace_allowed_rate_{w}"]
        )
        new_cols[f"matchup_opp_hold_vs_player_break_{w}"] = (
            merged[f"opponent_serve_hold_pct_{w}"] - merged[f"player_return_break_pct_{w}"]
        )
    return pd.concat([merged, pd.DataFrame(new_cols, index=merged.index)], axis=1)


def _prior_mean(df: pd.DataFrame, value_col: str, window_name: str, spec: dict) -> pd.Series:
    """Media simples (nao ponderada por volume de pontos) do `value_col`
    sobre as partidas ANTERIORES do proprio jogador, ignorando NA. Reusa o
    motor de soma (compute_windowed_priors) sobre (valor preenchido com 0,
    indicador de presenca) e divide -- e a forma generica de fazer
    "media ignorando ausentes" com o mesmo motor point-in-time."""

    tmp = pd.DataFrame(index=df.index)
    tmp["player_id"] = df["player_id"]
    tmp["tournament_date"] = df["tournament_date"]
    tmp["_seq"] = df["_seq"]
    tmp["_val"] = df[value_col].astype("float64").fillna(0.0)
    tmp["_present"] = df[value_col].notna().astype("float64")

    priors = compute_windowed_priors(
        tmp, ["player_id"], "tournament_date", "_seq", ["_val", "_present"], {window_name: spec},
    )
    num = priors[f"_val__{window_name}"].to_numpy(dtype="float64")
    den = priors[f"_present__{window_name}"].to_numpy(dtype="float64")
    with np.errstate(divide="ignore", invalid="ignore"):
        mean = np.where(den > 0, num / den, np.nan)
    return pd.Series(mean, index=df.index)


def add_opponent_adjustment(merged: pd.DataFrame) -> pd.DataFrame:
    """Item 9: camada simples de ajuste por forca do adversario para Ace
    Rate, Ace Allowed Rate (Ace Suppression), Hold% e Break%, nas janelas
    'career' e 'last50'. Sem circularidade: a "forca media do adversario
    enfrentado" usa, para cada partida anterior, o valor point-in-time do
    adversario NAQUELE momento (ja calculado no self-join), e a media em si
    so percorre partidas anteriores do proprio jogador."""

    df = merged.copy()
    df = df.reset_index(drop=True)
    df["_seq"] = df.index

    new_cols = {}
    for w in _ADJUSTMENT_WINDOWS:
        spec = {"type": "all_prior"} if w == "career" else {"type": "last_n", "n": 50}
        for out_name, own_col_prefix, opp_strength_col_prefix, use_complement in _ADJUSTMENT_SPECS:
            own_col = f"{own_col_prefix}_{w}"
            opp_col = f"{opp_strength_col_prefix}_{w}"
            avg_opp_strength = _prior_mean(df, opp_col, f"adjwin_{w}", spec).to_numpy()
            avg_col_name = f"avg_{opp_strength_col_prefix}_faced_{w}"
            new_cols[avg_col_name] = avg_opp_strength
            expected = (1.0 - avg_opp_strength) if use_complement else avg_opp_strength
            own_val = df[own_col].to_numpy(dtype="float64")
            if out_name in _ADJUSTMENT_INVERT:
                diff = expected - own_val
            else:
                diff = own_val - expected
            new_cols[f"{out_name}_{w}"] = diff

    out = pd.concat([df, pd.DataFrame(new_cols, index=df.index)], axis=1)
    return out.drop(columns=["_seq"])


def build_matchup_table(profile: pd.DataFrame) -> pd.DataFrame:
    merged = add_opponent_columns(profile)
    merged = add_matchup_comparatives(merged)
    merged = add_opponent_adjustment(merged)
    return merged
