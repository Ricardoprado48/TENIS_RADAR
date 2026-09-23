import urllib.request
import re

url = "http://www.tennisabstract.com/cgi-bin/player-classic.cgi?p=CarlosAlcaraz"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        html = resp.read().decode("utf-8", errors="ignore")
        print("Status:", resp.status)
        print("Total length:", len(html))
        # Look for headers or column names
        tables = re.findall(r"<table[^>]*>", html)
        print("Tables found:", len(tables), tables[:5])
        # Look for words like Ace, Df, 1stIn
        keywords = ["Ace%", "DF%", "1stIn", "1st%", "2nd%", "BPSvd", "Hld%"]
        found = [k for k in keywords if k in html]
        print("Keywords found:", found)
        # Check rows for 2026
        rows_2026 = [line for line in html.splitlines() if "2026" in line and ("Wimbledon" in line or "Roland Garros" in line or "US Open" in line)]
        print(f"2026 match rows count: {len(rows_2026)}")
        for r in rows_2026[:5]:
            print("  ", r[:120])
except Exception as e:
    print("Error:", e)

