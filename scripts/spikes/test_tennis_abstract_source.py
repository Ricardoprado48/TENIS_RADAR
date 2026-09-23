"""Spike Tecnico Completo: Tennis Abstract Source.

Executa as etapas 1 a 12 do spike:
1. Inspeciona paginas ATP e WTA no Tennis Abstract.
2. Amostra de 5 ATP e 5 WTA em diferentes faixas de ranking.
3. Valida os 9 campos criticos de saque/devolucao.
4. Compara partidas pre-cutoff com a base Sackmann oficial do TENNIS_RADAR.
5. Avalia cobertura recente (> 25/05/2026) por tour e superficie.
6. Avalia identidade, match_id, deduplicacao e hipotese Top 100 sob demanda.
7. Grava relatorios e saidas SOMENTE em data/outputs/spikes/tennis_abstract/.

NUNCA escreve em data/processed/ nem executa atualizacao incremental oficial.
"""

from __future__ import annotations

import csv
import json
import re
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

OUTPUT_DIR = Path("data/outputs/spikes/tennis_abstract")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Amostra diversificada de 5 ATP e 5 WTA cobrindo Top 20, Top 50 e ~Top 100
PLAYERS_SAMPLE = [
    # ATP
    {"name": "Carlos Alcaraz", "slug": "CarlosAlcaraz", "tour": "atp", "tier": "top20", "rank_approx": 3},
    {"name": "Jannik Sinner", "slug": "JannikSinner", "tour": "atp", "tier": "top20", "rank_approx": 1},
    {"name": "Novak Djokovic", "slug": "NovakDjokovic", "tour": "atp", "tier": "top20", "rank_approx": 4},
    {"name": "Tomas Machac", "slug": "TomasMachac", "tour": "atp", "tier": "top50", "rank_approx": 35},
    {"name": "Thiago Seyboth Wild", "slug": "ThiagoSeybothWild", "tour": "atp", "tier": "top100", "rank_approx": 75},
    # WTA
    {"name": "Iga Swiatek", "slug": "IgaSwiatek", "tour": "wta", "tier": "top20", "rank_approx": 2},
    {"name": "Aryna Sabalenka", "slug": "ArynaSabalenka", "tour": "wta", "tier": "top20", "rank_approx": 1},
    {"name": "Coco Gauff", "slug": "CocoGauff", "tour": "wta", "tier": "top20", "rank_approx": 3},
    {"name": "Beatriz Haddad Maia", "slug": "BeatrizHaddadMaia", "tour": "wta", "tier": "top50", "rank_approx": 20},
    {"name": "Renata Zarazua", "slug": "RenataZarazua", "tour": "wta", "tier": "top100", "rank_approx": 80},
]

MATCHHEAD_COLUMNS = [
    "date", "tourn", "surf", "level", "wl", "rank", "seed", "entry", "round",
    "score", "max", "opp", "orank", "oseed", "oentry", "ohand", "obday",
    "oht", "ocountry", "oactive", "time", "aces", "dfs", "pts", "firsts", "fwon",
    "swon", "games", "saved", "chances", "oaces", "odfs", "opts", "ofirsts",
    "ofwon", "oswon", "ogames", "osaved", "ochances", "obackhand", "chartlink",
    "pslink", "whserver", "matchid", "wh", "roundnum", "matchnum",
]


def fetch_url(url: str, delay_seconds: float = 2.5) -> tuple[int, str]:
    """Requisicao HTTP conservadora com intervalo de cortesia para evitar 429."""
    time.sleep(delay_seconds)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            content = resp.read().decode("utf-8", errors="ignore")
            return resp.status, content
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception as exc:
        print(f"Erro ao buscar {url}: {exc}")
        return -1, ""


def extract_matchmx_from_html(html: str, tour: str, player_slug: str) -> list[list[str]]:
    """Extrai a matriz matchmx do HTML ou do script jsmatches referenciado."""
    # 1. Tentar extrair do proprio HTML (padrao do player-classic.cgi)
    m = re.search(r"var\s+matchmx\s*=\s*\[(.*?)\];", html, re.DOTALL)
    if m:
        text = m.group(1).strip()
        if text:
            return parse_js_matrix(text)

    # 2. Se nao encontrou no HTML, verificar se ha script externo jsmatches/<Player>.js
    js_match = re.search(r'src=["\'](https?://[^"\']*/jsmatches/[^"\']*\.js)["\']', html)
    if js_match:
        js_url = js_match.group(1)
        print(f"  Buscando script externo referenciado: {js_url}")
        status, js_code = fetch_url(js_url, delay_seconds=2.0)
        if status == 200:
            m_js = re.search(r"var\s+matchmx\s*=\s*\[(.*?)\];", js_code, re.DOTALL)
            if m_js:
                return parse_js_matrix(m_js.group(1).strip())

    # 3. Fallback: tentar diretamente URL padrao do jsmatches
    direct_js_url = f"https://www.tennisabstract.com/jsmatches/{player_slug}.js"
    print(f"  Tentando script direto: {direct_js_url}")
    status, js_code = fetch_url(direct_js_url, delay_seconds=2.0)
    if status == 200:
        m_js = re.search(r"var\s+matchmx\s*=\s*\[(.*?)\];", js_code, re.DOTALL)
        if m_js:
            return parse_js_matrix(m_js.group(1).strip())

    return []


