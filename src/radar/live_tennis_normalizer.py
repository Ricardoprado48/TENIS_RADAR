"""Normalização Live Tennis -> contrato bruto da Fase 8.

Decisão de engenharia importante:
- /matches?status=upcoming é a fonte operacional de quais partidas são futuras;
- /fixtures fornece `event_date`, porque Match expõe `scheduled_time` em UTC
  mas não expõe a data local do torneio;
- nunca derivamos `match_date` simplesmente da data UTC do scheduled_time,
  pois src/calendar/match_key.py exige a data local do torneio.

Se uma partida upcoming não puder ser ligada de forma inequívoca a um fixture
com event_date, a normalização falha. É preferível parar a inventar uma data
que alteraria match_key e poderia ligar odds/calendário à partida errada.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

import pandas as pd

from .live_tennis import BASE_URL, SUPPORTED_TOURS


class LiveTennisNormalizationError(ValueError):
    """Payload Live Tennis insuficiente/ambíguo para o contrato da Fase 8."""


def _fixture_index(fixtures: Iterable[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    index: dict[int, dict[str, Any]] = {}
    for fixture in fixtures:
        match_id = fixture.get("match_id")
        if match_id is None:
            continue
        try:
            key = int(match_id)
        except (TypeError, ValueError) as exc:
            raise LiveTennisNormalizationError(
                f"fixture com match_id inválido: {match_id!r}"
            ) from exc
        if key in index:
            raise LiveTennisNormalizationError(
                f"mais de um fixture para o mesmo match_id={key}"
            )
        index[key] = fixture
    return index


def _require_text(value: Any, *, field: str, match_id: int) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        raise LiveTennisNormalizationError(
            f"match_id={match_id}: campo obrigatório ausente/vazio: {field}"
        )
    return text


def _player_name(match: dict[str, Any], side: str, match_id: int) -> str:
    players = match.get("players")
    if not isinstance(players, dict):
        raise LiveTennisNormalizationError(
            f"match_id={match_id}: objeto players ausente/inválido"
        )
    player = players.get(side)
    if not isinstance(player, dict):
        raise LiveTennisNormalizationError(
            f"match_id={match_id}: players.{side} ausente/inválido"
        )
    return _require_text(player.get("name"), field=f"players.{side}.name", match_id=match_id)


def normalize_upcoming_to_phase8(
    tour: str,
    matches: Iterable[dict[str, Any]],
    fixtures: Iterable[dict[str, Any]],
    *,
    collected_at: datetime | None = None,
) -> pd.DataFrame:
    """Converte partidas upcoming para o schema bruto aceito por src/radar/sources.py."""

    tour_key = tour.upper().strip()
    if tour_key not in SUPPORTED_TOURS:
        raise ValueError(f"tour inválido: {tour!r}; esperado ATP ou WTA")

    collected = collected_at or datetime.now(timezone.utc)
    if collected.tzinfo is None or collected.utcoffset() is None:
        raise ValueError("collected_at deve possuir timezone")
    collected_utc = collected.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    fixture_by_match = _fixture_index(fixtures)
    api_tour = SUPPORTED_TOURS[tour_key]
    source_url = (
        f"{BASE_URL}/matches?status=upcoming&tour={api_tour}&draw=singles"
    )

    rows: list[dict[str, Any]] = []
    for match in matches:
        raw_match_id = match.get("id")
        try:
            match_id = int(raw_match_id)
        except (TypeError, ValueError) as exc:
            raise LiveTennisNormalizationError(
                f"match com id inválido: {raw_match_id!r}"
            ) from exc

        if match.get("status") != "upcoming":
            raise LiveTennisNormalizationError(
                f"match_id={match_id}: status não é upcoming"
            )

        match_tour = _require_text(match.get("tour"), field="tour", match_id=match_id).lower()
        if match_tour != api_tour:
            raise LiveTennisNormalizationError(
                f"match_id={match_id}: tour={match_tour!r} diverge de {api_tour!r}"
            )

        fixture = fixture_by_match.get(match_id)
        if fixture is None:
            raise LiveTennisNormalizationError(
                f"match_id={match_id}: fixture correspondente não encontrado"
            )

        event_date = _require_text(
            fixture.get("event_date"),
            field="fixture.event_date",
            match_id=match_id,
        )
        try:
            parsed_date = datetime.strptime(event_date, "%Y-%m-%d").date()
        except ValueError as exc:
            raise LiveTennisNormalizationError(
                f"match_id={match_id}: fixture.event_date inválido: {event_date!r}"
            ) from exc

        scheduled_time = _require_text(
            match.get("scheduled_time"),
            field="scheduled_time",
            match_id=match_id,
        )
        try:
            scheduled_dt = datetime.fromisoformat(scheduled_time.replace("Z", "+00:00"))
        except ValueError as exc:
            raise LiveTennisNormalizationError(
                f"match_id={match_id}: scheduled_time inválido: {scheduled_time!r}"
            ) from exc
        if scheduled_dt.tzinfo is None or scheduled_dt.utcoffset() is None:
            raise LiveTennisNormalizationError(
                f"match_id={match_id}: scheduled_time sem timezone"
            )

        round_code = match.get("round_code") or fixture.get("round_code") or "UNKNOWN"
        round_value = str(round_code).strip() or "UNKNOWN"

        tournament = _require_text(match.get("tournament"), field="tournament", match_id=match_id)
        surface = _require_text(match.get("surface"), field="surface", match_id=match_id)

        rows.append(
            {
                "source_url": source_url,
                "collected_at": collected_utc,
                "tour": tour_key,
                "tournament": tournament,
                "surface": surface,
                "match_date": parsed_date.isoformat(),
                "round": round_value,
                "player_a_raw": _player_name(match, "p1", match_id),
                "player_b_raw": _player_name(match, "p2", match_id),
                "live_tennis_match_id": match_id,
                "live_tennis_fixture_id": fixture.get("id"),
                "scheduled_time_utc": scheduled_dt.astimezone(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "tournament_id": match.get("tournament_id"),
            }
        )

    columns = [
        "source_url",
        "collected_at",
        "tour",
        "tournament",
        "surface",
        "match_date",
        "round",
        "player_a_raw",
        "player_b_raw",
        "live_tennis_match_id",
        "live_tennis_fixture_id",
        "scheduled_time_utc",
        "tournament_id",
    ]
    out = pd.DataFrame(rows, columns=columns)
    if not out.empty:
        out = out.sort_values(
            ["match_date", "scheduled_time_utc", "tour", "tournament", "live_tennis_match_id"],
            kind="stable",
        ).reset_index(drop=True)
    return out
