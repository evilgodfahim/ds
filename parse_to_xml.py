#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Parse Daily Sun saved HTML files to XML.

- Fully matches your repo HTML filenames.
- All subcategory HTMLs for printversion are included dynamically.
- Only new articles are added.
- Existing XMLs are preserved.
- Strict URL filtering for printversion subcategories.
"""

import os
import re
from datetime import datetime, timezone
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
import mimetypes

BASE = "https://www.daily-sun.com"
MAX_ITEMS = 500

# Map source keys to html and xml files
SOURCES = {
    "opinion": {"html": "opinion.html", "xml": "opinion.xml"},
    "editorial": {"html": "editorial.html", "xml": "editorial.xml"},
    "todays_news": {"html": "todays-news.html", "xml": "todays_news.xml"},
    "business": {"html": "business.html", "xml": "business.xml"},
    "deep_dive": {"html": "deep_dive.html", "xml": "deep_dive.xml"},
    "diplomacy": {"html": "diplomacy.html", "xml": "diplomacy.xml"},
    "printversion": {"html": "printversion.html", "xml": "printversion.xml"},
}


# --- Utilities ---
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


def _pick_pub(container) -> str:
    if container is None:
        return ""
    for cls in ("desktopTime", "publishTime", "time", "title1_7"):
        el = container.find(class_=cls)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)
    return ""


def try_parse_rfc822(pub_text: str) -> str:
    if not pub_text:
        return None
    s = pub_text.replace("\u00A0", " ").strip()
    formats = [
        "%d %b %Y, %I:%M %p",
        "%d %b %Y, %H:%M",
        "%d %b %Y %I:%M %p",
        "%d %b %Y %H:%M",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(s, fmt)
            dt = dt.replace(tzinfo=timezone.utc)
            return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")
        except Exception:
            continue
    return None


def extract_articles_from_html_string(html: str) -> list:
    soup = BeautifulSoup(html, "html.parser")
    collected = []

    for block in soup.select("div.media, div.media.positionRelative"):
        link = block.find("a", href=True)
        if not link:
            continue
        url = _abs(BASE, link["href"])
        title = _pick_title(block) or link.get_text(strip=True)
        if not title:
            continue
        desc = _pick_description(block)
        pub = _pick_pub(block)
        img = _pick_image_url(block.find("img"), BASE)
        collected.append(
            {"url": url, "title": title, "desc": desc, "pub": pub, "img": img}
        )

    for a in soup.find_all("a", href=True):
        url = _abs(BASE, a["href"])
        title = a.get_text(strip=True)
        if not title or len(title.split()) <= 3:
            continue
        collected.append(
            {"url": url, "title": title, "desc": "", "pub": "", "img": ""}
        )

    seen = set()
    unique = []
    for a in collected:
        if a["url"] not in seen:
            seen.add(a["url"])
            unique.append(a)
    return unique


def load_or_create_tree(xml_file: str):
    if os.path.exists(xml_file):
        try:
            tree = ET.parse(xml_file)
            root = tree.getroot()
            return tree, root
        except ET.ParseError:
            pass
    root = ET.Element("rss", {"version": "2.0"})
    tree = ET.ElementTree(root)
    return tree, root


def ensure_channel(root, title_text, link_text, description_text):
    channel = root.find("channel")
    if channel is None:
        channel = ET.SubElement(root, "channel")
        ET.SubElement(channel, "title").text = title_text
        ET.SubElement(channel, "link").text = link_text
        ET.SubElement(channel, "description").text = description_text
    return channel


def write_feed(xml_file, channel_title, channel_link, articles):
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
        pub_rfc = try_parse_rfc822(art.get("pub"))
        if not pub_rfc:
            pub_rfc = (
                datetime.utcnow()
                .replace(tzinfo=timezone.utc)
                .strftime("%a, %d %b %Y %H:%M:%S +0000")
            )
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
        for old in items[: len(items) - MAX_ITEMS]:
            channel.remove(old)

    try:
        ET.indent(tree, space="  ")
    except Exception:
        pass
    tree.write(xml_file, encoding="utf-8", xml_declaration=True)
    return new_count, len(channel.findall("item"))


def matches_printversion_url_pattern(url: str, subcategory_href: str) -> bool:
    """
    Check if URL STRICTLY contains the subcategory path from the href.
    Extracts the path segment from href and checks if it appears in the article URL.
    
    Examples:
        href="/front-page" -> checks for "/front-page/" in URL
        href="https://www.daily-sun.com/metropolis" -> checks for "/metropolis/" in URL
        href="/my-districts" -> checks for "/my-districts/" in URL
    """
    if not subcategory_href:
        return False
    
    # Extract path from href (remove domain if present, get the path part)
    path = subcategory_href.strip()
    
    # Remove query parameters
    path = path.split('?')[0]
    
    # If it contains the domain, extract just the path
    if 'daily-sun.com' in path:
        parts = path.split('daily-sun.com/')
        if len(parts) > 1:
            path = '/' + parts[-1]
        else:
            path = '/'
    
    # Ensure path starts and ends with /
    if not path.startswith('/'):
        path = '/' + path
    if not path.endswith('/'):
        path = path + '/'
    
    # STRICT check: path must be present in URL
    return path.lower() in url.lower()


def main():
    total_new = 0
    for key, cfg in SOURCES.items():
        html_files = [cfg["html"]]
        subcategory_hrefs = {}  # Map html_file to href path for printversion

        if key == "printversion":
            if os.path.exists(cfg["html"]):
                with open(cfg["html"], "r", encoding="utf-8") as fh:
                    soup = BeautifulSoup(fh.read(), "html.parser")
                subcats = soup.select(".desktopSubCategoryDiv li a")
                for link in subcats:
                    label = link.get_text(strip=True)
                    href = link.get("href", "")
                    if not label or not href:
                        continue
                    sub_html = re.sub(r"\W+", "_", label.lower()) + ".html"
                    html_files.append(sub_html)
                    subcategory_hrefs[sub_html] = href

        articles_collected = []

        for html_file in html_files:
            if not os.path.exists(html_file):
                print(f"[{key}] no html for {html_file}")
                continue
            with open(html_file, "r", encoding="utf-8") as fh:
                html = fh.read()
            arts = extract_articles_from_html_string(html)
            
            # Filter articles for printversion subcategories - STRICT matching only
            if key == "printversion" and html_file in subcategory_hrefs:
                subcat_href = subcategory_hrefs[html_file]
                filtered_arts = []
                for a in arts:
                    if matches_printversion_url_pattern(a["url"], subcat_href):
                        filtered_arts.append(a)
                arts = filtered_arts
            
            for a in arts:
                if a["url"] not in {x["url"] for x in articles_collected}:
                    articles_collected.append(a)

        print(f"[{key}] collected {len(articles_collected)} unique articles to consider")

        channel_title = "Daily Sun " + key.replace("_", " ").title()
        channel_link = BASE + "/"
        new_count, total_items = write_feed(
            cfg["xml"], channel_title, channel_link, articles_collected
        )
        print(f"[{key}] added {new_count} new articles; total in {cfg['xml']}: {total_items}")
        total_new += new_count

    print(f"Total new articles added across all feeds: {total_new}")


if __name__ == "__main__":
    main()