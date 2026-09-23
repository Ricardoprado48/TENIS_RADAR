import json
import urllib.request
import urllib.error

def search_github(query, label):
    url = f"https://api.github.com/search/repositories?q={query}&sort=updated&order=desc"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"\n=== {label} (Total: {data.get('total_count')}) ===")
            for item in data.get("items", [])[:8]:
                print(f"- {item['full_name']} | pushed: {item.get('pushed_at')} | stars: {item.get('stargazers_count')}")
                if item.get('description'):
                    print(f"  desc: {item.get('description')[:100]}")
    except Exception as e:
        print(f"Error in {label}:", e)

def inspect_candidate_repos():
    repos = [
        "riddlejack/Alcaraz",
        "LuckyLoser91/TennisCourtLog",
        "thekasser/tennis-wta-atp",
        "Kadantte/tennis_atp",
    ]
    for repo in repos:
        found = False
        for branch in ["main", "master"]:
            url = f"https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    print(f"\n=== REPO: {repo} (branch: {branch}) ===")
                    matched = [
                        item for item in data.get("tree", [])
                        if item["path"].endswith(".csv") or item["path"].endswith(".parquet") or "2026" in item["path"]
                    ]
                    for item in matched[:15]:
                        print(f"  {item['path']} ({item.get('size')} bytes)")
                    if len(matched) > 15:
                        print(f"  ... and {len(matched)-15} more data files")
                    found = True
                    break
            except Exception:
                continue
        if not found:
            print(f"Could not fetch tree for {repo}")

if __name__ == "__main__":
    inspect_candidate_repos()
