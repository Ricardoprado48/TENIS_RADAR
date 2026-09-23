"""Investigacao de coleta automatica na Betano (item 4 da instrucao).

Prioridade pedida: (1) HTTP publico estruturado; (2) HTML publico; (3)
browser automation somente se necessario. Proibido: login automatizado,
contornar CAPTCHA/anti-bot, usar proxy para evasao, reproduzir autenticacao
privada, scraping massivo. `check_http_endpoint` e `check_robots` sao
funcoes puras (recebem o resultado de uma chamada de rede ja feita, nao
fazem a chamada elas mesmas) para que os testes unitarios nao dependam de
rede -- o mesmo padrao usado em `src/incremental/sources.py` (Fase 8.1).
"""

from __future__ import annotations

import json

from . import config as cfg


def classify_http_status(status_code: int | None, error: str | None = None) -> tuple[str, str]:
    """Classifica o resultado de uma tentativa de acesso HTTP direto, sem
    fazer a chamada de rede (item de nao reimplementar side-effects em
    funcao testavel)."""

    if error is not None:
        return "unavailable", f"erro de rede: {error}"
    if status_code == 200:
        return "adequate_pending_schema_check", "HTTP 200 -- precisa checar se o conteudo esta acessivel sem JS"
    if status_code in (401, 403):
        return "blocked_anti_bot", f"HTTP {status_code} -- bloqueio de bot (Akamai ou equivalente), nao contornado"
    if status_code in (301, 302, 308):
        return "redirect", f"HTTP {status_code} -- redirecionamento, requer nova checagem no destino"
    return "unavailable", f"HTTP {status_code} inesperado"


# item 4: evidencia real coletada nesta execucao (22/09/2026), reproduzivel
# com `curl`/WebFetch puros, sem qualquer contorno de bloqueio. Todas as
# tentativas usaram apenas GET publico, sem login, sem cookies de sessao,
# sem proxy, sem resolucao de CAPTCHA.
REAL_EVIDENCE = [
    {
        "url": "https://www.betano.com/",
        "method": "curl (HTTP puro)",
        "status_code": 403,
        "result": "blocked_anti_bot",
        "note": "Bloqueio de bot no dominio global .com.",
    },
    {
        "url": "https://www.betano.com/sport/tenis/",
        "method": "curl (HTTP puro)",
        "status_code": 403,
        "result": "blocked_anti_bot",
        "note": "Mesma pagina de tenis, mesmo bloqueio.",
    },
    {
        "url": "https://www.betano.com/api/sport/tennis",
        "method": "curl (HTTP puro, endpoint hipotetico)",
        "status_code": 403,
        "result": "blocked_anti_bot",
        "note": "Nao existe API publica documentada; endpoint de teste tambem bloqueado.",
    },
    {
        "url": "https://www.betano.com/sport/tenis/",
        "method": "WebFetch (ferramenta de leitura assistida, renderiza como navegador)",
        "status_code": 403,
        "result": "blocked_anti_bot",
        "note": (
            "A mesma ferramenta que, na Fase 8, conseguiu ler paginas de "
            "draws/schedule da ATP/WTA Tour (docs/013 secao 1.1) FOI "
            "bloqueada aqui -- ao contrario da ATP/WTA, a Betano bloqueia "
            "mesmo esse tipo de acesso."
        ),
    },
    {
        "url": "https://www.betano.bet.br/",
        "method": "curl (HTTP puro, dominio BR)",
        "status_code": 403,
        "result": "blocked_anti_bot",
        "note": "Dominio especifico do Brasil, mesmo bloqueio.",
    },
    {
        "url": "https://www.betano.bet.br/sport/tenis/",
        "method": "curl (HTTP puro, dominio BR)",
        "status_code": 403,
        "result": "blocked_anti_bot",
        "note": "Pagina de tenis do dominio BR, mesmo bloqueio.",
    },
    {
        "url": "https://www.betano.bet.br/sport/tenis/",
        "method": "WebFetch (ferramenta de leitura assistida)",
        "status_code": 403,
        "result": "blocked_anti_bot",
        "note": "Mesmo bloqueio via ferramenta de leitura assistida.",
    },
]

# item 12/pesquisa: nenhuma API oficial publica de odds foi encontrada
# (WebSearch, 22/09/2026) -- apenas revendedores terceirizados (Apify,
# OpticOdds, SharpAPI, Betstamp, OddsPapi, Parse.bot) que fazem scraping da
# Betano por conta propria e vendem o resultado como API. Usar qualquer um
# desses seria delegar exatamente o scraping/contorno de bloqueio que a
# instrucao proibe fazer diretamente -- por isso nenhum foi adotado.
THIRD_PARTY_RESELLERS_FOUND = [
    "apify.com/blackfalcondata/betano-odds-api",
    "opticodds.com/sportsbooks/betano-api",
    "sharpapi.io/sportsbooks/betano-odds-api",
    "betstamp.com/odds/betano",
    "oddspapi.io/sportsbooks/betano-bet-br",
    "parse.bot/marketplace/.../betano-com-api",
]


def run_betano_investigation() -> dict:
    """Roda a investigacao (usa a evidencia real coletada nesta sessao, nao
    refaz chamadas de rede a cada execucao -- ver REAL_EVIDENCE) e grava
    `source_investigation.{json,md}`, no mesmo espirito de
    `src/incremental/sources.py::run_source_investigation` (Fase 8.1)."""

    cfg.BETANO_INVESTIGATION_DIR.mkdir(parents=True, exist_ok=True)

    adequate = any(e["result"] not in ("blocked_anti_bot", "unavailable") for e in REAL_EVIDENCE)

    result = {
        "investigated_at": "2026-09-22",
        "adequate_automatic_source_found": adequate,
        "evidence": REAL_EVIDENCE,
        "third_party_resellers_found_not_used": THIRD_PARTY_RESELLERS_FOUND,
        "conclusion": (
            "Nenhum acesso HTTP publico (puro ou via ferramenta de leitura "
            "assistida) a Betano retornou conteudo -- todas as 7 tentativas "
            "documentadas voltaram HTTP 403 (bloqueio de bot). Revendedores "
            "terceirizados de odds da Betano existem, mas dependem do mesmo "
            "scraping/contorno de bloqueio proibido pela instrucao, entao "
            "nao foram usados. A entrada manual (scripts/record_odds.py) e "
            "a solucao operacional oficial desta fase."
        ),
    }

    with open(cfg.BETANO_INVESTIGATION_DIR / "source_investigation.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    lines = [
        "# Investigacao de coleta automatica -- Betano (Fase 9, item 4)",
        "",
        f"Fonte adequada encontrada: **{adequate}**",
        "",
        "| URL | Metodo | Status | Resultado |",
        "|---|---|---:|---|",
    ]
    for e in REAL_EVIDENCE:
        lines.append(f"| {e['url']} | {e['method']} | {e['status_code']} | {e['result']} |")
    lines += ["", result["conclusion"]]
    with open(cfg.BETANO_INVESTIGATION_DIR / "source_investigation.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return result
