"""Camada de apresentacao bilingue (PT/EN) para os relatorios da Fase 11.

Este modulo NAO calcula nada -- so traduz nomes internos (mercado, lado,
superficie, classificacao, settlement) para rotulos legiveis e formata
numeros com seguranca (nunca `nan`/`None`/nome interno cru na saida). Nenhuma
funcao aqui le probabilidade/odd/edge/classificacao de novo nem recalcula
qualquer metrica -- so recebe valores ja calculados pelas Fases 1-11 e decide
como exibi-los. Os nomes de mercado variam entre bookmakers, por isso toda
informacao operacional e mostrada em portugues e ingles lado a lado."""

from __future__ import annotations

_NA = "N/A"

MARKET_LABELS: dict[str, tuple[str, str]] = {
    "aces_player": ("Aces do jogador", "Player Aces"),
    "total_aces_match": ("Total de aces da partida", "Total Match Aces"),
    "double_faults_player": ("Duplas faltas do jogador", "Player Double Faults"),
}

SIDE_LABELS: dict[str, tuple[str, str]] = {
    "over": ("Mais de", "Over"),
    "under": ("Menos de", "Under"),
}

SURFACE_LABELS: dict[str, tuple[str, str]] = {
    "hard": ("Quadra dura", "Hard"),
    "clay": ("Saibro", "Clay"),
    "grass": ("Grama", "Grass"),
}

CLASSIFICATION_LABELS: dict[str, tuple[str, str]] = {
    "DESCARTAR": ("Descartado", "Discarded"),
    "OBSERVAR": ("Observar", "Watch"),
    "CANDIDATO_FRACO": ("Candidato fraco", "Weak candidate"),
    "CANDIDATO": ("Candidato", "Candidate"),
    "CANDIDATO_FORTE": ("Candidato forte", "Strong candidate"),
}

SETTLEMENT_LABELS: dict[str, tuple[str, str]] = {
    "WIN": ("Acerto", "Win"),
    "LOSS": ("Erro", "Loss"),
    "VOID": ("Anulado", "Void"),
    "UNRESOLVED": ("Pendente", "Pending"),
    "BOOKMAKER_RULE_REQUIRED": ("Aguardando regra da casa", "Awaiting bookmaker rule"),
}


def _is_missing(value) -> bool:
    if value is None:
        return True
    try:
        return value != value  # NaN
    except TypeError:
        return False


def bilingual(label_map: dict[str, tuple[str, str]], key, *, title_fallback: bool = True) -> str:
    """`chave_interna` -> "Rotulo PT / Rotulo EN". Nunca devolve a chave
    interna crua: se nao houver traducao cadastrada, usa um fallback legivel
    (sublinhados -> espacos, Title Case) igual nos dois idiomas."""

    if _is_missing(key):
        return _NA
    entry = label_map.get(str(key))
    if entry is not None:
        return f"{entry[0]} / {entry[1]}"
    if not title_fallback:
        return _NA
    fallback = str(key).replace("_", " ").strip().title()
    return fallback or _NA


def market_label(market) -> str:
    return bilingual(MARKET_LABELS, market)


def side_label(side) -> str:
    return bilingual(SIDE_LABELS, side)


def surface_label(surface) -> str:
    return bilingual(SURFACE_LABELS, str(surface).lower() if not _is_missing(surface) else surface)


def classification_label(classification) -> str:
    return bilingual(CLASSIFICATION_LABELS, classification)


def settlement_label(settlement) -> str:
    return bilingual(SETTLEMENT_LABELS, settlement)


def tour_label(tour) -> str:
    """ATP/WTA sao siglas identicas nos dois idiomas -- so protege contra
    `nan`/`None`, sem duplicar "ATP / ATP"."""
    return fmt_text(tour)


def fmt_pct(x, decimals: int = 0) -> str:
    if _is_missing(x):
        return _NA
    return f"{float(x) * 100:.{decimals}f}%"


def fmt_odds(x) -> str:
    if _is_missing(x):
        return _NA
    return f"{float(x):.2f}"


def fmt_edge_pp(x) -> str:
    """Edge em pontos percentuais (probabilidade modelo - implicita)."""
    if _is_missing(x):
        return _NA
    return f"{float(x) * 100:+.1f} p.p."


def fmt_number(x, decimals: int = 4) -> str:
    if _is_missing(x):
        return _NA
    return f"{float(x):.{decimals}f}"


def fmt_signed_pct(x, decimals: int = 1) -> str:
    if _is_missing(x):
        return _NA
    return f"{float(x) * 100:+.{decimals}f}%"


def fmt_line(value) -> str:
    if _is_missing(value):
        return _NA
    return str(value)


def fmt_text(value) -> str:
    """Qualquer texto livre (jogador, torneio, data, prediction_id) -- so
    protege contra `nan`/`None`, nunca traduz nomes proprios."""

    if _is_missing(value):
        return _NA
    text = str(value).strip()
    return text if text else _NA
