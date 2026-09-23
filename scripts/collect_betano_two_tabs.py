from __future__ import annotations

import argparse
import json
import re
import sys
import time

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


ROOT = Path(__file__).resolve().parents[1]

OUTPUT_DIR = ROOT / "data" / "raw" / "betano_collector"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# UTILITÁRIOS
# ============================================================

def now_iso():
    return datetime.now(timezone.utc).isoformat()


def safe_slug(value: str):
    value = value.strip().lower()

    value = (
        value
        .replace("á", "a")
        .replace("à", "a")
        .replace("ã", "a")
        .replace("â", "a")
        .replace("é", "e")
        .replace("ê", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ô", "o")
        .replace("õ", "o")
        .replace("ú", "u")
        .replace("ç", "c")
    )

    value = re.sub(r"[^a-z0-9]+", "_", value)

    return value.strip("_")


def decimal(value: str):
    try:
        return float(value.replace(",", "."))
    except Exception:
        return None


def normalize_lines(text: str):
    lines = []

    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()

        if line:
            lines.append(line)

    return lines


# ============================================================
# PLAYWRIGHT
# ============================================================
#
# A Betano usa um carrossel (Swiper.js) para as abas de mercado. Cliques
# sinteticos (Playwright .click(), force=True, mouse.down/up nas
# coordenadas exatas) NAO ativam a aba -- confirmado por teste real:
# a classe "swiper-slide-active" nunca migra para a aba clicada e o
# screenshot/DOM ficam identicos antes e depois. Em vez de tentar
# contornar isso, o coletor abre o navegador visivel e ESPERA que uma
# pessoa clique manualmente na aba; ele so detecta a mudanca de estado
# (polling da classe "swiper-slide-active") e entao extrai o texto.
# Nenhum clique é automatizado nas abas de mercado.

def fetch_real_geolocation(context):
    """
    Busca a localizacao real da rede atual (via IP) usando o proprio
    navegador, para responder ao prompt de geolocalizacao da Betano
    com um valor verdadeiro -- nunca coordenadas inventadas.
    """

    page = context.new_page()

    try:
        page.goto("https://ipinfo.io/json", timeout=15000)
        text = page.locator("body").inner_text(timeout=10000)
        data = json.loads(text)
        lat_str, lon_str = data["loc"].split(",")
        return {"latitude": float(lat_str), "longitude": float(lon_str)}
    except Exception as e:
        print(f"Aviso: nao foi possivel obter geolocalizacao real ({e}).")
        return None
    finally:
        page.close()


def dismiss_known_modals(page):
    """
    Fecha modais legitimos e ja respondidos pelo usuario nesta sessao:
    verificacao de maioridade (autoatestacao "Sim, sou maior de 18"),
    banner promocional de boas-vindas e banner de cookies. Nenhum deles
    e um mecanismo anti-bot -- sao consentimentos normais de um site
    de apostas regulado.
    """

    ok_btn = page.locator('[data-qa="age-verification-modal-ok-button"]')
    if ok_btn.count():
        try:
            ok_btn.first.click(timeout=8000)
            print("Verificacao de idade (18+) confirmada.")
            page.wait_for_timeout(800)
        except Exception:
            pass

    close_btn = page.locator('[data-testid="landing-modal-close-button"]')
    if close_btn.count():
        try:
            close_btn.first.click(timeout=5000)
            page.wait_for_timeout(500)
        except Exception:
            pass

    for txt in ["Rejeitar Todos", "Permitir Todos"]:
        loc = page.get_by_text(txt, exact=True)
        if loc.count():
            try:
                loc.first.click(timeout=5000)
                page.wait_for_timeout(500)
            except Exception:
                pass
            break


def wait_for_manual_tab_click(page, tab_text, timeout_seconds):
    """
    Espera ate `timeout_seconds` que a aba `tab_text` seja clicada
    manualmente (classe swiper-slide-active migra para ela). Retorna
    True se detectou o clique, False se o tempo esgotou.
    """

    tab = page.get_by_text(tab_text, exact=True).first

    if not tab.count():
        print(f"Aba '{tab_text}' nao encontrada na pagina.")
        return False

    print()
    print(f">>> Clique na aba \"{tab_text}\" na janela do navegador.")
    print(f"    Aguardando ate {timeout_seconds}s...")

    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        try:
            is_active = tab.evaluate(
                "el => !!el.closest('.swiper-slide')?.classList.contains('swiper-slide-active')"
            )
        except Exception:
            is_active = False

        if is_active:
            page.wait_for_timeout(1000)
            print(f"Aba \"{tab_text}\" detectada como ativa.")
            return True

        page.wait_for_timeout(500)

    print(f"Tempo esgotado esperando o clique em \"{tab_text}\".")
    return False


def page_visible_text(page):
    try:
        return page.locator("body").inner_text(timeout=10000)
    except Exception:
        return ""


# ============================================================
# PARSER DE ACES
# ============================================================

def extract_section(lines, title, stop_titles):
    """
    Extrai as linhas abaixo de um título até o próximo mercado.
    """

    start = None

    for i, line in enumerate(lines):
        if line.lower() == title.lower():
            start = i + 1
            break

    if start is None:
        return []

    result = []

    for line in lines[start:]:
        lower = line.lower()

        if any(
            lower == stop.lower()
            for stop in stop_titles
        ):
            break

        result.append(line)

    return result


def parse_plus_markets(section_lines):
    """
    Procura:
       3+
       1.21
       4+
       1.52

    ou:
       3+ 1.21
    """

    results = []

    # Junta tudo para também aceitar pares na mesma linha
    joined = " ".join(section_lines)

    pattern = re.compile(
        r"(?P<target>\d+)\+\s+"
        r"(?P<odd>\d+(?:[.,]\d+)?)"
    )

    for match in pattern.finditer(joined):
        target = int(match.group("target"))
        odd = decimal(match.group("odd"))

        if odd is None:
            continue

        # Betano 6+ = nosso Over 5.5
        model_line = target - 0.5

        results.append({
            "bookmaker_display": f"{target}+",
            "model_side": "Over",
            "model_line": model_line,
            "decimal_odds": odd,
        })

    return results


def parse_aces(text, player1, player2):
    lines = normalize_lines(text)

    desired = [
        ("total_aces_match", None, "Total de Aces"),
        ("aces_player", player1, f"{player1} Aces"),
        ("aces_player", player2, f"{player2} Aces"),
    ]

    all_market_titles = [
        line
        for line in lines
        if (
            "aces" in line.lower()
            or "duplas faltas" in line.lower()
            or "games" in line.lower()
        )
    ]

    records = []

    for market, player, heading in desired:
        section = extract_section(
            lines,
            heading,
            [
                x for x in all_market_titles
                if x.lower() != heading.lower()
            ],
        )

        pairs = parse_plus_markets(section)

        for pair in pairs:
            records.append({
                "market": market,
                "player": player,
                **pair,
            })

    return records


# ============================================================
# PARSER DE GAMES MAIS/MENOS
# ============================================================

def isolate_games_main_market(text):
    lines = normalize_lines(text)

    start = None

    for i, line in enumerate(lines):
        if line.lower() == "games":
            start = i + 1
            break

    if start is None:
        return lines

    result = []

    stop_markers = [
        "faixa de games",
        "vencedor e total de games",
        "handicap",
    ]

    for line in lines[start:]:
        if any(
            line.lower().startswith(marker)
            for marker in stop_markers
        ):
            break

        result.append(line)

    return result


def parse_games(text):
    lines = isolate_games_main_market(text)
    joined = " ".join(lines)

    records = []

    # Mais de 21.5 1.65
    over_pattern = re.compile(
        r"Mais de\s+"
        r"(?P<line>\d+(?:[.,]\d+)?)"
        r"\s+"
        r"(?P<odd>\d+(?:[.,]\d+)?)",
        re.IGNORECASE,
    )

    # Menos de 21.5 2.12
    under_pattern = re.compile(
        r"Menos de\s+"
        r"(?P<line>\d+(?:[.,]\d+)?)"
        r"\s+"
        r"(?P<odd>\d+(?:[.,]\d+)?)",
        re.IGNORECASE,
    )

    for pattern, side in [
        (over_pattern, "Over"),
        (under_pattern, "Under"),
    ]:
        for match in pattern.finditer(joined):
            market_line = decimal(match.group("line"))
            odd = decimal(match.group("odd"))

            if market_line is None or odd is None:
                continue

            records.append({
                "market": "total_games",
                "player": None,
                "bookmaker_display": (
                    f"{'Mais de' if side == 'Over' else 'Menos de'} "
                    f"{market_line:g}"
                ),
                "model_side": side,
                "model_line": market_line,
                "decimal_odds": odd,
            })

    return records


# ============================================================
# SAÍDA
# ============================================================

def save_collection(
    url,
    tournament,
    tour,
    player1,
    player2,
    aces_text,
    games_text,
    records,
):
    collected_at = now_iso()

    event_slug = safe_slug(
        f"{tour}_{tournament}_{player1}_{player2}"
    )

    timestamp_slug = datetime.now().strftime("%Y%m%d_%H%M%S")

    base = OUTPUT_DIR / f"{timestamp_slug}_{event_slug}"

    # RAW
    aces_raw = base.with_suffix(".aces.txt")
    games_raw = base.with_suffix(".games.txt")

    aces_raw.write_text(
        aces_text,
        encoding="utf-8",
    )

    games_raw.write_text(
        games_text,
        encoding="utf-8",
    )

    # Enriquecer registros
    normalized = []

    for row in records:
        normalized.append({
            "collected_at": collected_at,
            "bookmaker": "Betano",
            "source_method": "playwright_public_page",
            "source_url": url,
            "tour": tour,
            "tournament": tournament,
            "player_a": player1,
            "player_b": player2,
            **row,
        })

    # JSON
    json_path = base.with_suffix(".json")

    payload = {
        "metadata": {
            "collected_at": collected_at,
            "bookmaker": "Betano",
            "source_url": url,
            "tour": tour,
            "tournament": tournament,
            "player_a": player1,
            "player_b": player2,
        },
        "markets": normalized,
    }

    json_path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # CSV
    csv_path = base.with_suffix(".csv")

    if normalized:
        pd.DataFrame(normalized).to_csv(
            csv_path,
            index=False,
            encoding="utf-8-sig",
        )

    return {
        "json": json_path,
        "csv": csv_path,
        "aces_raw": aces_raw,
        "games_raw": games_raw,
    }


# ============================================================
# VISUAL
# ============================================================

def print_results(records):
    if not records:
        print()
        print("Nenhum mercado foi extraído.")
        return

    print()
    print("=" * 72)
    print("BETANO — MERCADOS EXTRAÍDOS")
    print("=" * 72)

    groups = [
        ("ACES DO JOGADOR", "aces_player"),
        ("TOTAL DE ACES", "total_aces_match"),
        ("TOTAL DE GAMES", "total_games"),
    ]

    for title, market in groups:
        rows = [
            row
            for row in records
            if row["market"] == market
        ]

        if not rows:
            continue

        print()
        print(title)
        print("-" * 72)

        current_player = object()

        for row in rows:
            if (
                market == "aces_player"
                and row.get("player") != current_player
            ):
                current_player = row.get("player")
                print()
                print(current_player)

            display = row["bookmaker_display"]
            odd = row["decimal_odds"]

            if market in {
                "aces_player",
                "total_aces_match",
            }:
                print(
                    f"  Betano {display:<8}"
                    f" -> Modelo Over {row['model_line']:.1f}"
                    f" -> Odd {odd:.2f}"
                )

            else:
                print(
                    f"  {display:<20}"
                    f" -> Odd {odd:.2f}"
                )

    print()


# ============================================================
# EXECUÇÃO
# ============================================================

def collect(args):
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
        )

        context = browser.new_context(
            locale="pt-BR",
            viewport={
                "width": 1500,
                "height": 1000,
            },
            permissions=["geolocation"],
        )

        geo = fetch_real_geolocation(context)

        if geo:
            context.set_geolocation(geo)
            print(f"Geolocalizacao real aplicada: {geo}")

        page = context.new_page()

        print()
        print("Abrindo Betano...")
        print(args.url)
        print()

        try:
            response = page.goto(
                args.url,
                wait_until="domcontentloaded",
                timeout=45000,
            )
        except PlaywrightTimeoutError:
            print(
                "A página demorou para carregar. "
                "O navegador permanecerá aberto."
            )
            response = None

        page.wait_for_timeout(3000)

        if response is not None:
            print(
                f"HTTP inicial: {response.status}"
            )

            if response.status == 403:
                print()
                print(
                    "A Betano retornou HTTP 403."
                )
                print(
                    "O coletor NÃO tentará contornar "
                    "a proteção anti-bot."
                )
                print()

                browser.close()
                return 2

        dismiss_known_modals(page)
        page.wait_for_timeout(1000)

        # ----------------------------------------
        # ABA ACES (clique manual)
        # ----------------------------------------

        if wait_for_manual_tab_click(page, "Aces", args.tab_timeout):
            aces_text = page_visible_text(page)
        else:
            aces_text = ""

        # ----------------------------------------
        # ABA GAMES MAIS/MENOS (clique manual)
        # ----------------------------------------

        if wait_for_manual_tab_click(page, "Games Mais/Menos", args.tab_timeout):
            games_text = page_visible_text(page)
        else:
            games_text = ""

        # ----------------------------------------
        # PARSE
        # ----------------------------------------

        ace_records = parse_aces(
            aces_text,
            args.player1,
            args.player2,
        )

        games_records = parse_games(
            games_text,
        )

        records = ace_records + games_records

        paths = save_collection(
            url=args.url,
            tournament=args.tournament,
            tour=args.tour,
            player1=args.player1,
            player2=args.player2,
            aces_text=aces_text,
            games_text=games_text,
            records=records,
        )

        print_results(records)

        print("=" * 72)
        print("ARQUIVOS SALVOS")
        print("=" * 72)
        print(paths["json"])
        print(paths["csv"])
        print(paths["aces_raw"])
        print(paths["games_raw"])
        print()

        browser.close()

        return 0


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Coleta somente os mercados Aces "
            "e Games Mais/Menos da página pública "
            "de uma partida da Betano."
        )
    )

    parser.add_argument(
        "url",
        help="URL da partida na Betano",
    )

    parser.add_argument(
        "--tour",
        required=True,
        choices=["ATP", "WTA"],
    )

    parser.add_argument(
        "--tournament",
        required=True,
        help="Nome do torneio",
    )

    parser.add_argument(
        "--player1",
        required=True,
        help="Jogador 1",
    )

    parser.add_argument(
        "--player2",
        required=True,
        help="Jogador 2",
    )

    parser.add_argument(
        "--tab-timeout",
        dest="tab_timeout",
        type=int,
        default=120,
        help="Segundos de espera pelo clique manual em cada aba (padrao: 120)",
    )

    args = parser.parse_args()

    sys.exit(
        collect(args)
    )


if __name__ == "__main__":
    main()
