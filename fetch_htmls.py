#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import os
import sys
from bs4 import BeautifulSoup
import time
import re

# -----------------------------
# CONFIG
# -----------------------------
PRINT_HTML = "printversion.html"  # Main print version HTML
FLARESOLVERR_URL = "http://localhost:8191/v1"  # Optional, only if JS rendering needed

# -----------------------------
# HELPER FUNCTIONS
# -----------------------------

def fetch_html(url, local_name):
    """Fetch HTML using FlareSolverr if available, else requests."""
    try:
        # Try FlareSolverr first
        payload = {"cmd": "request.get", "url": url, "maxTimeout": 60000}
        r = requests.post(FLARESOLVERR_URL, json=payload, timeout=70)
        data = r.json()
        if "solution" in data and "response" in data["solution"]:
            html = data["solution"]["response"]
        else:
            r2 = requests.get(url, timeout=30)
            html = r2.text
    except Exception:
        # fallback to simple requests
        r2 = requests.get(url, timeout=30)
        html = r2.text

    # Save HTML locally
    with open(local_name, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[+] Saved HTML: {local_name}")
    return html

def slugify(name):
    """Convert category name to safe filename."""
    return re.sub(r'\W+', '_', name.lower())

# -----------------------------
# MAIN LOGIC
# -----------------------------

if not os.path.exists(PRINT_HTML):
    print(f"[!] {PRINT_HTML} not found. Fetch it manually first or via your previous script.")
    sys.exit(1)

# Parse main printversion.html to find subcategory links
with open(PRINT_HTML, "r", encoding="utf-8") as f:
    soup = BeautifulSoup(f.read(), "html.parser")

subcats = soup.select(".desktopSubCategoryDiv li a")
html_files = []

for link in subcats:
    url = link.get("href", "").strip()
    if not url:
        continue
    # file name based on subcategory text
    name = slugify(link.get_text(strip=True)) + ".html"
    html_files.append(name)
    fetch_html(url, name)
    time.sleep(1)  # polite delay to avoid hammering server

# Always include printversion.html itself
html_files.append(PRINT_HTML)

print(f"[+] All HTML files ready: {html_files}")