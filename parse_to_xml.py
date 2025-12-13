#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
from datetime import datetime, timezone
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
import mimetypes

# -----------------------------
# CONFIG
# -----------------------------
MAX_ITEMS = 500
BASE = "https://www.daily-sun.com"
PRINT_XML = "printversion.xml"

# -----------------------------
# HELPERS
# -----------------------------
def slugify(name: str) -> str:
    """Convert category name to safe filename."""
    return re.sub(r'\W+', '_', name.lower())

def _abs(base: str, href: str) -> str:
    if not href:
        return ""
    if href.startswith("http"):
        return href
    return base.rstrip("/") + "/" + href.lstrip("/")

def _pick_title(container) -> str:
    if container is None:
        return ""
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
    p = container.find("p")
    if p and p.get_text(strip=True):
        return p.get_text(strip=True)
    return ""

def _pick_image_url(img_tag, base: str) -> str:
    if img_tag is None:
        return ""
    url = img_tag.get("data-src") or img_tag.get("src") or ""
    return _abs(base, url)

def try_parse_rfc822(pub_text: str) -> str:
    """Return RFC822 formatted date or empty string."""
    try:
        dt = datetime.utcnow().replace(tzinfo=timezone.utc)
        return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")
    except Exception:
        return ""

def extract_articles_from_html(html_file: str) -> list:
    if not os.path.exists(html_file):
        print(f"[!] no html for {html_file}")
        return []
    with open(html_file, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    collected = []

    # div.media blocks
    for block in soup.select("div.media, div.media.positionRelative"):
        link = block.find("a", href=True)
        if not link:
            continue
        url = _abs(BASE, link["href"])
        title = _pick_title(block)
        if not title:
            continue
        desc = _pick_description(block)
        img = _pick_image_url(block.find("img"), BASE)
        pub = ""  # optional parsing from block
        collected.append({"url": url, "title": title, "desc": desc, "img": img, "pub": pub})

    return collected

# -----------------------------
# XML Helpers
# -----------------------------
def load_or_create_tree(xml_file: str):
    if os.path.exists(xml_file):
        try:
            tree = ET.parse(xml_file)
            root = tree.getroot()
            return tree, root
        except ET.ParseError:
            print(f"[!] parse error {xml_file}, creating new skeleton")
    root = ET.Element("rss", {"version": "2.0"})
    tree = ET.ElementTree(root)
    return tree, root

def ensure_channel(root: ET.Element) -> ET.Element:
    channel = root.find("channel")
    if channel is None:
        channel = ET.SubElement(root, "channel")
        ET.SubElement(channel, "title").text = "Daily Sun Print Version"
        ET.SubElement(channel, "link").text = BASE + "/printversion"
        ET.SubElement(channel, "description").text = "Latest print version articles from Daily Sun"
    return channel

def write_feed(xml_file: str, articles: list):
    tree, root = load_or_create_tree(xml_file)
    channel = ensure_channel(root)

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
        ET.SubElement(item, "pubDate").text = art.get("pub") or try_parse_rfc822("")
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
        for old in items[:len(items)-MAX_ITEMS]:
            channel.remove(old)

    try:
        ET.indent(tree, space="  ")
    except Exception:
        pass
    tree.write(xml_file, encoding="utf-8", xml_declaration=True)
    return new_count, len(channel.findall("item"))

# -----------------------------
# MAIN LOGIC
# -----------------------------
def main():
    # Collect all printversion HTML files dynamically
    html_files = [f for f in os.listdir(".") if f.endswith(".html") and f != "index.html"]
    articles_all = []
    for html_file in html_files:
        arts = extract_articles_from_html(html_file)
        articles_all.extend(arts)
        print(f"[+] {html_file} collected {len(arts)} articles")

    new_count, total_items = write_feed(PRINT_XML, articles_all)
    print(f"[+] Added {new_count} new articles; total in {PRINT_XML}: {total_items}")

if __name__ == "__main__":
    main()