"""Contratos do LOTE D (docs/018_PWA_ARQUITETURA.md secao 8, ajustado pelas
instrucoes concretas deste lote). Uma linha por (partida, mercado, jogador
quando aplicavel, linha, lado) -- espelha exatamente uma linha ja
produzida por `data/outputs/phase8/precos_por_linha.parquet`
(`src.radar.build.run`, Fase 8), sem nenhum campo recalculado aqui.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class RadarLine(BaseModel):
    # Identificacao/juncao com o calendario (LOTE C) -- match_key e sempre
    # derivavel dos proprios dados do radar (independe do calendario
    # existir); event_datetime_sao_paulo so vem preenchido quando o
    # match_key bate com uma entrada real do calendario (ver limitacoes no
    # docs/018 LOTE D).
    match_key: str
    match_id: str
    tour: Literal["ATP", "WTA"]
    tournament: str
    round: str
    surface: Literal["Hard", "Clay", "Grass"]
    player_a: str
    player_b: str
    event_datetime_sao_paulo: datetime | None = None

    # A linha de preco em si (Fase 7/8, src/pricing + src/radar/pricing_future.py).
    market: Literal["aces_player", "total_aces_match", "double_faults_player"]
    player: str | None = None  # None em total_aces_match (mercado de partida, nao de jogador)
    side: Literal["over", "under"]
    line: float
    probability: float  # operational_probability (Fase 6.1: calibrada quando aprovada, raw quando nao)
    fair_odds: float | None = None  # None quando cold_start (pipeline nunca precifica cold start)
    minimum_odds: float | None = None  # odd_minima_por_edge["3pct"] -- ver campo abaixo para os outros cenarios
    odd_minima_por_edge: dict[str, float | None]

    # Classificacao (Fase 8, src/radar/candidates.py) -- decision_state e
    # so um agrupamento de apresentacao dos MESMOS sinais ja calculados
    # (is_candidate/candidate_blockers), feito nesta camada de adapter, sem
    # nenhuma nova regra estatistica (ver docs/018 LOTE D).
    decision_state: Literal["CONFERIR_ODDS", "OBSERVAR", "DESCARTADO"]
    candidate_blockers: list[str]
    sample_bucket_career: str
    restricted: bool
    restricted_motivo: str | None = None
    extreme_probability: bool
    identity_trusted: bool
    resolution_method_player: str | None = None
    resolution_method_opponent: str | None = None

    # Defasagem da base historica (Fase 9, src.odds.pricing_compare +
    # src.decision.staleness_policy) -- nunca escondida (docs/018 secao
    # "STALE DATA").
    staleness_status: str | None = None
    staleness_days: int | None = None
    historical_data_cutoff: date | None = None

    # LOTE J — Overlay Tennis Abstract
    effective_data_cutoff: date | None = None
    overlay_status: str | None = None