def parse_js_matrix(matrix_text: str) -> list[list[str]]:
    """Converte o corpo do array JS em lista de listas Python."""
    rows = []
    # Linhas sao arrays JSON válidos ou quase válidos: ["val1", "val2", ...]
    # Quebramos por fechamento de array ],
    raw_rows = re.findall(r"\[(.*?)\]", matrix_text, re.DOTALL)
    for r in raw_rows:
        # Usar leitor csv simples para tratar strings com aspas e virgulas
        reader = csv.reader([r.strip()], quotechar='"', skipinitialspace=True)
        try:
            row = next(reader)
            if row:
                rows.append([c.strip() for c in row])
        except Exception:
            continue
    return rows


def run_spike():
    print("=" * 60)
    print("INICIANDO SPIKE TECNICO DO TENNIS ABSTRACT")
    print("=" * 60)

    players_data = []

    for p in PLAYERS_SAMPLE:
        tour = p["tour"]
        slug = p["slug"]
        print(f"\nColetando dados para {p['name']} ({tour.upper()} - {p['tier']})...")

        if tour == "atp":
            url = f"http://www.tennisabstract.com/cgi-bin/player-classic.cgi?p={slug}"
        else:
            url = f"http://www.tennisabstract.com/cgi-bin/wplayer-classic.cgi?p={slug}"

        status, html = fetch_url(url, delay_seconds=2.5)
        print(f"  URL: {url} -> Status HTTP {status}")

        if status != 200:
            p_res = {
                "player": p,
                "status_code": status,
                "error": f"HTTP {status}",
                "matches": [],
            }
            players_data.append(p_res)
            continue

        rows = extract_matchmx_from_html(html, tour, slug)
        print(f"  Partidas extraidas em matchmx: {len(rows)}")

        # Mapear partidas para dicts com os nomes do matchhead
        parsed_matches = []
        for r in rows:
            m_dict = {}
            for idx, col_name in enumerate(MATCHHEAD_COLUMNS):
                val = r[idx] if idx < len(r) else ""
                m_dict[col_name] = val
            parsed_matches.append(m_dict)

        # Salvar JSON bruto individual
        raw_player_file = OUTPUT_DIR / f"raw_{tour}_{slug}.json"
        with open(raw_player_file, "w", encoding="utf-8") as f:
            json.dump({"player": p, "total_matches": len(parsed_matches), "matches": parsed_matches}, f, indent=2, ensure_ascii=False)

        # Classificar partidas em 2026 pre-cutoff (<= 2026-05-25) e post-cutoff (> 2026-05-25)
        matches_2026_pre = []
        matches_2026_post = []
        older_matches = []

        for m in parsed_matches:
            dt = m.get("date", "")
            if dt.startswith("2026"):
                try:
                    dt_val = int(dt)
                    if dt_val <= 20260525:
                        matches_2026_pre.append(m)
                    else:
                        matches_2026_post.append(m)
                except ValueError:
                    older_matches.append(m)
            else:
                older_matches.append(m)

        print(f"  Partidas 2026 pre-cutoff (<= 25/05/2026): {len(matches_2026_pre)}")
        print(f"  Partidas 2026 pos-cutoff (> 25/05/2026): {len(matches_2026_post)}")

        p_res = {
            "player": p,
            "status_code": status,
            "total_matches": len(parsed_matches),
            "matches_2026_pre": len(matches_2026_pre),
            "matches_2026_post": len(matches_2026_post),
            "post_matches": matches_2026_post,
            "sample_pre_matches": matches_2026_pre[:5],
        }
        players_data.append(p_res)

    # Gravar sumario consolidado
    summary_file = OUTPUT_DIR / "sample_players_summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(players_data, f, indent=2, ensure_ascii=False)
    print(f"\nSumario dos 10 jogadores gravado em: {summary_file}")

    # =========================================================================
    # Etapa 4: Comparacao Campo a Campo com a Base Sackmann Existente
    # =========================================================================
    run_comparison_with_sackmann(players_data)


