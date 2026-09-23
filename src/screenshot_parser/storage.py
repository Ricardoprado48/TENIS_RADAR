"""Armazenamento auditavel do print original (LOTE E) + busca por
upload_id (LOTE F, necessaria para o parser localizar a imagem/metadados a
partir do id recebido pelos novos endpoints de extracao/confirmacao).

Grava a imagem original em disco (nunca sobrescreve um upload anterior,
nunca executa/interpreta o conteudo -- so le os pixels para confirmar que
e uma imagem de verdade) e um JSON sidecar com os metadados minimos
pedidos. Leitura/normalizacao do que esta desenhado na imagem fica em
`mapping.py`/`validator.py`/`providers.py`/`extractor.py` (LOTE F).

Testavel sem subir a API (mesmo padrao de src/calendar e src/odds) --
`api/services/screenshot_service.py` so chama estas funcoes e adapta o
resultado para o schema HTTP.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from . import config as cfg

_ALLOWED_TAB_TYPES = {t.value for t in cfg.TabType}


class InvalidScreenshotError(ValueError):
    """Upload nao passou em uma das validacoes desta camada (campo
    obrigatorio, tamanho, formato de imagem real). Levantado ANTES de
    qualquer escrita em disco -- nunca ha um upload parcialmente gravado."""


@dataclass(frozen=True)
class ScreenshotRecord:
    upload_id: str
    created_at: datetime
    bookmaker: str
    match_key: str
    tab_type: str
    original_filename: str
    stored_path: str  # relativo a data/raw/ -- nunca o caminho absoluto da maquina
    mime_type: str
    file_size: int
    sha256: str

    def to_json_dict(self) -> dict:
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        return data


def _validate_match_key(match_key: str) -> str:
    match_key = (match_key or "").strip()
    if not match_key:
        raise InvalidScreenshotError("match_key nao pode ser vazio.")
    return match_key


def _validate_tab_type(tab_type: str) -> str:
    if tab_type not in _ALLOWED_TAB_TYPES:
        raise InvalidScreenshotError(f"tab_type invalido: {tab_type!r}.")
    return tab_type


def _validate_size(content: bytes) -> None:
    if len(content) == 0:
        raise InvalidScreenshotError("Arquivo vazio.")
    if len(content) > cfg.MAX_FILE_SIZE_BYTES:
        limit_mb = cfg.MAX_FILE_SIZE_BYTES // (1024 * 1024)
        raise InvalidScreenshotError(f"Arquivo excede o tamanho maximo de {limit_mb} MB.")


def _validate_and_identify_image(content: bytes) -> tuple[str, str]:
    """Abre a imagem de verdade (Pillow) para descobrir o formato real --
    nunca confia na extensao do nome do arquivo nem no Content-Type
    declarado pelo cliente. Devolve (extensao, mime_type)."""
    try:
        with Image.open(BytesIO(content)) as img:
            img.verify()
        # verify() invalida o objeto Image -- reabre para completar a
        # leitura, conforme a documentacao do Pillow recomenda.
        with Image.open(BytesIO(content)) as img:
            fmt = img.format
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise InvalidScreenshotError("Arquivo nao e uma imagem valida.") from exc

    allowed = cfg.ALLOWED_IMAGE_FORMATS.get(fmt or "")
    if allowed is None:
        raise InvalidScreenshotError(f"Formato de imagem nao permitido: {fmt!r}.")
    return allowed


def save_screenshot(*, content: bytes, original_filename: str, match_key: str, tab_type: str) -> ScreenshotRecord:
    match_key = _validate_match_key(match_key)
    tab_type = _validate_tab_type(tab_type)
    _validate_size(content)
    extension, mime_type = _validate_and_identify_image(content)

    upload_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc)
    sha256 = hashlib.sha256(content).hexdigest()

    relative_dir = f"bookmaker_screenshots/{created_at:%Y}/{created_at:%m}/{created_at:%d}"
    file_stem = f"{upload_id}_{tab_type}"

    day_dir = cfg.SCREENSHOTS_RAW_DIR / f"{created_at:%Y}" / f"{created_at:%m}" / f"{created_at:%d}"
    day_dir.mkdir(parents=True, exist_ok=True)

    image_path = day_dir / f"{file_stem}.{extension}"
    metadata_path = day_dir / f"{file_stem}.json"

    # upload_id vem de uuid4 -- colisao e praticamente impossivel, mas o
    # historico e append-only (item do pedido: nunca sobrescrever um print
    # anterior), entao uma colisao nunca deve resultar em sobrescrita
    # silenciosa.
    if image_path.exists() or metadata_path.exists():
        raise RuntimeError(f"Colisao inesperada de upload_id: {upload_id}")

    image_path.write_bytes(content)

    record = ScreenshotRecord(
        upload_id=upload_id,
        created_at=created_at,
        bookmaker=cfg.DEFAULT_BOOKMAKER,
        match_key=match_key,
        tab_type=tab_type,
        original_filename=original_filename or "",
        stored_path=f"{relative_dir}/{file_stem}.{extension}",
        mime_type=mime_type,
        file_size=len(content),
        sha256=sha256,
    )
    metadata_path.write_text(
        json.dumps(record.to_json_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return record


def _record_from_json_dict(data: dict) -> ScreenshotRecord:
    return ScreenshotRecord(
        upload_id=data["upload_id"],
        created_at=datetime.fromisoformat(data["created_at"]),
        bookmaker=data["bookmaker"],
        match_key=data["match_key"],
        tab_type=data["tab_type"],
        original_filename=data["original_filename"],
        stored_path=data["stored_path"],
        mime_type=data["mime_type"],
        file_size=data["file_size"],
        sha256=data["sha256"],
    )


def find_screenshot(upload_id: str) -> ScreenshotRecord | None:
    """Localiza o sidecar de um upload pelo `upload_id` (nome do arquivo
    e `<upload_id>_<tab_type>.json`, mas o diretorio e particionado por
    data de upload -- por isso a busca varre `SCREENSHOTS_RAW_DIR`, custo
    aceitavel no volume local desta entrega, mesmo raciocinio ja aceito
    para outras varreduras do projeto)."""
    if not cfg.SCREENSHOTS_RAW_DIR.exists():
        return None
    for path in cfg.SCREENSHOTS_RAW_DIR.rglob(f"{upload_id}_*.json"):
        return _record_from_json_dict(json.loads(path.read_text(encoding="utf-8")))
    return None


def resolve_image_path(record: ScreenshotRecord) -> Path:
    """Reconstroi o caminho da imagem a partir de `cfg.SCREENSHOTS_RAW_DIR`
    (a raiz que `save_screenshot` realmente usou para gravar), nunca a
    partir de `cfg.DATA_RAW / stored_path` -- assim continua correto
    mesmo quando `SCREENSHOTS_RAW_DIR` e substituido por um diretorio
    temporario nos testes (mesmo padrao de `find_screenshot`)."""
    day_dir = cfg.SCREENSHOTS_RAW_DIR / f"{record.created_at:%Y}" / f"{record.created_at:%m}" / f"{record.created_at:%d}"
    stem = f"{record.upload_id}_{record.tab_type}"
    for path in day_dir.glob(f"{stem}.*"):
        if path.suffix.lower() != ".json":
            return path
    raise FileNotFoundError(f"Imagem nao encontrada em disco para upload_id={record.upload_id!r}.")
