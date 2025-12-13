#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unified parser that ensures printversion subpages are parsed completely
(no url-fragment filtering). Keeps other XMLs (opinion/editorial/todays-news)
behaviour intact and only appends NEW articles to each XML.
"""

from __future__ import annotations
import os, re, sys, time, mimetypes
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET

# CONFIG
BASE = "https://www.daily-sun.com"
MAX_ITEMS = 500
FETCH_TIMEOUT = 30
FLARESOLVERR_URL = os.environ.get("FLARESOLVERR_URL")  # optional; if set, used
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DailySunParser/1.0)"}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)

SOURCES = {
    "opinion":      {"html": "opinion.html",      "xml": "opinion.xml",      "url_contains": "/opinion/"},
    "editorial":    {"html": "editorial.html",    "xml": "editorial.xml",    "url_contains": "/editorial/"},
    "printversion": {"html": "printversion.html", "xml": "printversion.xml", "url_contains": None},  # subpages used
    "todays-news":  {"html": "todays-news.html",  "xml": "todays-news.xml",  "url_contains": None},
}


# ---------- utilities ----------
def slugify(text: str) -> str:
    s = text.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return (s or "subpage") + ".html"


def _abs(base: str, href: Optional[str]) -> str:
    if not href:
        return ""
    return urljoin(base, href.strip())


def fetch_via_flaresolverr(url: str) -> Optional[str]:
    try:
        payload = {"cmd": "request.get", "url": url, "maxTimeout": 60000}
        r = SESSION.post(FLARESOLVERR_URL, json=payload, timeout=FETCH_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        sol = data.get("solution")
        if sol and "response" in sol:
            return sol["response"]
    except Exception as e:
        print(f"[flaresolverr] fail {url}: {e}", file=sys.stderr)
    return None


def fetch_via_requests(url: str) -> Optional[str]:
    try:
        r = SESSION.get(url, timeout=FETCH_TIMEOUT)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        return r.text
    except Exception as e:
        print(f"[requests] fail {url}: {e}", file=sys.stderr)
        return None


def fetch_html(url: str) -> Optional[str]:
    if FLARESOLVERR_URL:
        html = fetch_via_flaresolverr(url)
        if html:
            return html
    return fetch_via_requests(url)


def save_file(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


# ---------- parsing helpers ----------
def _pick_image_url(img_tag, base: str) -> str:
    if not img_tag:
        return ""
    src = img_tag.get("data-src") or img_tag.get("data-original") or img_tag.get("src") or ""
    return urljoin(base, src) if src else ""


def _pick_title(container) -> str:
    if not container:
        return ""
    sels = [".title26Latest", ".title10", ".title1", ".desktopSectionTitle", ".desktopCategoryTitle",
            ".title1_7", ".title26"]
    for sel in sels:
        el = container.select_one(sel)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)
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
    if not container:
        return ""
    for cls in ("desktopSummary", "summary", "CatDesc", "desktopSubTitle"):
        p = container.find("p", class_=cls)
        if p and p.get_text(strip=True):
            return p.get_text(strip=True)
    p = container.find("p")
    return p.get_text(strip=True) if p and p.get_text(strip=True) else ""


def _pick_pub(container) -> str:
    if not container:
        return ""
    for cls in ("desktopTime", "publishTime", "time", "title1_7"):
        el = container.find(class_=cls)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)
    span = container.find("span", class_=lambda c: c and "paddingR8" in c)
    return span.get_text(strip=True) if span and span.get_text(strip=True) else ""


def try_parse_rfc822(txt: str) -> Optional[str]:
    if not txt:
        return None
    s = txt.strip()
    if "ago" in s:
        return None
    s = s.replace("\u00A0", " ").strip()
    fmts = ["%d %b %Y, %I:%M %p", "%d %b %Y, %H:%M"]
    from datetime import datetime
    for f in fmts:
        try:
            dt = datetime.strptime(s, f)
            dt = dt.replace(tzinfo=timezone.utc)
            return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")
        except Exception:
            continue
    return None


# ---------- article extraction ----------
def extract_articles_from_html_string(html: str, base: str, url_contains: Optional[str]) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    collected: List[Dict] = []

    # main list blocks
    for block in soup.select("div.media.positionRelative, div.media"):
        link = block.select_one("a.linkOverlay") or block.find("a", href=True)
        if not link or not link.get("href"):
            continue
        url = _abs(base, link.get("href"))
        # IMPORTANT: when url_contains is provided, keep it only for non-print page flows
        if url_contains and url_contains not in url:
            continue
        title = _pick_title(block) or link.get_text(strip=True)
        if not title:
            continue
        desc = _pick_description(block)
        pub = _pick_pub(block)
        img = _pick_image_url(block.find("img"), base)
        collected.append({"url": url, "title": title, "desc": desc, "pub": pub, "img": img})

    # lead blocks
    for lead in soup.select(".desktopSectionLead, .DCatLead, .Catcards"):
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

    # catch-all: anchors with linkOverlay
    for link in soup.select("a.linkOverlay[href]"):
        url = _abs(base, link.get("href"))
        if url_contains and url_contains not in url:
            continue
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

    # dedupe preserve first seen
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


# ---------- print subcategory discovery ----------
def extract_print_subcategories(print_html: str, base: str) -> List[Tuple[str, str]]:
    soup = BeautifulSoup(print_html, "html.parser")
    container = soup.select_one(".desktopSubCategoryDiv")
    out: List[Tuple[str, str]] = []
    if not container:
        return out
    for a in container.select("ul li a[href]"):
        label = a.get_text(strip=True)
        href = a.get("href").strip()
        out.append((label, _abs(base, href)))
    return out


# ---------- XML helpers ----------
def load_or_create_tree(xml_file: str):
    if os.path.exists(xml_file):
        try:
            tree = ET.parse(xml_file)
            return tree, tree.getroot()
        except ET.ParseError:
            pass
    root = ET.Element("rss", {"version": "2.0"})
    tree = ET.ElementTree(root)
    return tree, root


def ensure_channel(root, title_text: str, link_text: str, description_text: str):
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
        pub_rfc = try_parse_rfc822(art.get("pub") or "")
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
        # remove oldest
        remove_count = len(items) - MAX_ITEMS
        for old in items[:remove_count]:
            channel.remove(old)

    try:
        ET.indent(tree, space="  ")
    except Exception:
        pass
    tree.write(xml_file, encoding="utf-8", xml_declaration=True)
    return new_count, len(channel.findall("item"))


# ---------- main ----------
def main():
    total_new = 0
    for key, cfg in SOURCES.items():
        html_file = cfg["html"]
        xml_file = cfg["xml"]
        url_contains = cfg.get("url_contains")
        base = cfg.get("base", BASE)

        collected: List[Dict] = []

        # special: printversion -> discover subpages and ensure they are parsed fully
        if key == "printversion":
            if not os.path.exists(html_file):
                print(f"[printversion] missing {html_file}, skipping", file=sys.stderr)
            else:
                with open(html_file, "r", encoding="utf-8") as fh:
                    main_html = fh.read()
                # parse main page as well
                articles_main = extract_articles_from_html_string(main_html, base, None)
                for a in articles_main:
                    if a["url"] not in {x["url"] for x in collected}:
                        collected.append(a)

                subs = extract_print_subcategories(main_html, base)
                if subs:
                    for label, href in subs:
                        fname = slugify(label)
                        # if local file exists use it; otherwise try to fetch and save
                        if os.path.exists(fname):
                            try:
                                with open(fname, "r", encoding="utf-8") as fh:
                                    sub_html = fh.read()
                            except Exception as e:
                                print(f"[printversion] cannot read {fname}: {e}", file=sys.stderr)
                                sub_html = None
                        else:
                            sub_html = fetch_html(href)
                            if sub_html:
                                try:
                                    save_file = fname
                                    with open(save_file, "w", encoding="utf-8") as fh:
                                        fh.write(sub_html)
                                except Exception as e:
                                    print(f"[printversion] failed to save {fname}: {e}", file=sys.stderr)

                        if not sub_html:
                            print(f"[printversion] no html for {label} ({href})", file=sys.stderr)
                            continue

                        # IMPORTANT: do NOT apply url_contains filtering for subpage parsing.
                        sub_articles = extract_articles_from_html_string(sub_html, base, url_contains=None)
                        for a in sub_articles:
                            if a["url"] not in {x["url"] for x in collected}:
                                collected.append(a)

                        # polite pause
                        time.sleep(0.2)
                else:
                    print("[printversion] no subcategories found; parsed main only", file=sys.stderr)

        else:
            # other sources: parse local html if exists
            if not os.path.exists(html_file):
                print(f"[{key}] missing {html_file}, skipping", file=sys.stderr)
            else:
                with open(html_file, "r", encoding="utf-8") as fh:
                    html = fh.read()
                arts = extract_articles_from_html_string(html, base, url_contains)
                for a in arts:
                    if a["url"] not in {x["url"] for x in collected}:
                        collected.append(a)

        print(f"[{key}] collected {len(collected)} unique articles to consider")

        new_count, total_items = write_feed(xml_file, "Daily Sun " + key.replace("-", " ").title(),
                                           urljoin(base, (url_contains or "/")), collected)
        print(f"[{key}] added {new_count} new articles; total in {xml_file}: {total_items}")
        total_new += new_count

    print(f"Total new articles added across all feeds: {total_new}")


if __name__ == "__main__":
    main()