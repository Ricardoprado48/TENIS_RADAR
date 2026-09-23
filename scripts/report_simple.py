import subprocess
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def run_original_report():
    cmd = [
        "python",
        str(ROOT / "scripts" / "daily_forward_workflow.py"),
        "report",
    ]

    result = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0:
        print("Erro ao gerar o relatório original.")
        print(result.stderr)
        raise SystemExit(result.returncode)

    return result.stdout


def value_after(line, marker):
    if marker not in line:
        return ""
    return line.split(marker, 1)[1].strip()


def clean_number(value):
    value = value.strip()

    if not value:
        return None

    if value.lower() in {"n/a", "nan", "none"}:
        return None

    return value


def parse_report(text):
    lines = text.splitlines()

    matches_analyzed = None
    odds_recorded = None
    candidates_count = None

    opportunities = []
    current_match = None
    current = None

    in_today = False

    for raw in lines:
        line = raw.strip()

        if line.startswith("HOJE / TODAY"):
            in_today = True
            continue

        if line.startswith("DESEMPENHO HISTORICO"):
            break

        if not in_today:
            continue

        if line.startswith("Partidas analisadas / Matches analyzed:"):
            matches_analyzed = value_after(
                line, "Partidas analisadas / Matches analyzed:"
            )
            continue

        if line.startswith("Odds registradas / Bookmaker odds recorded:"):
            odds_recorded = value_after(
                line, "Odds registradas / Bookmaker odds recorded:"
            )
            continue

        if line.startswith("Candidatos / Candidates:"):
            candidates_count = value_after(
                line, "Candidatos / Candidates:"
            )
            continue

        # Cabeçalho de torneio
        if (
            line
            and "(ATP)" in line or "(WTA)" in line
        ):
            if line.startswith("Mercado"):
                pass
            elif not line.startswith("-"):
                m = re.match(r"^(.*?)\s+\((ATP|WTA)\)$", line)
                if m:
                    current_match = {
                        "tournament": m.group(1).strip(),
                        "tour": m.group(2),
                        "surface": "",
                        "date": "",
                        "players": "",
                    }
                    continue

        if current_match:
            if line.startswith("Superficie / Surface:"):
                current_match["surface"] = value_after(
                    line, "Superficie / Surface:"
                )
                continue

            if line.startswith("Data / Date:"):
                current_match["date"] = value_after(
                    line, "Data / Date:"
                )
                continue

            if (
                " x " in line
                and not line.startswith("Linha")
                and not line.startswith("Edge")
            ):
                current_match["players"] = line.strip()
                continue

        if line.startswith("Mercado / Market:"):
            if current:
                opportunities.append(current)

            market_text = value_after(line, "Mercado / Market:")

            current = {
                "match": dict(current_match or {}),
                "market": market_text,
                "line": None,
                "probability": None,
                "fair_odds": None,
                "bookmaker_odds": None,
                "edge": None,
                "classification": None,
                "result": None,
            }
            continue

        if not current:
            continue

        if line.startswith("Linha / Line:"):
            current["line"] = clean_number(
                value_after(line, "Linha / Line:")
            )

        elif line.startswith("Probabilidade do modelo / Model Probability:"):
            current["probability"] = clean_number(
                value_after(
                    line,
                    "Probabilidade do modelo / Model Probability:",
                )
            )

        elif line.startswith("Odd justa / Fair Odds:"):
            current["fair_odds"] = clean_number(
                value_after(line, "Odd justa / Fair Odds:")
            )

        elif line.startswith("Odd encontrada / Bookmaker Odds:"):
            current["bookmaker_odds"] = clean_number(
                value_after(
                    line,
                    "Odd encontrada / Bookmaker Odds:",
                )
            )

        elif line.startswith("Edge:"):
            current["edge"] = clean_number(
                value_after(line, "Edge:")
            )

        elif line.startswith("Classificacao / Classification:"):
            current["classification"] = clean_number(
                value_after(
                    line,
                    "Classificacao / Classification:",
                )
            )

        elif line.startswith("Resultado / Result:"):
            current["result"] = clean_number(
                value_after(line, "Resultado / Result:")
            )

    if current:
        opportunities.append(current)

    return {
        "matches_analyzed": matches_analyzed,
        "odds_recorded": odds_recorded,
        "candidates_count": candidates_count,
        "opportunities": opportunities,
    }


def category(item):
    c = (item.get("classification") or "").lower()

    if "forte" in c or "strong" in c:
        return "CANDIDATOS"

    if "candidato" in c or "candidate" in c:
        return "CANDIDATOS"

    if "observar" in c or "watch" in c:
        return "OBSERVAR"

    return "DESCARTADOS"


