"""Formulas de saque/devolucao (Fase 3, itens 2 e 3 da instrucao).

Todas as metricas sao expressas como razao numerador/denominador (CLAUDE.md
#5: preferir "aces / service_points" a "aces / partida"). As agregacoes
historicas somam numerador e denominador separadamente ao longo da janela e
so entao dividem -- nunca fazem media simples de percentuais por partida
(evita o problema de "media de razoes" distorcer partidas com poucos pontos).

Hold% e Break% nao existem como coluna bruta (os dados Sackmann sao
agregados por partida, sem log jogo a jogo). Sao derivados por uma
propriedade da propria definicao de break point: como o game de saque
termina no instante em que um break point e convertido, no maximo 1 break
point por game pode ser "convertido" -- logo
    games quebrados no saque = break_points_faced - break_points_saved
e exatamente a contagem de games perdidos no saque (nao uma aproximacao).
O mesmo vale, espelhado, para `break_points_converted` (games quebrados na
devolucao), que a Fase 2 ja calcula. Ver docs/007 secao 3 para a
justificativa completa.
"""

from __future__ import annotations

import pandas as pd

# ---------------------------------------------------------------------------
# colunas derivadas adicionadas a uma copia da tabela de partidas antes de
# qualquer agregacao historica. Todas sao aritmetica simples sobre colunas
# Int64 anulaveis ja existentes na Fase 2; nulos se propagam automaticamente.
# ---------------------------------------------------------------------------


def add_derived_columns(table: pd.DataFrame) -> pd.DataFrame:
    df = table.copy()

    df["second_serves_in"] = df["service_points"] - df["first_serves_in"]
    df["service_points_won"] = df["first_serve_points_won"] + df["second_serve_points_won"]
    df["service_games_held"] = df["service_games"] - (df["break_points_faced"] - df["break_points_saved"])

    df["opponent_second_serves_in"] = df["return_points"] - df["opponent_first_serves_in"]
    df["return_points_won"] = df["return_points"] - (
        df["opponent_first_serve_points_won"] + df["opponent_second_serve_points_won"]
    )
    df["first_serve_return_points_won"] = df["opponent_first_serves_in"] - df["opponent_first_serve_points_won"]
    df["second_serve_return_points_won"] = df["opponent_second_serves_in"] - df["opponent_second_serve_points_won"]

    derived_int_cols = [
        "second_serves_in", "service_points_won", "service_games_held",
        "opponent_second_serves_in", "return_points_won",
        "first_serve_return_points_won", "second_serve_return_points_won",
    ]
    for col in derived_int_cols:
        df[col] = pd.array(pd.to_numeric(df[col], errors="coerce"), dtype="Int64")

    return df


# ---------------------------------------------------------------------------
# registro de metricas: nome -> (coluna_numerador, coluna_denominador)
# ---------------------------------------------------------------------------

SERVE_METRICS = {
    "ace_rate": ("aces", "service_points"),
    "double_fault_rate": ("double_faults", "service_points"),
    "first_serve_in_pct": ("first_serves_in", "service_points"),
    "first_serve_points_won_pct": ("first_serve_points_won", "first_serves_in"),
    "second_serve_points_won_pct": ("second_serve_points_won", "second_serves_in"),
    "service_points_won_pct": ("service_points_won", "service_points"),
    "break_points_saved_pct": ("break_points_saved", "break_points_faced"),
    "hold_pct": ("service_games_held", "service_games"),
}

RETURN_METRICS = {
    "ace_allowed_rate": ("opponent_aces", "return_points"),
    "return_points_won_pct": ("return_points_won", "return_points"),
    "first_serve_return_points_won_pct": ("first_serve_return_points_won", "opponent_first_serves_in"),
    "second_serve_return_points_won_pct": ("second_serve_return_points_won", "opponent_second_serves_in"),
    "break_points_created_per_return_game": ("break_points_created", "opponent_service_games"),
    "break_conversion_pct": ("break_points_converted", "break_points_created"),
    "break_pct": ("break_points_converted", "opponent_service_games"),
}

ALL_METRICS = {"serve": SERVE_METRICS, "return": RETURN_METRICS}


def base_value_columns() -> list[str]:
    """Todas as colunas numerador/denominador usadas por algum metrico,
    deduplicadas -- sao exatamente as colunas que precisam ser agregadas
    (somadas) ao longo das janelas historicas."""

    cols = set()
    for metrics in ALL_METRICS.values():
        for num, den in metrics.values():
            cols.add(num)
            cols.add(den)
    return sorted(cols)
