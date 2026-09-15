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
BASE_URL = "https://www.daily-sun.com"  # Ensure absolute URLs for fetching

# -----------------------------
# HELPER FUNCTIONS
# -----------------------------

def fetch_html(url, local_name):
    """Fetch HTML using FlareSolverr if available, else requests."""

    # Ensure URL is absolute before fetching
    if url.startswith("/"):
        url = BASE_URL + url

    print(f"[*] Fetching: {url} -> {local_name}")

    html = None

    try:
        # Attempt to use FlareSolverr
        payload = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": 60000
        }

        r = requests.post(
            FLARESOLVERR_URL,
            json=payload,
            timeout=70
        )

        data = r.json()

        if "solution" in data and "response" in data["solution"]:
            html = data["solution"]["response"]

        else:
            # Fallback if FlareSolverr fails or returns empty
            print("[!] FlareSolverr returned no usable response. Falling back to Requests.")

            r2 = requests.get(url, timeout=30)
            r2.raise_for_status()
            html = r2.text

    except (requests.exceptions.RequestException, ValueError) as e:
        # Fallback if FlareSolverr is unreachable or returns invalid JSON
        print(
            f"[!] FlareSolverr failed or unreachable. "
            f"Falling back to Requests. Error: {e}"
        )

        try:
            r2 = requests.get(url, timeout=30)
            r2.raise_for_status()
            html = r2.text

        except requests.exceptions.RequestException as e2:
            print(
                f"[!] Direct request also failed for {url}. "
                f"Error: {e2}"
            )
            return None

    if not html:
        print(f"[!] Empty HTML received from {url}")
        return None

    try:
        with open(local_name, "w", encoding="utf-8") as f:
            f.write(html)

        print(f"[+] Saved HTML: {local_name}")
        return html

    except OSError as e:
        print(f"[!] Could not save {local_name}: {e}")
        return None


def slugify(name):
    """Convert category name to safe filename."""
    return re.sub(r"\W+", "_", name.lower()).strip("_")


# -----------------------------
# MAIN LOGIC
# -----------------------------

def main():
    if not os.path.exists(PRINT_HTML):
        print(
            f"[!] {PRINT_HTML} not found. "
            f"Please provide the source file."
        )
        sys.exit(1)

    # Read the main print version HTML
    try:
        with open(PRINT_HTML, "r", encoding="utf-8-sig") as f:
            html = f.read()
    except OSError as e:
        print(f"[!] Could not read {PRINT_HTML}: {e}")
        sys.exit(1)

    soup = BeautifulSoup(html, "html.parser")

    # ---------------------------------------------------------
    # Daily Sun current print-version category menu
    #
    # Actual HTML structure:
    #
    # .ppCategoryBox
    #   ul
    #     li
    #       a
    #
    # Example:
    # <div class="ppCategoryBox">
    #   ...
    #   <ul>
    #       <li><a href=".../front-page">Front Page</a></li>
    #       <li><a href=".../business-print">Business</a></li>
    #       ...
    #   </ul>
    # </div>
    # ---------------------------------------------------------
    subcats = soup.select(".ppCategoryBox ul li a")

    if not subcats:
        print(
            "[!] Warning: No subcategories found. "
            "Check CSS selector or PRINT_HTML content."
        )
        sys.exit(1)

    html_files = []

    print(f"[*] Found {len(subcats)} categories in print menu.")

    for link in subcats:
        url = link.get("href", "").strip()
        text = link.get_text(" ", strip=True)

        if not url:
            continue

        # Ignore the "All" link because it is the main
        # printversion page already stored in PRINT_HTML.
        if text.lower() == "all":
            print("[*] Skipping main 'All' category.")
            continue

        # Ensure absolute URL
        if url.startswith("/"):
            url = BASE_URL + url

        base_name = slugify(text)

        # ---------------------------------------------------------
        # Business Print special handling
        #
        # Current Daily Sun HTML:
        # Business -> https://www.daily-sun.com/business-print
        #
        # We rely on the URL path rather than category text.
        # ---------------------------------------------------------
        parsed_url = urlparse(url)
        url_path = parsed_url.path.lower().rstrip("/")

        if (
            url_path == "/business-print"
            or "/business-print/" in url_path
            or ("business" in url_path and "print" in url_path)
        ):
            name = "business_printversion.html"
        else:
            name = f"{base_name}.html"

        # Avoid duplicate processing/fetching
        if name in html_files:
            print(f"[*] Skipping duplicate target: {name}")
            continue

        html_files.append(name)

        result = fetch_html(url, name)

        if result is None:
            print(f"[!] Failed to generate: {name}")

        time.sleep(1)  # Be gentle on the server

    # Always include printversion.html itself
    if PRINT_HTML not in html_files:
        html_files.append(PRINT_HTML)

    print("\n[+] Process complete.")
    print(f"[+] Generated files: {html_files}")


if __name__ == "__main__":
    main()