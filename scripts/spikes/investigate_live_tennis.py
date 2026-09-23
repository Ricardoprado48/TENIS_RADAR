import json
import urllib.request
import urllib.error

def check_github_org():
    url = "https://api.github.com/orgs/livetennisapi/repos"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            repos = json.loads(resp.read().decode("utf-8"))
            print(f"Total repos in org livetennisapi: {len(repos)}")
            for r in repos:
                print(f"- {r.get('name')}: {r.get('description')} (stars: {r.get('stargazers_count')})")
    except Exception as e:
        print("Error checking org:", e)

def check_huggingface():
    url = "https://huggingface.co/api/datasets?search=livetennisapi"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            datasets = json.loads(resp.read().decode("utf-8"))
            print(f"\nHuggingFace datasets matching 'livetennisapi': {len(datasets)}")
            for d in datasets:
                print(f"- {d.get('id')}: {d.get('description', '')[:80]}")
    except Exception as e:
        print("Error checking HuggingFace:", e)

def search_github_datasets():
    url = "https://api.github.com/search/repositories?q=livetennisapi+dataset"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"\nGitHub repos matching 'livetennisapi dataset': {data.get('total_count')}")
            for item in data.get("items", [])[:5]:
                print(f"- {item['full_name']}: {item.get('description')}")
    except Exception as e:
        print("Error searching GitHub repos:", e)

def check_repo_tree():
    url = "https://api.github.com/repos/livetennisapi/livetennisapi-data/git/trees/main?recursive=1"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print("\nTree of livetennisapi-data:")
            for item in data.get("tree", []):
                print(f"- {item['path']} ({item.get('size')} bytes)")
    except Exception as e:
        print("Error checking repo tree:", e)

if __name__ == "__main__":
    print("=== GITHUB REPOS ===")
    check_github_org()
    print("=== HUGGINGFACE ===")
    check_huggingface()
    print("=== GITHUB SEARCH ===")
    search_github_datasets()
    print("=== REPO TREE ===")
    check_repo_tree()
