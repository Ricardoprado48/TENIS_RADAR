"""CLI da Fase 5: comparacao de robustez e selecao tecnica dos mercados.

Le exclusivamente data/outputs/phase4/metrics/*.csv (ja produzidos na Fase 4).
Nao treina nem ajusta nenhum modelo novo. Escreve as tabelas consolidadas em
data/outputs/phase5/ e imprime um resumo JSON no final.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from src.selection import analysis as an
from src.selection import classify as cl
from src.selection import config as cfg


def main() -> None:
    cfg.PHASE5_DIR.mkdir(parents=True, exist_ok=True)
    (cfg.PHASE5_DIR).mkdir(parents=True, exist_ok=True)

    data = an.load_metrics()
    numeric, prob, count = data["numeric"], data["prob"], data["count"]

    # --- 1) robustez temporal + melhor abordagem por mercado ---------------
    temporal_num = an.temporal_robustness(numeric, "numeric")
    temporal_prob = an.temporal_robustness(prob, "prob")
    temporal_all = pd.concat([temporal_num, temporal_prob], ignore_index=True)
    temporal_all.to_csv(cfg.PHASE5_DIR / "robustez_temporal.csv", index=False)

    best_num = an.pick_best_approach(temporal_num)
    best_prob = an.pick_best_approach(temporal_prob)
    best_all = pd.concat([best_num, best_prob], ignore_index=True)

    # --- 2) robustez por superficie ----------------------------------------
    surf_num = an.surface_robustness(numeric, "numeric", best_num)
    surf_prob = an.surface_robustness(prob, "prob", best_prob)
    surf_all = pd.concat([surf_num, surf_prob], ignore_index=True)
    surf_all.to_csv(cfg.PHASE5_DIR / "robustez_superficie.csv", index=False)

    # --- 3) robustez de janela ----------------------------------------------
    win_num = an.window_robustness(numeric, "numeric")
    win_prob = an.window_robustness(prob, "prob")
    win_all = pd.concat([win_num, win_prob], ignore_index=True)
    win_all.to_csv(cfg.PHASE5_DIR / "janelas_robustez.csv", index=False)
    best_win = pd.concat([
        an.best_window_per_group(win_num), an.best_window_per_group(win_prob),
    ], ignore_index=True)
    best_win.to_csv(cfg.PHASE5_DIR / "janelas_melhor_por_grupo.csv", index=False)

    # --- 4) Serve x Return (aces) --------------------------------------------
    sr_rows = []
    for w in ["career", "last50"]:
        sr_rows.append(an.variant_ladder_at_window(
            numeric, "numeric", ["aces_player", "total_aces_match"], w,
            ["isolated", "matchup", "oppadj"],
        ))
    serve_return = pd.concat(sr_rows, ignore_index=True)
    serve_return.to_csv(cfg.PHASE5_DIR / "serve_return_analysis.csv", index=False)

    # --- 5) Hold x Break (games) ---------------------------------------------
    hb_rows = []
    for w in ["career", "last50"]:
        hb_rows.append(an.variant_ladder_at_window(
            numeric, "numeric", ["total_games", "game_diff", "total_sets"], w,
            ["isolated", "matchup", "oppadj"],
        ))
    hold_break = pd.concat(hb_rows, ignore_index=True)
    hold_break.to_csv(cfg.PHASE5_DIR / "hold_break_analysis.csv", index=False)

    # --- 6) overdispersion (Poisson vs NegBin) --------------------------------
    over_detail = an.overdispersion_table(count)
    over_detail.to_csv(cfg.PHASE5_DIR / "overdispersion_detalhe.csv", index=False)
    over_summary = an.overdispersion_summary(count)
    over_summary.to_csv(cfg.PHASE5_DIR / "overdispersion_resumo.csv", index=False)

    # --- 7) classificacao final -----------------------------------------------
    class_num = cl.classify_markets(best_num, surf_num)
    class_prob = cl.classify_markets(best_prob, surf_prob)
    classification = pd.concat([class_num, class_prob], ignore_index=True)
    classification.to_csv(cfg.PHASE5_DIR / "classificacao_mercados.csv", index=False)

    for tour in ["ATP", "WTA"]:
        classification[classification["tour"] == tour].to_csv(
            cfg.PHASE5_DIR / f"tabela_final_{tour.lower()}.csv", index=False
        )

    summary = {
        "n_temporal_rows": len(temporal_all),
        "n_surface_rows": len(surf_all),
        "n_window_rows": len(win_all),
        "n_serve_return_rows": len(serve_return),
        "n_hold_break_rows": len(hold_break),
        "n_overdispersion_rows": len(over_detail),
        "classification_counts": {
            f"{k[0]}__{k[1]}": v
            for k, v in classification.groupby(["tour", "decisao"]).size().to_dict().items()
        },
    }
    with open(cfg.PHASE5_DIR / "phase5_summary.json", "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in summary.items()}, f, indent=2, default=str)

    print(json.dumps({str(k): str(v) for k, v in summary.items()}, indent=2))


if __name__ == "__main__":
    main()
