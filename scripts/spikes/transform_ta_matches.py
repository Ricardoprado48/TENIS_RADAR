import json
import pandas as pd
from pathlib import Path

OUTPUT_DIR = Path("data/outputs/spikes/tennis_abstract")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

with open(OUTPUT_DIR / "sample_players_summary.json", encoding="utf-8") as f:
    players = json.load(f)

# Collect all post-cutoff matches across the 10 players
# Deduplicate using (tour, matchid) or (tour, date, tourn, sorted_pair, score)
raw_rows = []
seen_match_keys = set()

for p in players:
    info = p["player"]
    tour = info["tour"]
    p_name = info["name"]
    post_matches = p.get("post_matches", [])

    for m in post_matches:
        matchid = m.get("matchid", "")
        date = m.get("date", "")
        tourn = m.get("tourn", "")
        opp = m.get("opp", "")
        score = m.get("score", "")
        wl = m.get("wl", "")

        # Build stable deduplication key
        pair = "|".join(sorted([p_name, opp]))
        context_key = f"{tour}:{date}:{tourn}:{pair}:{score}"

        if context_key in seen_match_keys:
            continue
        seen_match_keys.add(context_key)

        # Map to Winner / Loser row (Sackmann schema format)
        is_winner = (wl == "W")
        winner_name = p_name if is_winner else opp
        loser_name = opp if is_winner else p_name

        def safe_int(val):
            try:
                return int(val) if val != "" else None
            except ValueError:
                return None

        # Parse tourney_id and match_num from matchid (e.g. 2026-560-223)
        tourney_id = ""
        match_num = ""
        if matchid:
            parts = matchid.split("-")
            if len(parts) >= 3:
                tourney_id = f"{parts[0]}-{parts[1]}"
                match_num = parts[2]
            else:
                tourney_id = matchid

        row = {
            "tour": tour.upper(),
            "match_id": f"{tour.upper()}:{tourney_id}:{match_num}" if match_num else f"{tour.upper()}:{tourney_id}",
            "tourney_id": tourney_id,
            "tourney_name": tourn,
            "surface": m.get("surf", ""),
            "tourney_level": m.get("level", ""),
            "tourney_date": date,
            "match_num": match_num,
            "winner_name": winner_name,
            "loser_name": loser_name,
            "score": score,
            "round": m.get("round", ""),
            "minutes": safe_int(m.get("time")),
            # Winner stats
            "w_ace": safe_int(m.get("aces" if is_winner else "oaces")),
            "w_df": safe_int(m.get("dfs" if is_winner else "odfs")),
            "w_svpt": safe_int(m.get("pts" if is_winner else "opts")),
            "w_1stIn": safe_int(m.get("firsts" if is_winner else "ofirsts")),
            "w_1stWon": safe_int(m.get("fwon" if is_winner else "ofwon")),
            "w_2ndWon": safe_int(m.get("swon" if is_winner else "oswon")),
            "w_SvGms": safe_int(m.get("games" if is_winner else "ogames")),
            "w_bpSaved": safe_int(m.get("saved" if is_winner else "osaved")),
            "w_bpFaced": safe_int(m.get("chances" if is_winner else "ochances")),
            # Loser stats
            "l_ace": safe_int(m.get("oaces" if is_winner else "aces")),
            "l_df": safe_int(m.get("odfs" if is_winner else "dfs")),
            "l_svpt": safe_int(m.get("opts" if is_winner else "pts")),
            "l_1stIn": safe_int(m.get("ofirsts" if is_winner else "firsts")),
            "l_1stWon": safe_int(m.get("ofwon" if is_winner else "fwon")),
            "l_2ndWon": safe_int(m.get("oswon" if is_winner else "swon")),
            "l_SvGms": safe_int(m.get("ogames" if is_winner else "games")),
            "l_bpSaved": safe_int(m.get("osaved" if is_winner else "saved")),
            "l_bpFaced": safe_int(m.get("ochances" if is_winner else "chances")),
        }
        raw_rows.append(row)

df_norm = pd.DataFrame(raw_rows)
out_csv = OUTPUT_DIR / "experimental_normalized_matches.csv"
df_norm.to_csv(out_csv, index=False)
print(f"Generated {len(df_norm)} unique normalized matches post-cutoff.")
print(f"Saved to: {out_csv}")
print(f"ATP count: {len(df_norm[df_norm['tour'] == 'ATP'])} | WTA count: {len(df_norm[df_norm['tour'] == 'WTA'])}")
print("\nSample row:")
print(df_norm.iloc[0].to_dict())

