import json
from pathlib import Path

with open("data/outputs/spikes/tennis_abstract/sample_players_summary.json", encoding="utf-8") as f:
    players = json.load(f)

print("=== POST-CUTOFF MATCHES ANALYSIS (> 2026-05-25) ===")

total_post_matches = 0
post_matches_with_all_9_fields = 0
by_tour = {"atp": {"total": 0, "complete": 0, "surfaces": {}}, "wta": {"total": 0, "complete": 0, "surfaces": {}}}
tournaments_found = {"atp": set(), "wta": set()}

critical_keys = ["aces", "dfs", "pts", "firsts", "fwon", "swon", "games", "saved", "chances"]

for p in players:
    info = p["player"]
    tour = info["tour"]
    post_list = p.get("post_matches", [])
    
    print(f"\n{info['name']} ({tour.upper()} - {info['tier']}): {len(post_list)} matches post-cutoff")
    for m in post_list:
        total_post_matches += 1
        by_tour[tour]["total"] += 1
        tourn = m.get("tourn", "Unknown")
        surf = m.get("surf", "Unknown")
        date = m.get("date", "Unknown")
        score = m.get("score", "")
        tournaments_found[tour].add(tourn)
        
        # Surface tally
        by_tour[tour]["surfaces"][surf] = by_tour[tour]["surfaces"].get(surf, 0) + 1
        
        # Check if all 9 critical fields are non-empty and numeric
        # Note: if score is W/O (walkover), stats are expected to be empty
        is_walkover = (score == "W/O" or "RET" in score and m.get("pts") == "")
        has_all_9 = True
        if not is_walkover:
            for k in critical_keys:
                v = m.get(k, "")
                if v == "":
                    has_all_9 = False
                    break
        else:
            has_all_9 = True # walkover has no stats by definition
            
        if has_all_9:
            post_matches_with_all_9_fields += 1
            by_tour[tour]["complete"] += 1

print("\n" + "="*50)
print(f"Total post-cutoff matches across 10 players: {total_post_matches}")
print(f"Total with complete 9 stats (or valid W/O): {post_matches_with_all_9_fields}")
print(f"Overall completeness rate: {post_matches_with_all_9_fields / total_post_matches * 100:.1f}%")

print("\n=== BY TOUR ===")
for t, d in by_tour.items():
    pct = (d['complete'] / d['total'] * 100) if d['total'] > 0 else 0
    print(f"{t.upper()}: {d['total']} matches | {d['complete']} complete ({pct:.1f}%)")
    print(f"  Surfaces: {d['surfaces']}")
    print(f"  Tournaments: {sorted(list(tournaments_found[t]))}")

# Let's save this detailed audit
report = {
    "total_post_matches": total_post_matches,
    "complete_post_matches": post_matches_with_all_9_fields,
    "completeness_pct": post_matches_with_all_9_fields / total_post_matches * 100,
    "by_tour": by_tour,
    "tournaments_found": {t: sorted(list(tournaments_found[t])) for t in tournaments_found}
}

with open("data/outputs/spikes/tennis_abstract/post_cutoff_audit.json", "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2)

print("\nDetailed audit saved to data/outputs/spikes/tennis_abstract/post_cutoff_audit.json")