def is_problem(item):
    match = item.get("match", {})

    tournament = (match.get("tournament") or "").strip()
    surface = (match.get("surface") or "").strip()
    players = (match.get("players") or "").strip()

    if not tournament or tournament.upper() == "N/A":
        return True

    if not surface or surface.upper() == "N/A":
        return True

    if not players or "N/A" in players:
        return True

    if not item.get("probability"):
        return True

    return False


def discard_reason(item):
    if not item.get("probability"):
        return "Probabilidade do modelo indisponível"

    if not item.get("bookmaker_odds"):
        return "Odd da casa indisponível"

    c = (item.get("classification") or "").lower()

    if "descart" in c or "discard" in c:
        edge = item.get("edge")
        if edge and edge.startswith("-"):
            return "Preço oferecido abaixo do limite do modelo"

        return "Não passou pelos critérios operacionais"

    return "Registro incompleto"


def print_item(item, idx, show_reason=False):
    market = item.get("market") or "Mercado não identificado"
    line = item.get("line")
    probability = item.get("probability")
    fair = item.get("fair_odds")
    offered = item.get("bookmaker_odds")
    edge = item.get("edge")
    result = item.get("result")
    classification = item.get("classification")

    print(f"{idx}. {market}")

    if line:
        print(f"   {line}")

    if show_reason:
        print(f"   Motivo: {discard_reason(item)}")
    else:
        if probability:
            print(f"   Probabilidade: {probability}")

        if fair:
            print(f"   Odd justa:     {fair}")

        if offered:
            print(f"   Odd Betano:    {offered}")

        if edge:
            print(f"   Edge:          {edge}")

        if classification:
            pt = classification.split("/")[0].strip().upper()
            print(f"   Status:        {pt}")

    if result:
        pt_result = result.split("/")[0].strip().upper()
        print(f"   Resultado:     {pt_result}")

    print()


def main():
    original = run_original_report()
    data = parse_report(original)

    opportunities = data["opportunities"]

    valid = [x for x in opportunities if not is_problem(x)]
    problems = [x for x in opportunities if is_problem(x)]

    grouped_matches = {}

    for item in valid:
        match = item["match"]

        key = (
            match.get("tournament"),
            match.get("tour"),
            match.get("surface"),
            match.get("date"),
            match.get("players"),
        )

        grouped_matches.setdefault(key, []).append(item)

    print()
    print("=" * 68)
    print("TENNIS RADAR — HOJE")
    print("=" * 68)

    global_idx = 1

    for key, items in grouped_matches.items():
        tournament, tour, surface, date, players = key

        print()
        print(f"{tournament.upper()} — {tour}")
        print(surface)

        if date:
            print(f"Data: {date}")

        print()
        print(players)
        print()

        for section in ["CANDIDATOS", "OBSERVAR", "DESCARTADOS"]:
            subset = [x for x in items if category(x) == section]

            if not subset:
                continue

            print("-" * 68)
            print(section)
            print("-" * 68)
            print()

            for item in subset:
                print_item(
                    item,
                    global_idx,
                    show_reason=(section == "DESCARTADOS"),
                )
                global_idx += 1

    if problems:
        print()
        print("=" * 68)
        print("REGISTROS COM PROBLEMA")
        print("=" * 68)
        print()

        for item in problems:
            match = item.get("match", {})
            players = match.get("players") or "Partida não identificada"
            market = item.get("market") or "Mercado não identificado"

            print(f"- {players}")
            print(f"  {market}")
            print(f"  Problema: {discard_reason(item)}")
            print()

    resolved = 0
    pending = 0

    counts = {
        "CANDIDATOS": 0,
        "OBSERVAR": 0,
        "DESCARTADOS": 0,
    }

    for item in opportunities:
        result = (item.get("result") or "").lower()

        if (
            not result
            or "pendente" in result
            or "pending" in result
        ):
            pending += 1
        else:
            resolved += 1

        counts[category(item)] += 1

    print()
    print("=" * 68)
    print("RESUMO")
    print("=" * 68)
    print()

    print(f"Previsões registradas: {len(opportunities)}")
    print(f"Resolvidas:             {resolved}")
    print(f"Pendentes:              {pending}")
    print()
    print(f"Candidatos:             {counts['CANDIDATOS']}")
    print(f"Observar:               {counts['OBSERVAR']}")
    print(f"Descartados:            {counts['DESCARTADOS']}")
    print()

    print("=" * 68)


if __name__ == "__main__":
    main()
