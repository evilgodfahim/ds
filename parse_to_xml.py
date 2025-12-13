#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Parse Daily Sun saved HTML files to XML (offline only).

- Works strictly on local HTML files; no network fetching.
- Subcategory filtering for printversion is strict and segment-based.
- Only articles under valid subcategory paths are accepted.
- Existing XML files are preserved; only new items are appended.
"""

import os
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
import mimetypes

BASE = "https://www.daily-sun.com"
DOMAIN = "daily-sun.com"
MAX_ITEMS = 500

SOURCES = {
    "opinion": {"html": "opinion.html", "xml": "opinion.xml"},
    "editorial": {"html": "editorial.html", "xml": "editorial.xml"},
    "todays_news": {"html": "todays-news.html", "xml": "todays_news.xml"},
    "business": {"html": "business.html", "xml": "business.xml"},
    "deep_dive": {"html": "deep_dive.html", "xml": "deep_dive.xml"},
    "diplomacy": {"html": "diplomacy.html", "xml": "diplomacy.xml"},
    "printversion": {"html": "printversion.html", "xml": "printversion.xml"},
}


def _abs(base: str, href: str) -> str:
    if not href:
        return ""
    return urljoin(base, href.strip())


def _is_same_domain(url: str) -> bool:
    if not url:
        return False
    try:
        p = urlparse(url)
        return DOMAIN in (p.netloc or "")
    except Exception:
        return False


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

    blocks = soup.select("div.media") + soup.select("div.media.positionRelative") + soup.find_all("article")
    blocks = list(dict.fromkeys(blocks))

    for block in blocks:
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
        collected.append({"url": url, "title": title, "desc": desc, "pub": pub, "img": img})

    for a in soup.find_all("a", href=True):
        href = a["href"]
        url = _abs(BASE, href)
        if not _is_same_domain(url):
            continue
        title = a.get_text(strip=True)
        if not title or len(title.split()) <= 3:
            continue
        collected.append({"url": url, "title": title, "desc": "", "pub": "", "img": ""})

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
        for old in items[: len(items) - MAX_ITEMS]:
            channel.remove(old)

    try:
        ET.indent(tree, space="  ")
    except Exception:
        pass
    tree.write(xml_file, encoding="utf-8", xml_declaration=True)
    return new_count, len(channel.findall("item"))


def normalize_path_from_href(href: str) -> str:
    if not href:
        return ""
    href = href.strip()
    if href.lower().startswith("javascript:") or href.startswith("#"):
        return ""
    parsed = urlparse(href)
    path = parsed.path or href
    if not path:
        return ""
    path = re.sub(r"/+", "/", path)
    path = path.rstrip("/")
    if path == "":
        return "/"
    if not path.startswith("/"):
        path = "/" + path
    return path


def path_segments(path: str):
    if not path or path == "/":
        return []
    return [seg for seg in path.split("/") if seg]


def matches_printversion_url_pattern(url: str, subcategory_href: str) -> bool:
    if not url or not subcategory_href:
        return False
    sub_path = normalize_path_from_href(subcategory_href)
    if not sub_path or sub_path == "/":
        return False
    try:
        u = urlparse(url)
        url_path = u.path or ""
    except Exception:
        return False
    url_path = re.sub(r"/+", "/", url_path).rstrip("/")
    if url_path == "":
        url_path = "/"
    sub_segs = path_segments(sub_path)
    url_segs = path_segments(url_path)
    if not sub_segs:
        return False
    if len(url_segs) < len(sub_segs):
        return False
    return url_segs[: len(sub_segs)] == sub_segs


def main():
    total_new = 0
    for key, cfg in SOURCES.items():
        html_files = [cfg["html"]]
        subcategory_hrefs = {}

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
                    norm = normalize_path_from_href(href)
                    if not norm or norm == "/":
                        continue
                    html_files.append(sub_html)
                    subcategory_hrefs[sub_html] = href

        articles_collected = []
        seen_urls = set()

        for html_file in html_files:
            if not os.path.exists(html_file):
                print(f"[{key}] no html for {html_file}")
                continue
            with open(html_file, "r", encoding="utf-8") as fh:
                html = fh.read()
            arts = extract_articles_from_html_string(html)

            if key == "printversion":
                filtered = []
                sub_hrefs = list(subcategory_hrefs.values())
                for a in arts:
                    url = a.get("url", "")
                    if not url or not _is_same_domain(url):
                        continue
                    matched = False
                    for sh in sub_hrefs:
                        if matches_printversion_url_pattern(url, sh):
                            matched = True
                            break
                    if html_file in subcategory_hrefs and matches_printversion_url_pattern(url, subcategory_hrefs[html_file]):
                        matched = True
                    if matched:
                        filtered.append(a)
                arts = filtered
            else:
                arts = [a for a in arts if a.get("url") and _is_same_domain(a.get("url"))]

            for a in arts:
                u = a.get("url")
                if not u:
                    continue
                if u in seen_urls:
                    continue
                seen_urls.add(u)
                articles_collected.append(a)

        print(f"[{key}] collected {len(articles_collected)} unique articles to consider")
        channel_title = "Daily Sun " + key.replace("_", " ").title()
        channel_link = BASE + "/"
        new_count, total_items = write_feed(cfg["xml"], channel_title, channel_link, articles_collected)
        print(f"[{key}] added {new_count} new articles; total in {cfg['xml']}: {total_items}")
        total_new += new_count

    print(f"Total new articles added across all feeds: {total_new}")


if __name__ == "__main__":
    main()