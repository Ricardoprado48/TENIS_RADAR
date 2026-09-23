"""Camada operacional simples sobre a Fase 11 (forward test) -- reduz a
rotina diaria do usuario a 4 comandos claros. Nao recalcula, nao redefine e
nao duplica nenhuma logica ja existente nas Fases 8-11: cada modo abaixo so
chama, na ordem certa, funcoes ja publicadas em `src.radar.build`,
`src.forward.build`, `src.forward.odds_snapshots`, `src.forward.predictions`,
`src.forward.settlement` e `src.pricing.odds`.

Nao altera modelos, features, calibracao, regras, thresholds ou a estrutura
de dados de nenhuma fase anterior. Nao busca odds automaticamente em nenhuma
casa de apostas (a coleta continua manual, Fase 9/11). Nao calcula stake
real, nao faz aposta, nao cria interface, nao avanca para a Fase 12.

Uso:

    python scripts/daily_forward_workflow.py morning [csv_partidas_futuras]
    python scripts/daily_forward_workflow.py odds [--prediction-id ID --bookmaker NOME --decimal-odds ODD [--collected-at TS]] [--input-json ARQ]
    python scripts/daily_forward_workflow.py settle [--input-json ARQ]
    python scripts/daily_forward_workflow.py report

morning  -- roda o radar (Fase 8), registra no forward test (Fase 11) toda
            oportunidade ja classificada e ainda nao registrada, e mostra um
            resumo das partidas do dia. Nao busca bookmaker.
odds     -- sem argumentos: orienta quais previsoes registradas ainda estao
            em aberto e qual foi a ultima odd conhecida de cada uma. Com
            --prediction-id/--decimal-odds (ou --input-json, para lote):
            grava um novo snapshot de odd (Fase 11) e mostra a comparacao
            dessa odd com o modelo (probabilidade, odd justa, edge).
settle   -- registra resultados pos-jogo (--input-json, uma lista de objetos
            com os campos de `results.record_result`) e roda o settlement
            (WIN/LOSS/VOID/UNRESOLVED/BOOKMAKER_RULE_REQUIRED), recalculando
            metricas, paper test e CLV. Sem --input-json, so reprocessa o
            settlement com os resultados ja registrados.
report   -- imprime o relatorio diario, o dashboard cumulativo e o tamanho
            atual da amostra registrada.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.forward import build as fwd_build  # noqa: E402
from src.forward import config as fwd_cfg  # noqa: E402
from src.forward import odds_snapshots as fwd_snaps  # noqa: E402
from src.forward import predictions as fwd_preds  # noqa: E402
from src.forward import settlement as fwd_settle  # noqa: E402
from src.pricing import odds as pricing_odds  # noqa: E402
from src.radar import build as radar_build  # noqa: E402

_TERMINAL_SETTLEMENTS = {fwd_cfg.SETTLEMENT_WIN, fwd_cfg.SETTLEMENT_LOSS, fwd_cfg.SETTLEMENT_VOID}


def _fmt_pct(x) -> str:
    return f"{x * 100:.1f}%" if x == x else "N/A"


def _fmt_odds(x) -> str:
    return f"{x:.2f}" if x == x else "N/A"


# ---------------------------------------------------------------------------
# morning
# ---------------------------------------------------------------------------

def _mode_morning(args: argparse.Namespace) -> int:
    radar_summary = radar_build.run(args.raw_path)
    register_result = fwd_build.register_day()

    print("=== RADAR DO DIA (Fase 8) ===")
    print(f"Partidas brutas recebidas: {radar_summary['n_matches_raw']}")
    print(f"Partidas resolvidas e utilizaveis: {radar_summary['n_matches_resolved_usable']}")
    print(f"Partidas nao resolvidas: {radar_summary['n_matches_unresolved']}")
    print(f"Linhas de preco geradas: {radar_summary['n_price_rows']}")
    print(f"Candidatos do radar (antes da Fase 9/10): {radar_summary['n_radar_candidates']}")
    print()
    print("=== REGISTRO NO FORWARD TEST (Fase 11) ===")
    print(f"Novas previsoes registradas: {register_result['n_registered']}")
    print(f"Ja registradas anteriormente (ignoradas): {register_result['n_skipped_duplicates']}")
    if register_result["n_rejected_overwrite_attempts"]:
        print(
            f"ALERTA -- tentativa(s) de sobrescrita rejeitada(s): "
            f"{register_result['n_rejected_overwrite_attempts']}"
        )
    print()
    print(
        "Nenhuma casa de apostas foi consultada nesta etapa -- a coleta de "
        "odds continua manual (Fase 9/11, use o modo 'odds' a seguir)."
    )
    return 0


# ---------------------------------------------------------------------------
# odds
# ---------------------------------------------------------------------------

def _guidance_odds(predictions) -> None:
    if predictions.empty:
        print("Nenhuma previsao registrada ainda. Rode o modo 'morning' primeiro.")
        return

    settlements = fwd_settle.latest_settlements()
    terminal_ids = set()
    if not settlements.empty:
        terminal_ids = set(
            settlements.loc[settlements["settlement"].isin(_TERMINAL_SETTLEMENTS), "prediction_id"]
        )
    open_preds = predictions[~predictions["prediction_id"].isin(terminal_ids)]

    movement = fwd_snaps.summarize_odds_movement()
    movement_by_id = (
        {r["prediction_id"]: r for r in movement.to_dict(orient="records")} if not movement.empty else {}
    )

    print(f"{len(open_preds)} previsao(oes) em aberto (sem settlement final):")
    print()
    for row in open_preds.to_dict(orient="records"):
        mv = movement_by_id.get(row["prediction_id"])
        last_txt = (
            f"ultima odd observada: {_fmt_odds(mv['last_observed_odds'])} "
            f"({mv['n_snapshots']} leitura(s))"
            if mv else "nenhuma leitura de odd registrada"
        )
        print(
            f"  {row['prediction_id']}  {row['tour']} {row['market']} {row['player']} "
            f"{str(row['side']).capitalize()} {row['line']}"
        )
        print(
            f"    modelo: {_fmt_pct(row['operational_probability'])} "
            f"(odd justa {_fmt_odds(row['fair_odds'])})  |  "
            f"classificacao: {row['classification']}  |  {last_txt}"
        )
    print()
    print("Para gravar uma nova leitura manual de odd:")
    print(
        "  python scripts/daily_forward_workflow.py odds --prediction-id <id> "
        "--bookmaker Betano --decimal-odds 1.80"
    )
    print(
        "Em lote: --input-json arquivo.json (lista de objetos "
        "{prediction_id, bookmaker, decimal_odds, collected_at})"
    )


def _compare_with_model(prediction_row: dict, decimal_odds: float) -> str:
    model_prob = prediction_row.get("operational_probability")
    fair_odds = prediction_row.get("fair_odds")
    implied = float(pricing_odds.implied_probability(decimal_odds))
    edge = (model_prob - implied) if model_prob == model_prob and implied == implied else float("nan")
    edge_txt = f"{edge * 100:+.1f} p.p." if edge == edge else "N/A"
    return (
        f"    {prediction_row['market']} {prediction_row['player']} "
        f"{str(prediction_row['side']).capitalize()} {prediction_row['line']}  --  "
        f"prob. modelo: {_fmt_pct(model_prob)} | odd justa: {_fmt_odds(fair_odds)} | "
        f"odd observada: {_fmt_odds(decimal_odds)} | prob. implicita: {_fmt_pct(implied)} | "
        f"edge (modelo - implicita): {edge_txt}"
    )


def _odds_entries(args: argparse.Namespace) -> list[dict]:
    if args.input_json:
        with open(args.input_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else [data]
    if args.prediction_id and args.decimal_odds is not None:
        return [{
            "prediction_id": args.prediction_id,
            "bookmaker": args.bookmaker,
            "decimal_odds": args.decimal_odds,
            "collected_at": args.collected_at,
        }]
    return []


def _mode_odds(args: argparse.Namespace) -> int:
    predictions = fwd_preds.load_predictions()
    preds_by_id = (
        {r["prediction_id"]: r for r in predictions.to_dict(orient="records")} if not predictions.empty else {}
    )

    entries = _odds_entries(args)
    if not entries:
        _guidance_odds(predictions)
        return 0

    for entry in entries:
        pid = entry["prediction_id"]
        decimal_odds = float(entry["decimal_odds"])
        result_df = fwd_build.record_odds_for_prediction(
            pid, entry.get("bookmaker", "Betano"), decimal_odds, entry.get("collected_at"),
        )
        print(f"{pid}: {len(result_df)} snapshot(s) no total registrado(s) para esta previsao.")
        row = preds_by_id.get(pid)
        if row is not None:
            print(_compare_with_model(row, decimal_odds))
        else:
            print("    ALERTA: prediction_id nao encontrado em forward_predictions.parquet.")
        print()
    return 0


# ---------------------------------------------------------------------------
# settle
# ---------------------------------------------------------------------------

def _mode_settle(args: argparse.Namespace) -> int:
    recorded = []
    if args.input_json:
        with open(args.input_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        entries = data if isinstance(data, list) else [data]
        for entry in entries:
            recorded.append(fwd_build.record_match_result(entry))

    settle_result = fwd_build.settle_day()
    print(json.dumps(
        {"results_recorded": recorded, "settle": settle_result},
        indent=2, ensure_ascii=False, default=str,
    ))
    return 0


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def _mode_report(args: argparse.Namespace) -> int:
    predictions = fwd_preds.load_predictions()
    print(fwd_build.daily_report())
    print()
    print("=" * 40)
    print()
    print(fwd_build.cumulative_dashboard())
    print()
    print(f"Tamanho atual da amostra (forward_predictions.parquet): {len(predictions)} previsao(oes) registrada(s).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)

    p_morning = sub.add_parser(
        "morning",
        help="Roda o radar (Fase 8) e registra previsoes elegiveis no forward test (Fase 11). Nao busca bookmaker.",
    )
    p_morning.add_argument(
        "raw_path", nargs="?", default=None,
        help="CSV de partidas futuras (opcional; usa o mais recente em data/raw/phase8/ por padrao)",
    )

    p_odds = sub.add_parser(
        "odds",
        help=(
            "Sem argumentos: orienta quais previsoes ainda estao em aberto. "
            "Com --prediction-id/--decimal-odds (ou --input-json): grava snapshot e compara com o modelo."
        ),
    )
    p_odds.add_argument("--prediction-id", dest="prediction_id", default=None)
    p_odds.add_argument("--bookmaker", default="Betano")
    p_odds.add_argument("--decimal-odds", dest="decimal_odds", type=float, default=None)
    p_odds.add_argument("--collected-at", dest="collected_at", default=None)
    p_odds.add_argument("--input-json", dest="input_json", default=None)

    p_settle = sub.add_parser(
        "settle",
        help="Registra resultados pos-jogo (--input-json opcional) e roda settlement + paper test.",
    )
    p_settle.add_argument("--input-json", dest="input_json", default=None)

    sub.add_parser("report", help="Relatorio diario + dashboard cumulativo + tamanho atual da amostra.")

    args = parser.parse_args()

    if args.mode == "morning":
        return _mode_morning(args)
    if args.mode == "odds":
        return _mode_odds(args)
    if args.mode == "settle":
        return _mode_settle(args)
    if args.mode == "report":
        return _mode_report(args)
    parser.error(f"modo desconhecido: {args.mode}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