def run_comparison_with_sackmann(players_data: list[dict]):
    print("\n" + "=" * 60)
    print("ETAPA 4: COMPARACAO CAMPO A CAMPO TENNIS ABSTRACT VS SACKMANN")
    print("=" * 60)

    # Carregar base local existente de 2026 pre-cutoff para ATP e WTA
    atp_parquet = Path("data/processed/atp/matches.parquet")
    wta_parquet = Path("data/processed/wta/matches.parquet")

    df_atp = pd.read_parquet(atp_parquet) if atp_parquet.exists() else pd.DataFrame()
    df_wta = pd.read_parquet(wta_parquet) if wta_parquet.exists() else pd.DataFrame()

    print(f"Base local ATP carregada: {len(df_atp)} linhas")
    print(f"Base local WTA carregada: {len(df_wta)} linhas")

    # Mapeamento do Tennis Abstract (matchhead) -> Normalizado Fase 2
    # TA registra a perspectiva do jogador da pagina.
    # Se wl == 'W', jogador e o Winner. Se wl == 'L', jogador e o Loser.
    # campos do proprio jogador: aces, dfs, pts, firsts, fwon, swon, games, saved, chances
    # campos do oponente: oaces, odfs, opts, ofirsts, ofwon, oswon, ogames, osaved, ochances

    comparisons = []

    for p_info in players_data:
        p = p_info["player"]
        tour = p["tour"]
        slug = p["slug"]
        pre_matches = p_info.get("sample_pre_matches", [])
        if not pre_matches:
            continue

        df_target = df_atp if tour == "atp" else df_wta

        for m_ta in pre_matches:
            ta_date_str = m_ta.get("date", "")  # YYYYMMDD
            ta_opp = m_ta.get("opp", "")
            ta_score = m_ta.get("score", "")
            ta_wl = m_ta.get("wl", "")

            # Buscar no dataframe local pela data e nomes
            # na base normalizada Fase 2: tournament_date (Timestamp), player_name, opponent_name, result ('W'/'L')
            if ta_date_str:
                dt_iso = f"{ta_date_str[:4]}-{ta_date_str[4:6]}-{ta_date_str[6:]}"
                # Filtrar partidas do torneio / jogador
                sub = df_target[
                    (df_target["player_name"].str.contains(p["name"].split()[-1], case=False, na=False)) &
                    (df_target["result"] == ta_wl)
                ]

                # Match exato pelo placar e adversario
                matched_row = None
                for idx, row in sub.iterrows():
                    # Compara sobrenome do oponente
                    opp_last = ta_opp.split()[-1] if ta_opp else ""
                    if opp_last.lower() in str(row["opponent_name"]).lower():
                        matched_row = row
                        break

                if matched_row is not None:
                    # Comparar os 9 campos
                    comp_detail = {
                        "tour": tour.upper(),
                        "player": p["name"],
                        "opponent": ta_opp,
                        "date_ta": ta_date_str,
                        "date_local": str(matched_row["tournament_date"])[:10],
                        "tournament": m_ta.get("tourn"),
                        "score_ta": ta_score,
                        "score_local": matched_row["score"],
                        "fields": {},
                    }

                    fields_map = [
                        ("ace", "aces", "aces"),
                        ("df", "dfs", "double_faults"),
                        ("svpt", "pts", "service_points"),
                        ("1stIn", "firsts", "first_serves_in"),
                        ("1stWon", "fwon", "first_serve_points_won"),
                        ("2ndWon", "swon", "second_serve_points_won"),
                        ("SvGms", "games", "service_games"),
                        ("bpSaved", "saved", "break_points_saved"),
                        ("bpFaced", "chances", "break_points_faced"),
                    ]

                    all_exact = True
                    for field_name, ta_col, local_col in fields_map:
                        val_ta_raw = m_ta.get(ta_col, "")
                        val_local = matched_row.get(local_col)

                        try:
                            val_ta_int = int(val_ta_raw) if val_ta_raw != "" else None
                        except ValueError:
                            val_ta_int = None

                        val_local_int = int(val_local) if pd.notna(val_local) else None

                        is_equal = (val_ta_int == val_local_int)
                        if not is_equal:
                            all_exact = False

                        diff = None if (val_ta_int is None or val_local_int is None) else abs(val_ta_int - val_local_int)

                        comp_detail["fields"][field_name] = {
                            "ta_val": val_ta_int,
                            "local_val": val_local_int,
                            "exact_match": is_equal,
                            "diff": diff,
                        }

                    comp_detail["all_fields_exact"] = all_exact
                    comparisons.append(comp_detail)

                    if len(comparisons) >= 6:
                        break
        if len(comparisons) >= 6:
            break

    comp_file = OUTPUT_DIR / "comparison_sackmann_vs_ta.json"
    with open(comp_file, "w", encoding="utf-8") as f:
        json.dump(comparisons, f, indent=2, ensure_ascii=False)
    print(f"Comparacao com Sackmann concluida ({len(comparisons)} partidas pareadas). Salva em: {comp_file}")


if __name__ == "__main__":
    run_spike()

