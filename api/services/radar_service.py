"""Servico do radar do dia (GET /api/radar/today, LOTE D).

So LEITURA dos outputs ja produzidos por `src.radar.build.run()` (Fase 8,
`data/outputs/phase8/*.parquet`) -- nenhum modelo, feature, calibracao,
threshold ou logica de odds e recalculado aqui. O unico trabalho novo desta
camada e adaptar os DataFrames existentes para o schema JSON da PWA
(api/schemas/radar.py) e cruzar com o calendario (LOTE C) pelo match_key
compartilhado (`src.calendar.match_key.build_match_key`, reaproveitado sem
duplicar).

`decision_state` (CONFERIR_ODDS/OBSERVAR/DESCARTADO) e um agrupamento de
apresentacao dos mesmos sinais que `src.radar.candidates.flag_candidates`
ja calculou (`is_candidate`/`candidate_blockers`) -- nao e uma nova regra
estatistica, so uma forma de mostrar 3 grupos em vez de um booleano + uma
lista de motivos:

  - CONFERIR_ODDS: is_candidate == True (atende todos os 5 criterios).
  - OBSERVAR:      is_candidate == False e o UNICO criterio que falhou foi
                    "probabilidade_nao_trivial" -- estatisticamente bem
                    suportada (amostra ok, mercado liberado, calibracao
                    disponivel, identidade confiavel), so a probabilidade e
                    extrema demais para valer a pena conferir odds agora.
  - DESCARTADO:     qualquer outro caso -- pelo menos um problema
                    estrutural (amostra insuficiente, mercado restrito,
                    calibracao indisponivel ou identidade nao confiavel).

Ver docs/018_PWA_ARQUITETURA.md, secao "LOTE D — CONCLUIDO", para a
justificativa completa e para as limitacoes conhecidas (join por match_key
entre calendario e radar depende dos dois arquivos brutos listarem os
jogadores com o mesmo texto/ordem).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd

from src.calendar.manual_provider import ManualFileCalendarProvider
from src.calendar.match_key import build_match_key
from src.decision import staleness_policy
from src.odds import pricing_compare
from src.incremental import config as inc_cfg
from src.incremental import overlay as ta_overlay
from src.pricing import config as pricing_cfg
from src.radar import config as radar_cfg

from api.schemas.radar import RadarLine

_RELIABLE_RESOLUTION_METHODS = {"exact", "alias"}
DEFAULT_EDGE_LABEL = "3pct"
_EDGE_LABELS = [label for label, _ in pricing_cfg.EDGE_LEVELS]


def _nan_to_none(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _blockers_list(raw) -> list[str]:
    raw = _nan_to_none(raw)
    if not raw:
        return []
    return [b for b in str(raw).split(",") if b]


def _decision_state(is_candidate: bool, blockers: list[str]) -> str:
    if is_candidate:
        return "CONFERIR_ODDS"
    if blockers == ["probabilidade_nao_trivial"]:
        return "OBSERVAR"
    return "DESCARTADO"


def _load_parquet(path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def _load_resolved_matches() -> pd.DataFrame:
    """`match_id -> (tour, tournament, round, player_a_raw, player_b_raw,
    match_date)`, mesmo filtro (`usable_for_prediction & ~is_duplicate`) e
    mesma formula de match_id (`FUTURE:{tour}:{raw_match_seq}`) que
    `src.radar.build._match_context` ja usa -- nunca alterado, so lido de
    novo aqui porque `precos_por_linha.parquet` nao carrega esses campos
    brutos por jogo (so `player_name`/`opponent_name`, que trocam de lado
    conforme a linha)."""
    df = _load_parquet(radar_cfg.PHASE8_DIR / "partidas_resolvidas.parquet")
    if df.empty:
        return df
    df = df[df["usable_for_prediction"] & ~df["is_duplicate"]].copy()
    df["match_id"] = "FUTURE:" + df["tour"].astype(str) + ":" + df["raw_match_seq"].astype(str)
    return df


def _match_context_map(resolved: pd.DataFrame) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in resolved.itertuples(index=False):
        match_date = r.match_date
        match_date = match_date.date() if hasattr(match_date, "date") else match_date
        key = build_match_key(
            tour=r.tour, tournament=r.tournament, round_=r.round,
            player_a=r.player_a_raw, player_b=r.player_b_raw, match_date=match_date,
        )
        out[r.match_id] = {
            "match_key": key,
            "player_a": r.player_a_raw,
            "player_b": r.player_b_raw,
            "player_id_a": r.player_id_a,
            "player_id_b": r.player_id_b,
        }
    return out


def _now_utc() -> datetime:
    """Relogio isolado para permitir teste deterministico."""
    return datetime.now(timezone.utc)


def _active_calendar_datetimes_by_key() -> dict[str, datetime]:
    """Partidas operacionais ainda validas no calendario.

    O calendario e a fonte de verdade operacional do Radar:
    - futuro, proximo e iniciado permanecem elegiveis;
    - encerrado nao aparece;
    - partida ausente da agenda tambem nao aparece.

    Nenhum dado historico do Phase 8 e apagado.
    """
    provider = ManualFileCalendarProvider()
    matches = provider.list_matches(
        date.min,
        date.max,
        now=_now_utc(),
    )
    return {
        m.match_key: m.event_datetime_sao_paulo
        for m in matches
        if m.status != "encerrado"
    }


def _staleness_by_tour() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for tour in radar_cfg.TOURS:
        try:
            info = pricing_compare.staleness_warning(tour)
            status = staleness_policy.classify_staleness(info["data_staleness_days"])
            out[tour] = {
                "staleness_status": status,
                "staleness_days": info["data_staleness_days"],
                "historical_data_cutoff": info["historical_data_cutoff"],
            }
        except Exception:
            # Base historica processada indisponivel no ambiente -- nunca
            # inventa um valor, so nao anexa staleness a essas linhas
            # (mesma regra do api/services/info_service.py, LOTE A).
            out[tour] = {"staleness_status": None, "staleness_days": None, "historical_data_cutoff": None}
    return out


def _dedupe_match_level_markets(prices: pd.DataFrame) -> pd.DataFrame:
    """`total_aces_match` e um mercado de PARTIDA (nao de jogador), mas o
    pipeline grava uma linha por jogador-ancora com valores identicos (a
    formula nao depende de qual jogador foi usado como ancora -- conferido
    sobre os dados reais desta entrega). Mantemos so a primeira ocorrencia
    por (match_id, market, line, side) para nao duplicar o mesmo card na
    UI, e expomos player=None (e realmente um mercado de partida)."""
    if prices.empty:
        return prices
    prices = prices.sort_values(["match_id", "market", "line", "side", "player_id"])
    is_match_level = prices["market"] == "total_aces_match"
    dedup_subset = ["match_id", "market", "line", "side"]
    return pd.concat([
        prices[~is_match_level],
        prices[is_match_level].drop_duplicates(subset=dedup_subset, keep="first"),
    ]).sort_index()


def _min_odds_by_key(min_odds: pd.DataFrame) -> dict[tuple, dict[str, float | None]]:
    out: dict[tuple, dict[str, float | None]] = {}
    if min_odds.empty:
        return out
    for row in min_odds.itertuples(index=False):
        key = (row.match_id, row.market, row.player_id, row.line, row.side)
        out.setdefault(key, {})[row.edge_label] = _nan_to_none(row.odd_minima)
    return out


def get_radar_lines() -> list[RadarLine]:
    prices = _load_parquet(radar_cfg.PHASE8_DIR / "precos_por_linha.parquet")
    if prices.empty:
        return []
    prices = _dedupe_match_level_markets(prices)

    match_context = _match_context_map(_load_resolved_matches())
    calendar_datetimes = _active_calendar_datetimes_by_key()
    staleness = _staleness_by_tour()
    min_odds_map = _min_odds_by_key(_load_parquet(radar_cfg.PHASE8_DIR / "odds_minimas_por_edge.parquet"))

    lines: list[RadarLine] = []
    for row in prices.itertuples(index=False):
        ctx = match_context.get(row.match_id)
        if ctx is None:
            # Nunca deveria acontecer (precos so existem para partidas
            # usaveis/nao-duplicadas), mas nunca inventa contexto se faltar.
            continue

        # O calendario e a fonte de verdade operacional.
        # Ausente ou encerrado => nao pertence ao radar atual.
        event_datetime = calendar_datetimes.get(ctx["match_key"])
        if event_datetime is None:
            continue

        blockers = _blockers_list(row.candidate_blockers)
        is_market_level = row.market == "total_aces_match"
        # player_name/opponent_name (precos_por_linha.parquet) carregam o
        # nome resolvido tal como esta em players.parquet, que tem
        # capitalizacao inconsistente para alguns jogadores (ex.:
        # "sebastian baez" em minusculas) -- em vez de mostrar isso na UI,
        # usamos o mesmo texto bruto (player_a_raw/player_b_raw, corretamente
        # capitalizado na fonte) ja usado em player_a/player_b, escolhido
        # pelo player_id (identidade ja resolvida, nao recalculada aqui).
        player_display = None
        if not is_market_level:
            if row.player_id == ctx["player_id_a"]:
                player_display = ctx["player_a"]
            elif row.player_id == ctx["player_id_b"]:
                player_display = ctx["player_b"]
            else:
                player_display = _nan_to_none(row.player_name)

        edge_odds = min_odds_map.get((row.match_id, row.market, row.player_id, row.line, row.side), {})
        odd_minima_por_edge = {label: edge_odds.get(label) for label in _EDGE_LABELS}

        tour_staleness = staleness.get(row.tour, {})
        base_cutoff = tour_staleness.get("historical_data_cutoff")

        # Overlay Tennis Abstract (LOTE J)
        if inc_cfg.TA_OVERLAY_ENABLED and player_display:
            p_freshness = ta_overlay.get_player_freshness(player_display, row.tour)
            eff_cutoff_str = p_freshness.get("effective_data_cutoff")
            effective_data_cutoff = pd.to_datetime(eff_cutoff_str).date() if eff_cutoff_str else base_cutoff
            overlay_status = p_freshness.get("freshness_status")
        else:
            effective_data_cutoff = base_cutoff
            overlay_status = "BASE_ONLY" if not inc_cfg.TA_OVERLAY_ENABLED else "BASE_ONLY"

        lines.append(RadarLine(
            match_key=ctx["match_key"],
            match_id=row.match_id,
            tour=row.tour,
            tournament=row.tournament,
            round=row.round,
            surface=row.surface,
            player_a=ctx["player_a"],
            player_b=ctx["player_b"],
            event_datetime_sao_paulo=event_datetime,
            market=row.market,
            player=player_display,
            side=row.side,
            line=float(row.line),
            probability=float(row.operational_probability),
            fair_odds=_nan_to_none(row.fair_odds),
            minimum_odds=odd_minima_por_edge.get(DEFAULT_EDGE_LABEL),
            odd_minima_por_edge=odd_minima_por_edge,
            decision_state=_decision_state(bool(row.is_candidate), blockers),
            candidate_blockers=blockers,
            sample_bucket_career=row.sample_bucket_career,
            restricted=bool(row.restricted),
            restricted_motivo=_nan_to_none(row.restricted_motivo),
            extreme_probability=bool(row.extreme_probability),
            identity_trusted="identidade_confiavel" not in blockers,
            resolution_method_player=_nan_to_none(row.resolution_method_player),
            resolution_method_opponent=_nan_to_none(row.resolution_method_opponent),
            staleness_status=tour_staleness.get("staleness_status"),
            staleness_days=tour_staleness.get("staleness_days"),
            historical_data_cutoff=base_cutoff,
            effective_data_cutoff=effective_data_cutoff,
            overlay_status=overlay_status,
        ))
    return lines
