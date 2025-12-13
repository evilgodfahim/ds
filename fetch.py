import requests
import sys

FLARESOLVERR_URL = "http://localhost:8191/v1"

TARGETS = {
    "opinion.html": "https://www.daily-sun.com/opinion",
    "editorial.html": "https://www.daily-sun.com/editorial",
    "todays-news.html": "https://www.daily-sun.com/todays-news",
    "business.html": "https://www.daily-sun.com/business",
    "deep_dive.html": "https://www.daily-sun.com/deep_dive",
    "diplomacy.html": "https://www.daily-sun.com/diplomacy",
    "printversion.html": "https://www.daily-sun.com/printversion",
}

for filename, url in TARGETS.items():
    payload = {
        "cmd": "request.get",
        "url": url,
        "maxTimeout": 60000
    }

    r = requests.post(FLARESOLVERR_URL, json=payload)
    data = r.json()

    if "error" in data:
        print(f"FlareSolverr error for {url}:", data["error"])
        sys.exit(1)

    if "solution" not in data or "response" not in data["solution"]:
        print(f"Invalid FlareSolverr response for {url}:", data)
        sys.exit(1)

    html = data["solution"]["response"]

    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
