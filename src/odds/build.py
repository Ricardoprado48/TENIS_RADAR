"""Orquestrador da Fase 9: registra odds observadas manualmente (ou em lote),
casa cada uma contra o radar ja gerado pela Fase 8, calcula
implied_probability/edge/status por edge (Fase 7, reaproveitada) e grava em
`data/outputs/phase9/`, sempre em modo append-only para o historico de
snapshots (item 11).

Nao consulta casa de apostas automaticamente por padrao (a investigacao da
Betano, item 4, e um passo separado e documentado em `betano_source.py`).
Nao calcula stake, nao faz aposta, nao cria interface.
"""

from __future__ import annotations

import json

import pandas as pd

from . import betano_source
from . import config as cfg
from . import matching
from . import pricing_compare as pc
from . import storage


def load_current_radar() -> pd.DataFrame:
    return pd.read_parquet(cfg.PHASE8_PRICES_PATH)


def validate_entry(entry: dict) -> list[tuple[str, float]]:
    """Valida uma entrada bruta e devolve a lista de (side, decimal_odds)
    presentes. Lanca ValueError com mensagem objetiva em caso de entrada
    invalida (item 14: 'mercados inexistentes')."""

    bookmaker = entry.get("bookmaker")
    if not bookmaker:
        raise ValueError("bookmaker e obrigatorio")

    tour = entry.get("tour")
    if tour not in cfg.TOURS:
        raise ValueError(f"tour invalido: {tour!r} (esperado um de {cfg.TOURS})")

    market = entry.get("market")
    if market not in cfg.ALLOWED_MARKETS:
        raise ValueError(f"mercado invalido/nao escopado nesta fase: {market!r} (esperado um de {cfg.ALLOWED_MARKETS})")

    if not entry.get("player"):
        raise ValueError("player e obrigatorio")

    line = entry.get("line")
    if line is None:
        raise ValueError("line e obrigatoria")

    sides = []
    for side in cfg.SIDES:
        val = entry.get(f"{side}_odds")
        if val is None or val == "" or (isinstance(val, float) and pd.isna(val)):
            continue
        val = float(val)
        if val <= 1.0:
            raise ValueError(f"{side}_odds invalida: {val} (odd decimal precisa ser > 1.0)")
        sides.append((side, val))

    if not sides:
        raise ValueError("informe pelo menos over_odds ou under_odds")

    return sides


def record_entry(entry: dict, prices: pd.DataFrame) -> dict:
    """Processa UMA entrada bruta (pode conter over_odds e/ou under_odds) e
    devolve as linhas prontas para persistencia + o texto compacto (item
    13) de cada lado."""

    sides = validate_entry(entry)

    bookmaker = entry["bookmaker"]
    tour = entry["tour"]
    market = entry["market"]
    player = entry["player"]
    line = float(entry["line"])
    collected_at = entry.get("collected_at") or pd.Timestamp.now("UTC").isoformat()
    source_method = entry.get("source_method", "manual")
    source_url = entry.get("source_url")

    stale = pc.staleness_warning(tour)

    over_odds = dict(sides).get("over")
    under_odds = dict(sides).get("under")
    vig = pc.overround_and_novig(over_odds, under_odds) if (over_odds and under_odds) else None

    observations = []
    comparisons = []
    reports = []

    for side, decimal_odds in sides:
        match = matching.match_against_radar(tour, market, player, line, side, prices)

        obs_row = {
            "bookmaker": bookmaker,
            "match_id": match.get("match_id", "UNMATCHED"),
            "tour": tour,
            "tournament": match.get("tournament", entry.get("tournament")),
            "player": player,
            "opponent": match.get("resolved_opponent_name", entry.get("opponent")),
            "market": market,
            "side": side,
            "line": line,
            "decimal_odds": decimal_odds,
            "collected_at": collected_at,
            "source_method": source_method,
            "source_url": source_url,
        }
        observations.append(obs_row)

        cmp_row = {
            "bookmaker": bookmaker,
            "match_id": obs_row["match_id"],
            "tour": tour,
            "market": market,
            "player": player,
            "side": side,
            "line": line,
            "decimal_odds": decimal_odds,
            "collected_at": collected_at,
            "matched": match["matched"],
            "match_reason": match.get("match_reason", ""),
            "operational_probability": match.get("operational_probability"),
            "fair_odds": match.get("fair_odds"),
            "sample_bucket_career": match.get("sample_bucket_career"),
            "restricted": match.get("restricted"),
            "restricted_motivo": match.get("restricted_motivo"),
            "extreme_probability": match.get("extreme_probability"),
            "is_candidate": match.get("is_candidate"),
            **pc.compare_one(match.get("operational_probability"), decimal_odds),
            **stale,
        }
        if vig is not None:
            cmp_row.update(vig)
        comparisons.append(cmp_row)

        reports.append(_format_report(obs_row, cmp_row, match))

    return {
        "observations": pd.DataFrame(observations),
        "comparisons": pd.DataFrame(comparisons),
        "reports": reports,
    }


