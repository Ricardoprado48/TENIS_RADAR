"""Motor generico de agregacao historica point-in-time.

Regra de ouro (CLAUDE.md #3): para a partida na linha i, toda agregacao usa
SOMENTE linhas estritamente anteriores do mesmo jogador (e, quando pedido,
da mesma superficie). A ordem cronologica e dada por (tournament_date,
_seq), onde `_seq` e um numero de sequencia global estavel (a posicao da
linha na tabela de partidas da Fase 2, ja ordenada por
[tournament_date, tourney_id, match_id, result]) usado como desempate
deterministico para partidas do mesmo jogador na mesma data (ex. Davis Cup
com 2 jogos no mesmo dia). Isso e uma limitacao documentada: nao ha
timestamp de hora no dado bruto, entao a ordem intra-dia e uma convencao,
nao um fato observado -- ver docs/007.

Duas familias de janela:
  - "all_prior" / "last_n": usam cumsum().shift(1) ou shift(1).rolling(n).sum()
    -- exclui a linha atual por construcao (shift antes de somar).
  - "time" (janela em dias corridos): usa rolling baseado em data, que por
    padrao do pandas inclui a linha atual (janela fechada a direita); a
    linha atual e subtraida explicitamente do resultado para excluir-se.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

ONE_COL = "_one"


def compute_windowed_priors(
    df: pd.DataFrame,
    group_cols: list[str],
    date_col: str,
    seq_col: str,
    value_cols: list[str],
    windows: dict,
) -> pd.DataFrame:
    """Retorna um DataFrame alinhado ao index de `df` com uma coluna
    f"{value_col}__{window_name}" para cada combinacao, mais
    f"n_prior_matches__{window_name}" (contagem de partidas previas
    incluidas na janela)."""

    work = df[group_cols + [date_col, seq_col] + value_cols].copy()
    work[ONE_COL] = 1
    cols = value_cols + [ONE_COL]
    work_sorted = work.sort_values(group_cols + [date_col, seq_col])

    pieces = []
    for window_name, spec in windows.items():
        wtype = spec["type"]
        if wtype == "all_prior":
            grouped = work_sorted.groupby(group_cols, sort=False, group_keys=False)
            out = grouped[cols].apply(lambda g: g.cumsum().shift(1))
        elif wtype == "last_n":
            n = spec["n"]
            grouped = work_sorted.groupby(group_cols, sort=False, group_keys=False)
            out = grouped[cols].apply(lambda g: g.shift(1).rolling(n, min_periods=1).sum())
        elif wtype == "time":
            days = spec["days"]

            def _time_prior(g, _cols=cols, _date_col=date_col, _days=days):
                sub = g[_cols + [_date_col]].set_index(_date_col)
                incl = sub.rolling(f"{_days}D")[_cols].sum()
                incl.index = g.index
                return incl - g[_cols].to_numpy()

            grouped = work_sorted.groupby(group_cols, sort=False, group_keys=False)
            out = grouped.apply(_time_prior)
        else:
            raise ValueError(f"tipo de janela desconhecido: {wtype}")

        out = out.reindex(df.index)
        rename_map = {c: f"{c}__{window_name}" for c in value_cols}
        rename_map[ONE_COL] = f"n_prior_matches__{window_name}"
        out = out.rename(columns=rename_map)
        pieces.append(out)

    result = pd.concat(pieces, axis=1)
    # contagens sao inteiras; ratios ficam em float (NaN nativo, nao Int64,
    # pois sao somas de contagens que ja tratam ausencia via skipna do pandas)
    count_cols = [c for c in result.columns if c.startswith("n_prior_matches__")]
    for c in count_cols:
        result[c] = result[c].fillna(0).astype("int64")
    return result


def compute_decay_priors(
    df: pd.DataFrame,
    group_cols: list[str],
    date_col: str,
    seq_col: str,
    value_cols: list[str],
    halflife_days: float,
    suffix: str,
) -> pd.DataFrame:
    """Soma ponderada por decaimento exponencial (meia-vida configuravel em
    dias) das colunas de `value_cols`, estritamente anterior a cada linha.
    Complexidade O(n) por jogador via recorrencia:

        D_i = 0.5 ** (gap_dias / halflife) * (D_{i-1} + v_{i-1})

    onde D_i e a soma decaida de todas as partidas anteriores, avaliada na
    data da partida i. Valores ausentes (NA) contam como contribuicao 0 no
    acumulador, mas o relogio (last_date) sempre avanca -- o tempo decorrido
    e real mesmo quando a estatistica daquela partida especifica nao foi
    reportada.
    """

    work = df[group_cols + [date_col, seq_col] + value_cols].copy()
    work = work.sort_values(group_cols + [date_col, seq_col])

    n = len(work)
    out_arrays = {c: np.full(n, np.nan, dtype="float64") for c in value_cols}
    match_count_out = np.zeros(n, dtype="int64")

    values = {c: work[c].to_numpy(dtype="float64") for c in value_cols}
    dates = work[date_col].to_numpy()
    group_keys = work[group_cols].apply(tuple, axis=1).to_numpy() if len(group_cols) > 1 else work[group_cols[0]].to_numpy()

    running = {c: 0.0 for c in value_cols}
    running_raw_count = 0  # contagem real (NAO decaida) de partidas anteriores
    last_date = None
    last_key = None

    positions = np.arange(n)
    for pos in positions:
        key = group_keys[pos]
        if key != last_key:
            running = {c: 0.0 for c in value_cols}
            running_raw_count = 0
            last_date = None

        if last_date is None:
            decay = 0.0
        else:
            gap_days = (dates[pos] - last_date) / np.timedelta64(1, "D")
            decay = 0.5 ** (gap_days / halflife_days)

        for c in value_cols:
            prior_val = running[c] * decay
            out_arrays[c][pos] = prior_val
            v = values[c][pos]
            running[c] = prior_val + (v if not np.isnan(v) else 0.0)

        # a contagem de amostra reportada e o numero REAL de partidas
        # anteriores (nao decaido) -- um "n_prior_matches" decaido perderia
        # sentido como indicador de tamanho de amostra (tenderia a 0 mesmo
        # havendo muitas partidas antigas reais). Ver docs/007 secao 5.
        match_count_out[pos] = running_raw_count
        running_raw_count += 1

        last_date = dates[pos]
        last_key = key

    result = pd.DataFrame(index=work.index)
    for c in value_cols:
        result[f"{c}__{suffix}"] = out_arrays[c]
    result[f"n_prior_matches__{suffix}"] = match_count_out
    return result.reindex(df.index)
