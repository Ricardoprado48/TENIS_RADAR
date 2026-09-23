"""Politica de decisao (item 10): `evaluate_opportunity(...)` -- a unica
funcao que classifica uma oportunidade ja enriquecida (`inputs.py`) em um
dos 5 estados operacionais (item 3), com motivos, flags e metricas (item
11). Nao re-treina, nao recalibra, nao re-seleciona mercado e nao altera
nenhuma probabilidade/odd/edge ja calculada -- so aplica regras
deterministicas sobre o que ja existe.

Estrutura da decisao, em 2 etapas:

  1) GATES (item 2) -- todos precisam passar para a oportunidade "avancar"
     alem de DESCARTAR. Falha em qualquer gate -> DESCARTAR, com o motivo
     exato de cada gate que falhou (nunca um status sem justificativa).

  2) ESCADA DE CLASSIFICACAO (itens 4, 5, 6, 8, 9) -- combina o edge ja
     atingido (Fase 9), o piso minimo de edge do mercado (item 9, testado
     nesta fase, nao escolhido como padrao definitivo), a qualidade de
     amostra (item 5) e a politica de staleness (item 6) para decidir entre
     OBSERVAR / CANDIDATO_FRACO / CANDIDATO / CANDIDATO_FORTE."""

from __future__ import annotations

import math

from . import config as cfg
from . import sample_quality as sq
from . import staleness_policy as stale


def _is_missing(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v)) or v != v


def _bool_or_false(v) -> bool:
    return bool(v) if v is not None and v == v else False


def _compute_gates(row: dict) -> tuple[list[tuple[str, bool, str]], str]:
    """Retorna (lista de (nome, ok, motivo_se_falhou), sample_quality)."""

    market = row.get("market")
    matched = _bool_or_false(row.get("matched"))
    restricted = _bool_or_false(row.get("restricted"))
    operational_probability = row.get("operational_probability")
    decimal_odds = row.get("decimal_odds")
    resolution_player = row.get("resolution_method_player")
    resolution_opponent = row.get("resolution_method_opponent")
    historical_cutoff = row.get("historical_data_cutoff")
    staleness_days = row.get("data_staleness_days")

    sample_q = sq.classify_sample_quality(
        row.get("prior_matches_career"),
        row.get("prior_service_points_career"),
        row.get("prior_return_points_career"),
        row.get("surface_prior_matches"),
        feature_consistent=not (
            _bool_or_false(row.get("cold_start"))
            or _bool_or_false(row.get("insufficient_history"))
            or _bool_or_false(row.get("calibrator_insufficient_sample"))
        ),
    )

    gates = [
        (
            "mercado_aprovado",
            market in cfg.ALLOWED_MARKETS,
            f"mercado '{market}' nao esta entre os aprovados nas fases anteriores ({cfg.ALLOWED_MARKETS})",
        ),
        (
            "linha_existe_na_distribuicao",
            matched,
            f"linha nao casada com o radar atual: {row.get('match_reason') or 'motivo nao registrado'}",
        ),
        (
            "previsao_nao_restrita",
            not restricted,
            f"previsao restrita: {row.get('restricted_motivo') or 'restricao herdada da Fase 7 (docs/012 secao 5)'}",
        ),
        (
            "identidade_confiavel",
            matched and resolution_player in cfg._RELIABLE_RESOLUTION_METHODS and resolution_opponent in cfg._RELIABLE_RESOLUTION_METHODS,
            "jogador e/ou adversario nao resolvidos com identidade confiavel (exact/alias)",
        ),
        (
            "probabilidade_operacional_valida",
            matched and not _is_missing(operational_probability) and 0.0 < float(operational_probability) < 1.0,
            "probabilidade operacional ausente ou fora do intervalo (0, 1)",
        ),
        (
            "odd_acima_do_limite_configurado",
            not _is_missing(decimal_odds) and float(decimal_odds) >= cfg.MIN_LIQUID_ODDS,
            f"odd observada ({decimal_odds}) abaixo do limite minimo configurado ({cfg.MIN_LIQUID_ODDS})",
        ),
        (
            "amostra_historica_minima",
            sample_q != cfg.SAMPLE_QUALITY_LOW,
            f"qualidade de amostra = {sample_q} (abaixo do minimo exigido para avancar)",
        ),
        (
            "staleness_registrada",
            historical_cutoff is not None and not _is_missing(staleness_days),
            "defasagem estatistica (historical_data_cutoff/data_staleness_days) nao registrada",
        ),
    ]
    return gates, sample_q


