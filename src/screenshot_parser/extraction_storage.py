"""Persistencia dos dois artefatos separados do LOTE F (secao
"PERSISTENCIA" do pedido): a extracao bruta da IA (auditoria, nunca
reescrita) e a extracao confirmada pelo usuario. JSON simples, um arquivo
por registro -- mesmo raciocinio de volume local ja aceito para
`data/raw/bookmaker_screenshots/` (LOTE E)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from . import config as cfg
from .models import ConfirmedExtraction, ExtractionResult, NormalizedMarket


def _market_from_json_dict(data: dict) -> NormalizedMarket:
    return NormalizedMarket(
        market=data["market"],
        player=data.get("player"),
        bookmaker_display=data["bookmaker_display"],
        side=data.get("side"),
        model_line=data.get("model_line"),
        decimal_odds=data["decimal_odds"],
        confidence=data.get("confidence"),
        warnings=tuple(data.get("warnings") or ()),
        needs_confirmation=bool(data.get("needs_confirmation", False)),
    )


def _extraction_from_json_dict(data: dict) -> ExtractionResult:
    return ExtractionResult(
        extraction_id=data["extraction_id"],
        upload_id=data["upload_id"],
        match_key=data["match_key"],
        tab_type=data["tab_type"],
        status=data["status"],
        provider=data["provider"],
        provider_model=data.get("provider_model"),
        created_at=datetime.fromisoformat(data["created_at"]),
        markets=tuple(_market_from_json_dict(m) for m in data.get("markets", [])),
        extraction_warnings=tuple(data.get("extraction_warnings") or ()),
        raw_provider_response=data.get("raw_provider_response"),
    )


def save_raw_extraction(result: ExtractionResult) -> Path:
    cfg.EXTRACTED_RAW_DIR.mkdir(parents=True, exist_ok=True)
    path: Path = cfg.EXTRACTED_RAW_DIR / f"{result.extraction_id}.json"
    if path.exists():
        raise RuntimeError(f"Colisao inesperada de extraction_id: {result.extraction_id}")
    path.write_text(json.dumps(result.to_json_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def list_raw_extractions(upload_id: str) -> list[ExtractionResult]:
    if not cfg.EXTRACTED_RAW_DIR.exists():
        return []
    results = []
    for path in cfg.EXTRACTED_RAW_DIR.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("upload_id") == upload_id:
            results.append(_extraction_from_json_dict(data))
    return sorted(results, key=lambda r: r.created_at)


def latest_raw_extraction(upload_id: str) -> ExtractionResult | None:
    results = list_raw_extractions(upload_id)
    return results[-1] if results else None


def save_confirmed(confirmed: ConfirmedExtraction) -> Path:
    cfg.CONFIRMED_DIR.mkdir(parents=True, exist_ok=True)
    path: Path = cfg.CONFIRMED_DIR / f"{confirmed.extraction_id}.json"
    if path.exists():
        raise RuntimeError(f"Colisao inesperada de extraction_id: {confirmed.extraction_id}")
    path.write_text(json.dumps(confirmed.to_json_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def list_confirmed(upload_id: str) -> list[ConfirmedExtraction]:
    if not cfg.CONFIRMED_DIR.exists():
        return []
    results = []
    for path in cfg.CONFIRMED_DIR.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("upload_id") == upload_id:
            results.append(
                ConfirmedExtraction(
                    extraction_id=data["extraction_id"],
                    upload_id=data["upload_id"],
                    match_key=data["match_key"],
                    tab_type=data["tab_type"],
                    confirmed_at=datetime.fromisoformat(data["confirmed_at"]),
                    confirmed_by=data["confirmed_by"],
                    corrected=bool(data["corrected"]),
                    markets=tuple(_market_from_json_dict(m) for m in data.get("markets", [])),
                )
            )
    return sorted(results, key=lambda r: r.confirmed_at)
