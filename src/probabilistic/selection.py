"""Escolha da configuracao (variant, window) por tour/mercado (item 2), com
tratamento separado para Grass (item 3).

Configuracao "base" (Hard/Clay, e ponto de partida para Grass): lida
diretamente de data/outputs/phase5/classificacao_mercados.csv -- a "melhor
abordagem" ja determinada objetivamente na Fase 5 (mais folds vencidos,
maior melhora relativa media, menor desvio-padrao entre folds). Nao
reajustada aqui.

Configuracao de Grass: quando o mercado tem uma variante "matchup" (Serve x
Return) alem da "isolated" (so sacador) -- caso de aces_player e
total_aces_match, nao de double_faults_player, que a Fase 4 nunca modelou
com devolvedor -- comparamos as duas SOMENTE nas linhas de Grass, na MESMA
janela ja escolhida para aquele tour/mercado (para isolar a pergunta "o
devolvedor ajuda em Grass?" da pergunta "qual janela usar?", ja respondida
separadamente). Decisao 100% por MAE fora da amostra em Grass -- nunca
fixada a priori (item 3: "Nao decidir antecipadamente qual usar").
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import config as cfg

_KNOWN_VARIANTS = ["history_mean", "isolated", "matchup", "oppadj"]


@dataclass(frozen=True)
class MarketConfig:
    tour: str
    market: str
    base_variant: str
    base_window: str
    grass_variant: str
    grass_window: str
    grass_compared: bool  # True se isolated x matchup foi comparado em Grass
    grass_mae_isolated: float | None
    grass_mae_matchup: float | None
    grass_n: int | None


def _parse_melhor_abordagem(s: str) -> tuple[str, str]:
    for v in sorted(_KNOWN_VARIANTS, key=len, reverse=True):
        prefix = v + "_"
        if s.startswith(prefix):
            return v, s[len(prefix):]
    raise ValueError(f"nao foi possivel separar variant/window de '{s}'")


def load_base_configs() -> pd.DataFrame:
    path = cfg.PHASE5_DIR / "classificacao_mercados.csv"
    df = pd.read_csv(path)
    df = df[df["market"].isin(cfg.MARKETS)].copy()
    parsed = df["melhor_abordagem"].apply(_parse_melhor_abordagem)
    df["variant"] = [p[0] for p in parsed]
    df["window"] = [p[1] for p in parsed]
    return df[["tour", "market", "variant", "window", "decisao"]]


def _load_predictions(tour: str) -> pd.DataFrame:
    frames = [
        pd.read_parquet(cfg.PHASE4_PREDICTIONS_DIR / f"predictions_{tour}_{fold}.parquet")
        for fold in cfg.FOLDS
    ]
    return pd.concat(frames, ignore_index=True)


def _mae(actual: pd.Series, pred: pd.Series) -> tuple[float | None, int]:
    a = pd.to_numeric(actual, errors="coerce")
    p = pd.to_numeric(pred, errors="coerce")
    mask = a.notna() & p.notna()
    n = int(mask.sum())
    if n == 0:
        return None, 0
    return float((a[mask] - p[mask]).abs().mean()), n


def resolve_market_config(tour: str, market: str, base_row: pd.Series,
                           predictions_by_tour: dict[str, pd.DataFrame]) -> MarketConfig:
    base_variant, base_window = base_row["variant"], base_row["window"]
    actual_col = cfg.ACTUAL_COL[market]

    matchup_col = cfg.pred_column_name(market, "matchup", base_window)
    isolated_col = cfg.pred_column_name(market, "isolated", base_window)

    df = predictions_by_tour[tour]
    # double_faults_player nunca teve uma variante "matchup" separada na
    # Fase 4 (mesma coluna serviria para as duas "variantes", o que tornaria
    # a comparacao vazia/enganosa) -- so comparamos isolated x matchup em
    # Grass quando as duas colunas de fato existem e sao diferentes.
    has_both = matchup_col in df.columns and isolated_col in df.columns and matchup_col != isolated_col
    if not has_both:
        return MarketConfig(
            tour=tour, market=market, base_variant=base_variant, base_window=base_window,
            grass_variant=base_variant, grass_window=base_window,
            grass_compared=False, grass_mae_isolated=None, grass_mae_matchup=None, grass_n=None,
        )

    grass = df.loc[df["surface"] == "Grass"]
    mae_iso, n_iso = _mae(grass[actual_col], grass[isolated_col])
    mae_mu, n_mu = _mae(grass[actual_col], grass[matchup_col])

    if mae_iso is None or mae_mu is None:
        grass_variant = base_variant
    else:
        grass_variant = "isolated" if mae_iso < mae_mu else "matchup"

    return MarketConfig(
        tour=tour, market=market, base_variant=base_variant, base_window=base_window,
        grass_variant=grass_variant, grass_window=base_window,
        grass_compared=True, grass_mae_isolated=mae_iso, grass_mae_matchup=mae_mu,
        grass_n=n_iso or n_mu,
    )


def build_all_configs() -> list[MarketConfig]:
    base_df = load_base_configs()
    predictions_by_tour = {tour: _load_predictions(tour) for tour in cfg.TOURS}
    out = []
    for _, row in base_df.iterrows():
        out.append(resolve_market_config(row["tour"], row["market"], row, predictions_by_tour))
    return out


def configs_to_frame(configs: list[MarketConfig]) -> pd.DataFrame:
    return pd.DataFrame([{
        "tour": c.tour, "market": c.market,
        "base_variant": c.base_variant, "base_window": c.base_window,
        "grass_variant": c.grass_variant, "grass_window": c.grass_window,
        "grass_compared": c.grass_compared,
        "grass_mae_isolated": c.grass_mae_isolated, "grass_mae_matchup": c.grass_mae_matchup,
        "grass_n": c.grass_n,
        "grass_diff_from_base": c.grass_variant != c.base_variant,
    } for c in configs])