def _format_report(obs_row: dict, cmp_row: dict, match: dict) -> str:
    if not match["matched"]:
        return (
            f"{obs_row['player']} -- {obs_row['market']} linha {obs_row['line']} ({obs_row['side']})\n"
            f"  {obs_row['bookmaker']}: {obs_row['decimal_odds']}\n"
            f"  NAO CASADO com o radar atual: {match.get('match_reason', '')}\n"
            f"  (observacao gravada mesmo assim -- item 6, nunca perdida)\n"
        )

    p = cmp_row["operational_probability"]
    fair = match.get("fair_odds")
    fair_txt = f"{fair:.2f}" if fair == fair else "N/A"
    edge_txt = f"{cmp_row['model_edge'] * 100:+.1f} p.p." if cmp_row["model_edge"] == cmp_row["model_edge"] else "N/A"

    lines = [
        f"{match['resolved_player_name']} x {match['resolved_opponent_name']}",
        "",
        f"{obs_row['player']} -- {obs_row['market']} linha {obs_row['line']} ({obs_row['side']})",
        "",
        f"Modelo: {p * 100:.1f}%",
        f"Odd justa: {fair_txt}",
        "",
        f"{obs_row['bookmaker']}: {obs_row['decimal_odds']}",
        "",
        f"Edge vs preco: {edge_txt}",
        f"Classificacao: {cmp_row['status']}",
    ]
    for label, _e in cfg.EDGE_LEVELS:
        min_odds = cmp_row.get(f"odd_minima_{label}")
        pct = label.replace("_", ".").replace("pct", "%")
        hit = min_odds == min_odds and obs_row["decimal_odds"] >= min_odds
        lines.append(f"Edge minimo {pct}: {'ATINGIDO' if hit else 'NAO ATINGIDO'}")
    lines += [
        "",
        f"Dados historicos atualizados ate: {cmp_row['historical_data_cutoff']}",
        f"Defasagem: {cmp_row['data_staleness_days']} dias",
    ]
    if "overround" in cmp_row and cmp_row["overround"] == cmp_row["overround"]:
        lines.append(f"Overround: {cmp_row['overround'] * 100:.1f}%")
    return "\n".join(lines)


def run_manual_entries(entries: list[dict]) -> dict:
    prices = load_current_radar()

    all_obs = []
    all_cmp = []
    all_reports = []
    errors = []

    for i, entry in enumerate(entries):
        try:
            result = record_entry(entry, prices)
        except ValueError as exc:
            errors.append({"entry_index": i, "entry": entry, "error": str(exc)})
            continue
        all_obs.append(result["observations"])
        all_cmp.append(result["comparisons"])
        all_reports.extend(result["reports"])

    n_recorded = 0
    if all_obs:
        obs_df = pd.concat(all_obs, ignore_index=True)
        cmp_df = pd.concat(all_cmp, ignore_index=True)
        combined_obs = storage.append_observations(obs_df)
        storage.append_comparisons(cmp_df)
        storage.rebuild_snapshots_history()
        storage.write_daily_check(cmp_df)
        n_recorded = len(obs_df)
        n_total_ledger = len(combined_obs)
    else:
        n_total_ledger = len(pd.read_parquet(cfg.ODDS_OBSERVED_PATH)) if cfg.ODDS_OBSERVED_PATH.exists() else 0

    return {
        "n_entries_submitted": len(entries),
        "n_entries_rejected": len(errors),
        "n_observation_rows_recorded_this_run": n_recorded,
        "n_observation_rows_total_ledger": n_total_ledger,
        "errors": errors,
        "reports": all_reports,
    }


def run(entries: list[dict] | None = None, investigate_betano: bool = True) -> dict:
    cfg.PHASE9_DIR.mkdir(parents=True, exist_ok=True)

    betano_result = betano_source.run_betano_investigation() if investigate_betano else None

    manual_result = run_manual_entries(entries or [])

    summary = {
        "betano_automatic_collection_adequate": betano_result["adequate_automatic_source_found"] if betano_result else None,
        "manual_entry_operational": True,
        "n_entries_submitted": manual_result["n_entries_submitted"],
        "n_entries_rejected": manual_result["n_entries_rejected"],
        "n_observation_rows_recorded_this_run": manual_result["n_observation_rows_recorded_this_run"],
        "n_observation_rows_total_ledger": manual_result["n_observation_rows_total_ledger"],
        "edge_levels": cfg.EDGE_LEVELS,
        "allowed_markets": cfg.ALLOWED_MARKETS,
    }
    with open(cfg.PHASE9_DIR / "phase9_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str, ensure_ascii=False)

    return {**summary, "reports": manual_result["reports"], "errors": manual_result["errors"]}
