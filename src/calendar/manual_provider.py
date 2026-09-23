"""ManualFileCalendarProvider (docs/018_PWA_ARQUITETURA.md secao 5.2).

Le `data/raw/calendar/agenda_*.csv` (preenchido manualmente, mesma
disciplina ja usada em `data/raw/phase8/partidas_futuras_*.csv` --
CLAUDE.md Sec.12: fonte estruturada local antes de qualquer scraping).
Ao contrario de `src/radar/sources.py` (que so le o ultimo arquivo), o
calendario cobre uma janela de varios dias -- todos os arquivos
`agenda_*.csv` existentes sao lidos e combinados, e o filtro de
date_from/date_to acontece depois, sobre a data ja convertida para
`America/Sao_Paulo` (secao 4.2: e o fuso que a PWA mostra ao usuario).

Nunca sobrescreve/apaga arquivo bruto (CLAUDE.md Sec.11) -- so leitura.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from . import config as cfg
from .match_key import build_match_key
from .providers import MatchSchedule, Tournament


def _raw_files(raw_dir: Path) -> list[Path]:
    return sorted(raw_dir.glob("agenda_*.csv"))


def _derive_status(event_datetime_utc: datetime, now: datetime) -> str:
    """docs/018 secao 5.4 -- limiares documentados em src/calendar/config.py."""
    if now < event_datetime_utc - cfg.STATUS_PROXIMO_WINDOW:
        return "futuro"
    if now < event_datetime_utc:
        return "proximo"
    if now < event_datetime_utc + cfg.STATUS_DURACAO_MAXIMA:
        return "iniciado"
    return "encerrado"


class ManualFileCalendarProvider:
    """Implementacao inicial do CalendarProvider (docs/018 secao 5.2)."""

    def __init__(self, raw_dir: str | Path | None = None):
        self.raw_dir = Path(raw_dir) if raw_dir is not None else cfg.CALENDAR_RAW_DIR

    def _load_all_matches(self, now: datetime | None = None) -> list[MatchSchedule]:
        now = now if now is not None else datetime.now(timezone.utc)
        matches: list[MatchSchedule] = []
        for path in _raw_files(self.raw_dir):
            matches.extend(self._load_file(path, now))
        return matches

    def _load_file(self, path: Path, now: datetime) -> list[MatchSchedule]:
        df = pd.read_csv(path, dtype=str)

        missing = [c for c in cfg.REQUIRED_RAW_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"{path}: colunas obrigatorias ausentes: {missing}")

        df["tour"] = df["tour"].str.upper().str.strip()
        bad_tour = ~df["tour"].isin(cfg.TOURS)
        if bad_tour.any():
            raise ValueError(
                f"{path}: tour invalido em {int(bad_tour.sum())} linha(s): "
                f"{sorted(df.loc[bad_tour, 'tour'].unique())}"
            )

        df["surface"] = df["surface"].str.strip().str.title()
        bad_surface = ~df["surface"].isin(cfg.SURFACES)
        if bad_surface.any():
            raise ValueError(
                f"{path}: surface invalida em {int(bad_surface.sum())} linha(s): "
                f"{sorted(df.loc[bad_surface, 'surface'].unique())}"
            )

        for col in ["tournament", "round", "player_a_raw", "player_b_raw", "event_timezone"]:
            blank = df[col].isna() | (df[col].astype(str).str.strip() == "")
            if blank.any():
                raise ValueError(f"{path}: coluna '{col}' vazia em {int(blank.sum())} linha(s)")
            df[col] = df[col].str.strip()

        df["event_datetime_original"] = pd.to_datetime(
            df["event_datetime_original"], errors="raise"
        )
        df["collected_at"] = pd.to_datetime(df["collected_at"], errors="raise", utc=True)

        rows: list[MatchSchedule] = []
        for record in df.itertuples(index=False):
            tz_name = record.event_timezone
            try:
                tz = ZoneInfo(tz_name)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ValueError(
                    f"{path}: fuso horario invalido ('{tz_name}'): {exc}"
                ) from exc

            event_original = record.event_datetime_original.to_pydatetime().replace(tzinfo=tz)
            event_utc = event_original.astimezone(timezone.utc)
            event_sao_paulo = event_original.astimezone(ZoneInfo(cfg.DISPLAY_TIMEZONE))

            match_key = build_match_key(
                tour=record.tour,
                tournament=record.tournament,
                round_=record.round,
                player_a=record.player_a_raw,
                player_b=record.player_b_raw,
                match_date=event_original.date(),
            )

            source_url_raw = getattr(record, "source_url", None)
            if source_url_raw is None or (isinstance(source_url_raw, float) and pd.isna(source_url_raw)):
                source_url = None
            else:
                source_url = str(source_url_raw).strip() or None

            rows.append(
                MatchSchedule(
                    match_key=match_key,
                    tour=record.tour,
                    tournament=record.tournament,
                    round=record.round,
                    surface=record.surface,
                    player_a=record.player_a_raw,
                    player_b=record.player_b_raw,
                    event_datetime_original=event_original,
                    event_timezone=tz_name,
                    event_datetime_utc=event_utc,
                    event_datetime_sao_paulo=event_sao_paulo,
                    status=_derive_status(event_utc, now),
                    collected_at=record.collected_at.to_pydatetime(),
                    source_url=source_url,
                )
            )
        return rows

    def list_tournaments(self, date_from: date, date_to: date) -> list[Tournament]:
        seen: dict[tuple[str, str], Tournament] = {}
        for m in self.list_matches(date_from, date_to):
            key = (m.tour, m.tournament)
            if key not in seen:
                seen[key] = Tournament(tour=m.tour, tournament=m.tournament, surface=m.surface)
        return list(seen.values())

    def list_matches(
        self,
        date_from: date,
        date_to: date,
        tour: str | None = None,
        tournament: str | None = None,
        now: datetime | None = None,
    ) -> list[MatchSchedule]:
        result = [
            m for m in self._load_all_matches(now)
            if date_from <= m.event_datetime_sao_paulo.date() <= date_to
        ]
        if tour is not None:
            result = [m for m in result if m.tour == tour]
        if tournament is not None:
            result = [m for m in result if m.tournament == tournament]
        result.sort(key=lambda m: m.event_datetime_utc)
        return result

    def get_match(self, match_key: str, now: datetime | None = None) -> MatchSchedule | None:
        for m in self._load_all_matches(now):
            if m.match_key == match_key:
                return m
        return None
