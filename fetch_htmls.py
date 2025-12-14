# -*- coding: utf-8 -*-

import requests
import os
import sys
from bs4 import BeautifulSoup
import time
import re
from urllib.parse import urlparse

# -----------------------------
# CONFIG
# -----------------------------
PRINT_HTML = "printversion.html"  # Main print version HTML
FLARESOLVERR_URL = "http://localhost:8191/v1"  # Optional, only if JS rendering needed
BASE_URL = "https://www.daily-sun.com" # Ensure absolute URLs for fetching

# -----------------------------
# HELPER FUNCTIONS
# -----------------------------

def fetch_html(url, local_name):
    """Fetch HTML using FlareSolverr if available, else requests."""
    # Ensure URL is absolute before fetching
    if url.startswith("/"):
        url = BASE_URL + url
    
    print(f"[*] Fetching: {url} -> {local_name}")

    try:
        # Attempt to use FlareSolverr
        payload = {"cmd": "request.get", "url": url, "maxTimeout": 60000}
        r = requests.post(FLARESOLVERR_URL, json=payload, timeout=70)
        data = r.json()
        if "solution" in data and "response" in data["solution"]:
            html = data["solution"]["response"]
        else:
            # Fallback if FlareSolverr fails or returns empty
            r2 = requests.get(url, timeout=30)
            html = r2.text
    except requests.exceptions.RequestException as e:
        # Fallback if FlareSolverr is unreachable
        print(f"[!] FlareSolverr failed or unreachable. Falling back to Requests. Error: {e}")
        try:
            r2 = requests.get(url, timeout=30)
            html = r2.text
        except requests.exceptions.RequestException as e2:
            print(f"[!] Direct request also failed for {url}. Error: {e2}")
            return None # Failed to fetch

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

def main():
    if not os.path.exists(PRINT_HTML):
        print(f"[!] {PRINT_HTML} not found. Please provide the source file.")
        sys.exit(1)

    with open(PRINT_HTML, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    # Target the specific sub-menu for print version
    subcats = soup.select(".desktopSubCategoryDiv li a")

    if not subcats:
        print("[!] Warning: No subcategories found. Check CSS selector or PRINT_HTML content.")
        sys.exit(1)

    html_files = []
    print(f"[*] Found {len(subcats)} subcategories in print menu.")

    for link in subcats:
        url = link.get("href", "").strip()
        text = link.get_text(strip=True)
        
        if not url:
            continue

        base_name = slugify(text)

        # --- REVISED FIX: Rely strictly on path content for Business Print ---
        parsed_url = urlparse(url)
        url_path = parsed_url.path.lower()
        
        # Check if the link URL path contains both "business" AND "print" elements
        # (or the user-specified segment /business-print/)
        if ("/business-print/" in url_path or 
            ("business" in url_path and "print" in url_path)):
            name = "business_printversion.html"
        else:
            name = f"{base_name}.html"

        # Check if the file is already in the list to avoid duplicate processing/fetching
        if name not in html_files:
            html_files.append(name)
            fetch_html(url, name)
            time.sleep(1) # Be gentle on the server

    # Always include printversion.html itself
    if PRINT_HTML not in html_files:
        html_files.append(PRINT_HTML)

    print(f"\n[+] Process complete.")
    print(f"[+] Generated files: {html_files}")


if __name__ == "__main__":
    main()