def evaluate_opportunity(row: dict, market_edge_floor: dict | None = None) -> dict:
    """`row`: uma linha ja enriquecida (`inputs.enrich_comparisons`).
    `market_edge_floor` (opcional): sobrepoe `config.MARKET_MIN_EDGE_LABEL`
    -- usado so pelo teste de sensibilidade do item 9, nunca como politica
    default."""

    floor_map = market_edge_floor or cfg.MARKET_MIN_EDGE_LABEL

    gates, sample_q = _compute_gates(row)
    failed = [(name, motivo) for name, ok, motivo in gates if not ok]

    market = row.get("market")
    status = row.get("status")
    staleness_bucket = stale.classify_staleness(row.get("data_staleness_days"))
    extreme_prob = _bool_or_false(row.get("extreme_probability"))

    flags = {
        "matched": _bool_or_false(row.get("matched")),
        "restricted": _bool_or_false(row.get("restricted")),
        "extreme_probability": extreme_prob,
        "cold_start": _bool_or_false(row.get("cold_start")),
        "insufficient_history": _bool_or_false(row.get("insufficient_history")),
        "calibrator_insufficient_sample": _bool_or_false(row.get("calibrator_insufficient_sample")),
        "candidato_forte_capped_by_staleness": False,
    }
    metrics = {
        "model_edge": row.get("model_edge"),
        "implied_probability": row.get("implied_probability"),
        "operational_probability": row.get("operational_probability"),
        "decimal_odds": row.get("decimal_odds"),
        "fair_odds": row.get("fair_odds"),
        "edge_status": status,
        "sample_quality": sample_q,
        "staleness_bucket": staleness_bucket,
        "data_staleness_days": row.get("data_staleness_days"),
        "market_edge_floor": floor_map.get(market),
        "market": market,
        "tour": row.get("tour"),
        "surface": row.get("surface_ctx"),
    }

    if failed:
        classification = cfg.STATE_DESCARTAR
        reasons = [motivo for _name, motivo in failed]
        alerts = []
        if not _is_missing(row.get("data_staleness_days")) and staleness_bucket != cfg.STALENESS_ATUAL:
            alerts.append(row.get("staleness_warning") or f"defasagem de {row.get('data_staleness_days')} dias")
        return {
            "classification": classification,
            "reasons": reasons,
            "flags": flags,
            "metrics": metrics,
            "alerts": alerts,
            "stake_policy": cfg.STAKE_POLICY_NOT_IMPLEMENTED,
        }

    # --- todos os gates passaram: escada de classificacao ---------------
    floor_label = floor_map.get(market, cfg.MARKET_MIN_EDGE_LABEL.get(market, "ATINGE_EDGE_5"))
    floor_rank = cfg.EDGE_RANK.get(floor_label, cfg.EDGE_RANK["ATINGE_EDGE_5"])
    edge_rank = cfg.EDGE_RANK.get(status, 0)

    if edge_rank < floor_rank:
        classification = cfg.STATE_OBSERVAR
    elif edge_rank == floor_rank:
        classification = cfg.STATE_CANDIDATO_FRACO
    elif edge_rank < cfg.STRONG_EDGE_MIN_RANK:
        classification = cfg.STATE_CANDIDATO if sample_q == cfg.SAMPLE_QUALITY_HIGH else cfg.STATE_CANDIDATO_FRACO
    else:
        classification = cfg.STATE_CANDIDATO_FORTE if sample_q == cfg.SAMPLE_QUALITY_HIGH else cfg.STATE_CANDIDATO

    alerts = []
    if classification == cfg.STATE_CANDIDATO_FORTE and stale.blocks_candidato_forte(staleness_bucket):
        classification = cfg.STATE_CANDIDATO
        flags["candidato_forte_capped_by_staleness"] = True
        alerts.append(
            f"CANDIDATO_FORTE bloqueado por staleness (defasagem de {row.get('data_staleness_days')} dias "
            f"> {cfg.MAX_STALENESS_DAYS_FOR_CANDIDATO_FORTE}) -- classificado como CANDIDATO"
        )

    if staleness_bucket != cfg.STALENESS_ATUAL:
        alerts.append(row.get("staleness_warning") or f"defasagem de {row.get('data_staleness_days')} dias")
    if extreme_prob:
        alerts.append(
            "probabilidade extrema (>=90%) -- nao tratada como qualidade superior automaticamente (item 8)"
        )

    model_edge = row.get("model_edge")
    edge_txt = f"edge = {model_edge * 100:+.1f} p.p." if not _is_missing(model_edge) else "edge = N/A"
    reasons = [
        edge_txt,
        f"amostra = {sample_q}",
        "calibração aprovada" if row.get("method_selected") not in (None, "unavailable") else "calibração indisponível",
    ]
    surface = row.get("surface_ctx")
    if surface:
        reasons.append(f"{str(surface).lower()} court")

    return {
        "classification": classification,
        "reasons": reasons,
        "flags": flags,
        "metrics": metrics,
        "alerts": alerts,
        "stake_policy": cfg.STAKE_POLICY_NOT_IMPLEMENTED,
    }


def format_explanation(result: dict) -> str:
    """item 11: nunca devolve so um status -- sempre 'Motivos:' (e
    'Alertas:' quando houver)."""

    lines = [result["classification"], "", "Motivos:"]
    lines += [f"- {r}" for r in result["reasons"]]
    if result["alerts"]:
        lines += ["", "Alertas:"]
        lines += [f"- {a}" for a in result["alerts"]]
    return "\n".join(lines)
