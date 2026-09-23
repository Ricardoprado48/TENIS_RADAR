"""IDs estaveis (item 16: "cada registro deve ter IDs estaveis para
relacionamento") -- hashes deterministicos (sha1, truncado) da chave natural
de cada entidade. Nunca um contador incremental (que dependeria da ordem de
execucao e quebraria em reprocessamentos)."""

from __future__ import annotations

import hashlib


def _stable_id(prefix: str, *parts) -> str:
    key = "|".join("" if p is None else str(p) for p in parts)
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def make_prediction_id(bookmaker, tour, match_id, market, player, side, line) -> str:
    """Identidade da OPORTUNIDADE, nao da odd (item 1): uma vez registrada,
    a probabilidade nunca muda, entao o id nao inclui `collected_at`/
    `decimal_odds` -- esses pertencem aos snapshots de odds
    (`make_snapshot_id`), que podem se repetir varias vezes para a mesma
    previsao."""

    return _stable_id("PRED", bookmaker, tour, match_id, market, player, side, line)


def make_snapshot_id(prediction_id: str, collected_at) -> str:
    return _stable_id("SNAP", prediction_id, collected_at)


def make_match_key(tour: str, match_id: str) -> str:
    return _stable_id("MATCH", tour, match_id)
