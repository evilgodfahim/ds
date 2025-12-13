#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unified parser/fetcher for Daily Sun HTML -> per-source RSS XML.

Features:
- Handles multiple sources: opinion, editorial, printversion, todays-news.
- For printversion: discovers subcategory links in printversion.html,
  fetches each subpage (FlareSolverr optional via FLARESOLVERR_URL env var),
  saves subpage HTML files (slugified from label) and parses them.
- Extracts title, link, description, pubDate (best-effort), image (data-src or src).
- Writes one XML per source (opinion.xml, editorial.xml, printversion.xml, todays-news.xml).
- Adds ONLY new articles (dedup by absolute URL).
- Preserves existing XML channel skeleton when present.
- Trims to MAX_ITEMS.
"""

from __future__ import annotations

import os
import re
import sys
import time
import json
import mimetypes
from datetime import datetime, timezone
from typing import List, Dict, Tuple, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET

# ---- CONFIG ----
BASE = "https://www.daily-sun.com"
MAX_ITEMS = 500
FETCH_TIMEOUT = 30
FLARESOLVERR_URL = os.environ.get("FLARESOLVERR_URL")  # optional

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DailySunParser/1.0)"}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)

SOURCES = {
    "opinion": {
        "html": "opinion.html",
        "xml": "opinion.xml",
        "base": BASE,
        "url_contains": "/opinion/"
    },
    "editorial": {
        "html": "editorial.html",
        "xml": "editorial.xml",
        "base": BASE,
        "url_contains": "/editorial/"
    },
    "printversion": {
        "html": "printversion.html",
        "xml": "printversion.xml",
        "base": BASE,
        "url_contains": None  # will use subpage discovery
    },
    "todays-news": {
        "html": "todays-news.html",
        "xml": "todays-news.xml",
        "base": BASE,
        "url_contains": None
    }
}


# ---- Utilities ----
def slugify(text: str) -> str:
    s = text.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    s = s.strip("-")
    if not s:
        s = "subpage"
    return s + ".html"


def fetch_via_flaresolverr(url: str) -> Optional[str]:
    try:
        payload = {"cmd": "request.get", "url": url, "maxTimeout": 60000}
        r = SESSION.post(FLARESOLVERR_URL, json=payload, timeout=FETCH_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            print(f"[flaresolverr] error for {url}: {data['error']}", file=sys.stderr)
            return None
        sol = data.get("solution")
        if not sol or "response" not in sol:
            print(f"[flaresolverr] invalid response for {url}", file=sys.stderr)
            return None
        return sol["response"]
    except Exception as e:
        print(f"[flaresolverr] fetch failed for {url}: {e}", file=sys.stderr)
        return None


def fetch_via_requests(url: str) -> Optional[str]:
    try:
        r = SESSION.get(url, timeout=FETCH_TIMEOUT)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        return r.text
    except Exception as e:
        print(f"[requests] fetch failed for {url}: {e}", file=sys.stderr)
        return None


def fetch_html(url: str) -> Optional[str]:
    if FLARESOLVERR_URL:
        html = fetch_via_flaresolverr(url)
        if html is not None:
            return html
    return fetch_via_requests(url)


def write_file(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def _abs(base: str, href: str) -> str:
    return urljoin(base, href.strip()) if href else ""


def _pick_image_url(img_tag, base: str) -> str:
    if img_tag is None:
        return ""
    url = img_tag.get("data-src") or img_tag.get("data-original") or img_tag.get("src") or ""
    return urljoin(base, url) if url else ""


def _pick_title(container) -> str:
    if container is None:
        return ""
    selectors = [".title26Latest", ".title10", ".title1", ".desktopSectionTitle", ".desktopCategoryTitle",
                 ".title1_7", ".title26", ".title26Latest", ".title10 .strong"]
    for sel in selectors:
        el = container.select_one(sel)
        if el:
            t = el.get_text(strip=True)
            if t:
                return t
    for h in container.find_all(["h1", "h2", "h3"]):
        t = h.get_text(strip=True)
        if t:
            return t
    a = container.find("a", href=True)
    if a and a.get_text(strip=True):
        return a.get_text(strip=True)
    img = container.find("img")
    if img and img.get("alt"):
        return img.get("alt").strip()
    return ""


def _pick_description(container) -> str:
    if container is None:
        return ""
    for cls in ("desktopSummary", "summary", "CatDesc", "desktopSubTitle"):
        p = container.find("p", class_=cls)
        if p and p.get_text(strip=True):
            return p.get_text(strip=True)
    p = container.find("p")
    if p and p.get_text(strip=True):
        return p.get_text(strip=True)
    return ""


def _pick_pub(container) -> str:
    if container is None:
        return ""
    for cls in ("desktopTime", "publishTime", "time", "title1_7"):
        el = container.find(class_=cls)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)
    span = container.find("span", class_=lambda c: c and "paddingR8" in c)
    if span and span.get_text(strip=True):
        return span.get_text(strip=True)
    return ""


def try_parse_rfc822(pub_text: str) -> Optional[str]:
    if not pub_text:
        return None
    s = pub_text.strip()
    if "ago" in s:
        return None
    s = s.replace("\u00A0", " ").strip()
    formats = ["%d %b %Y, %I:%M %p", "%d %b %Y, %H:%M", "%d %b %Y %I:%M %p", "%d %b %Y %H:%M"]
    for fmt in formats:
        try:
            dt = datetime.strptime(s, fmt)
            dt = dt.replace(tzinfo=timezone.utc)
            return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")
        except Exception:
            continue
    return None


# ---- Extraction strategies (generalized) ----
def extract_articles_from_html_string(html: str, base: str, url_contains: Optional[str]) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    collected: List[Dict] = []

    # Primary pattern: div.media blocks
    for block in soup.select("div.media.positionRelative, div.media"):
        link = block.select_one("a.linkOverlay") or block.find("a", href=True)
        if not link or not link.get("href"):
            continue
        url = _abs(base, link.get("href"))
        if url_contains and url_contains not in url:
            continue
        title = _pick_title(block) or link.get_text(strip=True)
        if not title:
            continue
        desc = _pick_description(block)
        pub = _pick_pub(block)
        img = _pick_image_url(block.find("img"), base)
        collected.append({"url": url, "title": title, "desc": desc, "pub": pub, "img": img})

    # Secondary: lead blocks
    for lead in soup.select(".desktopSectionLead, .DCatLead, .Catcards, .desktopSectionLead .thumbnail"):
        link = lead.select_one("a.linkOverlay") or lead.find("a", href=True)
        if not link or not link.get("href"):
            continue
        url = _abs(base, link.get("href"))
        if url_contains and url_contains not in url:
            continue
        title = _pick_title(lead)
        if not title:
            continue
        desc = _pick_description(lead)
        pub = _pick_pub(lead)
        img = _pick_image_url(lead.find("img"), base)
        collected.append({"url": url, "title": title, "desc": desc, "pub": pub, "img": img})

    # Catch-all: linkOverlay anywhere
    for link in soup.select("a.linkOverlay[href]"):
        url = _abs(base, link.get("href"))
        if url_contains and url_contains not in url:
            continue
        # find relevant parent
        parent = link
        for _ in range(4):
            parent = parent.parent
            if parent is None:
                break
            if parent.find("img") or parent.find(["h1", "h2", "h3", "p"]):
                break
        if parent is None:
            parent = link.parent
        title = _pick_title(parent)
        if not title:
            if link.get_text(strip=True):
                title = link.get_text(strip=True)
            else:
                continue
        desc = _pick_description(parent)
        pub = _pick_pub(parent)
        img = _pick_image_url(parent.find("img"), base)
        collected.append({"url": url, "title": title, "desc": desc, "pub": pub, "img": img})

    # Normalize & dedupe by URL preserving first-seen
    seen = set()
    unique = []
    for a in collected:
        if not a.get("url"):
            continue
        if a["url"] in seen:
            continue
        seen.add(a["url"])
        unique.append(a)
    return unique


# ---- Printversion subcategory discovery & fetch ----
def extract_print_subcategories(print_html: str, base: str) -> List[Tuple[str, str]]:
    soup = BeautifulSoup(print_html, "html.parser")
    container = soup.select_one(".desktopSubCategoryDiv")
    if not container:
        container = soup.find("div", class_="desktopSubCategoryDiv")
    out: List[Tuple[str, str]] = []
    if not container:
        return out
    for a in container.select("ul li a[href]"):
        label = a.get_text(strip=True)
        href = a.get("href").strip()
        href = _abs(base, href)
        out.append((label, href))
    return out


# ---- XML helpers ----
def load_or_create_tree(xml_file: str) -> Tuple[ET.ElementTree, ET.Element]:
    if os.path.exists(xml_file):
        try:
            tree = ET.parse(xml_file)
            root = tree.getroot()
            return tree, root
        except ET.ParseError:
            print(f"[xml] parse error for {xml_file}; creating new skeleton", file=sys.stderr)
    root = ET.Element("rss", {"version": "2.0"})
    tree = ET.ElementTree(root)
    return tree, root


def ensure_channel(root: ET.Element, title_text: str, link_text: str, description_text: str) -> ET.Element:
    channel = root.find("channel")
    if channel is None:
        channel = ET.SubElement(root, "channel")
        ET.SubElement(channel, "title").text = title_text
        ET.SubElement(channel, "link").text = link_text
        ET.SubElement(channel, "description").text = description_text
    return channel


def write_feed(xml_file: str, channel_title: str, channel_link: str, articles: List[Dict]) -> Tuple[int, int]:
    tree, root = load_or_create_tree(xml_file)
    channel = ensure_channel(root, channel_title, channel_link, channel_title)

    existing = set()
    for item in channel.findall("item"):
        link_tag = item.find("link")
        if link_tag is not None and link_tag.text:
            existing.add(link_tag.text.strip())

    new_count = 0
    for art in articles:
        if art["url"] in existing:
            continue
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = art.get("title") or ""
        ET.SubElement(item, "link").text = art.get("url") or ""
        ET.SubElement(item, "description").text = art.get("desc") or ""
        pub_rfc = None
        if art.get("pub"):
            pub_rfc = try_parse_rfc822(art["pub"])
        if not pub_rfc:
            pub_rfc = datetime.utcnow().replace(tzinfo=timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
        ET.SubElement(item, "pubDate").text = pub_rfc
        img = art.get("img") or ""
        if img:
            ctype, _ = mimetypes.guess_type(img)
            if not ctype:
                ctype = "image/jpeg"
            ET.SubElement(item, "enclosure", {"url": img, "type": ctype})
        new_count += 1
        existing.add(art["url"])

    items = channel.findall("item")
    if len(items) > MAX_ITEMS:
        to_remove = len(items) - MAX_ITEMS
        for old in items[:to_remove]:
            channel.remove(old)

    try:
        ET.indent(tree, space="  ")
    except Exception:
        pass
    tree.write(xml_file, encoding="utf-8", xml_declaration=True)
    return new_count, len(channel.findall("item"))


# ---- Main workflow ----
def main():
    total_new = 0
    for key, cfg in SOURCES.items():
        html_file = cfg["html"]
        xml_file = cfg["xml"]
        base = cfg["base"]
        url_filter = cfg.get("url_contains")

        articles_collected: List[Dict] = []

        # Special handling for printversion: discover subpages and fetch them
        if key == "printversion":
            if not os.path.exists(html_file):
                print(f"[{key}] required file {html_file} not found; skipping discovery", file=sys.stderr)
            else:
                with open(html_file, "r", encoding="utf-8") as fh:
                    print_html = fh.read()
                subs = extract_print_subcategories(print_html, base)
                # Always attempt to parse printversion.html itself too
                arts_from_main = extract_articles_from_html_string(print_html, base, None)
                for a in arts_from_main:
                    if a["url"] not in {x["url"] for x in articles_collected}:
                        articles_collected.append(a)

                if subs:
                    # fetch and save each subpage
                    for label, href in subs:
                        fname = slugify(label)
                        print(f"[{key}] fetch subpage: {label} -> {href} -> {fname}")
                        html = fetch_html(href)
                        if html:
                            write_file(fname, html)
                            # parse saved file using editorial-like selectors; restrict by path fragment
                            path = urlparse(href).path or None
                            url_contains_fragment = path if path and path != "/" else None
                            parsed = []
                            try:
                                with open(fname, "r", encoding="utf-8") as fh:
                                    parsed = extract_articles_from_html_string(fh.read(), base, url_contains_fragment)
                            except Exception as e:
                                print(f"[{key}] parse error for {fname}: {e}", file=sys.stderr)
                            for a in parsed:
                                if a["url"] not in {x["url"] for x in articles_collected}:
                                    articles_collected.append(a)
                        else:
                            print(f"[{key}] failed to fetch {href}", file=sys.stderr)
                        time.sleep(0.25)
                else:
                    print(f"[{key}] no subcategories discovered in {html_file}", file=sys.stderr)

        else:
            # Non-print sources: parse their provided html files directly
            if not os.path.exists(html_file):
                print(f"[{key}] file {html_file} not found; skipping", file=sys.stderr)
                # continue to next source
            else:
                with open(html_file, "r", encoding="utf-8") as fh:
                    html = fh.read()
                arts = extract_articles_from_html_string(html, base, url_filter)
                # If nothing found with primary selectors, attempt link-overlay catch-all
                if not arts:
                    arts = extract_articles_from_html_string(html, base, url_filter)
                for a in arts:
                    if a["url"] not in {x["url"] for x in articles_collected}:
                        articles_collected.append(a)

        print(f"[{key}] collected {len(articles_collected)} unique articles to consider")

        # Write feed (adds only new items)
        channel_title = "Daily Sun " + key.replace("-", " ").title()
        channel_link = urljoin(base, url_filter or ("/" if key == "printversion" else "/"))
        new_count, total_items = write_feed(xml_file, channel_title, channel_link, articles_collected)
        print(f"[{key}] added {new_count} new articles; total in {xml_file}: {total_items}")
        total_new += new_count

    print(f"Total new articles added across all feeds: {total_new}")


if __name__ == "__main__":
    main()