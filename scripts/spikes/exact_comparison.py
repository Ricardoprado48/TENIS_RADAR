import json
import pandas as pd
from pathlib import Path

df_atp = pd.read_parquet("data/processed/atp/matches.parquet")
df_wta = pd.read_parquet("data/processed/wta/matches.parquet")

with open("data/outputs/spikes/tennis_abstract/sample_players_summary.json", encoding="utf-8") as f:
    players = json.load(f)

comparisons = []

for p_info in players:
    p = p_info["player"]
    tour = p["tour"]
    slug = p["slug"]
    pre_matches = p_info.get("sample_pre_matches", [])
    df_target = df_atp if tour == "atp" else df_wta

    for m_ta in pre_matches:
        ta_date = m_ta.get("date", "")
        ta_score = m_ta.get("score", "")
        ta_opp = m_ta.get("opp", "")
        ta_wl = m_ta.get("wl", "")
        if not ta_date or not ta_score or ta_score == "W/O":
            continue

        dt_str = f"{ta_date[:4]}-{ta_date[4:6]}-{ta_date[6:]}"
        opp_last = ta_opp.split()[-1].lower() if ta_opp else ""
        p_last = p["name"].split()[-1].lower()

        sub = df_target[
            (df_target["tournament_date"] == dt_str) &
            (df_target["result"] == ta_wl) &
            (df_target["player_name"].str.lower().str.contains(p_last)) &
            (df_target["opponent_name"].str.lower().str.contains(opp_last))
        ]

        if len(sub) >= 1:
            row = sub.iloc[0]
            fields = [
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
            comp = {
                "tour": tour.upper(),
                "player": p["name"],
                "opponent": str(row["opponent_name"]),
                "date": dt_str,
                "tournament": m_ta.get("tourn"),
                "score": str(row["score"]),
                "all_exact": True,
                "field_matches": {}
            }
            for f_name, ta_col, local_col in fields:
                val_ta = int(m_ta.get(ta_col)) if m_ta.get(ta_col) != "" else None
                val_loc = int(row.get(local_col)) if pd.notna(row.get(local_col)) else None
                exact = (val_ta == val_loc)
                if not exact:
                    comp["all_exact"] = False
                comp["field_matches"][f_name] = {
                    "ta": val_ta,
                    "sackmann": val_loc,
                    "exact": exact
                }
            comparisons.append(comp)

print(f"Total matched matches: {len(comparisons)}")
atp_matches = [c for c in comparisons if c["tour"] == "ATP"]
wta_matches = [c for c in comparisons if c["tour"] == "WTA"]

print(f"ATP matched: {len(atp_matches)} | All exact: {sum(1 for c in atp_matches if c['all_exact'])}")
print(f"WTA matched: {len(wta_matches)} | All exact: {sum(1 for c in wta_matches if c['all_exact'])}")

out_path = Path("data/outputs/spikes/tennis_abstract/exact_comparison.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(comparisons, f, indent=2, ensure_ascii=False)

print(f"Saved exact comparison to {out_path}")

