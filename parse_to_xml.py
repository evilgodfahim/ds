#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Multi-source HTML -> per-source RSS XML exporter.

Creates one XML per source (opinion/editorial/printversion/todays-news).
Parses multiple structural patterns to avoid skipping articles.
"""

import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urljoin
import mimetypes

from bs4 import BeautifulSoup

MAX_ITEMS = 500

SOURCES = {
    "opinion": {
        "html": "opinion.html",
        "xml": "opinion.xml",
        "base": "https://www.daily-sun.com",
        "url_contains": "/opinion/"
    },
    "editorial": {
        "html": "editorial.html",
        "xml": "editorial.xml",
        "base": "https://www.daily-sun.com",
        "url_contains": "/editorial/"
    },
    "printversion": {
        "html": "printversion.html",
        "xml": "printversion.xml",
        "base": "https://www.daily-sun.com",
        "url_contains": None  # accept all (use structural filtering)
    },
    "todays-news": {
        "html": "todays-news.html",
        "xml": "todays-news.xml",
        "base": "https://www.daily-sun.com",
        "url_contains": None
    }
}


def _norm_url(base, href):
    if not href:
        return ""
    return urljoin(base, href.strip())


def _pick_image(img_tag):
    if not img_tag:
        return ""
    return img_tag.get("data-src") or img_tag.get("data-original") or img_tag.get("src") or ""


def _pick_title(container):
    # Look for typical heading classes first, then any h1/h2/h3, then alt text
    if not container:
        return ""
    # common class names seen on Daily Sun
    title_selectors = [
        ".title26Latest", ".title10", ".title1", ".desktopSectionTitle",
        ".desktopCategoryTitle", ".title1_7", ".title26"
    ]
    for sel in title_selectors:
        t = container.select_one(sel)
        if t and t.get_text(strip=True):
            return t.get_text(strip=True)
    for h in container.find_all(["h1", "h2", "h3"]):
        txt = h.get_text(strip=True)
        if txt:
            return txt
    # fallback: link text
    a = container.find("a", href=True)
    if a and a.get_text(strip=True):
        return a.get_text(strip=True)
    # fallback: image alt
    img = container.find("img")
    if img and img.get("alt"):
        return img.get("alt").strip()
    return ""


def _pick_description(container):
    if not container:
        return ""
    for cls in ("desktopSummary", "summary", "CatDesc", "CatcardsDesc"):
        p = container.find("p", class_=cls)
        if p and p.get_text(strip=True):
            return p.get_text(strip=True)
    # fallback: first <p> with text
    p = container.find("p")
    if p and p.get_text(strip=True):
        return p.get_text(strip=True)
    return ""


def _pick_pubdate(container):
    if not container:
        return ""
    # classes seen: desktopTime, publishTime, title1_7
    for cls in ("desktopTime", "publishTime", "time", "title1_7"):
        el = container.find(class_=cls)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)
    # sometimes time is inside a <span> with paddingR8
    span = container.find("span", class_=lambda c: c and "paddingR8" in c)
    if span and span.get_text(strip=True):
        return span.get_text(strip=True)
    return ""


def _try_parse_to_rfc822(pub_text):
    # Try to convert common shapes like: "13 Dec 2025, 10:23 AM" -> RFC822
    # If not parseable, return empty string (we'll fall back to now).
    if not pub_text:
        return ""
    s = pub_text.strip()
    # remove extra words like 'ago' or trailing category
    # If it contains 'ago' - cannot convert reliably, return empty
    if "ago" in s:
        return ""
    # Common format: "13 Dec 2025, 10:23 AM"
    formats = [
        "%d %b %Y, %I:%M %p",
        "%d %b %Y, %H:%M %p",
        "%d %b %Y, %H:%M",
        "%d %b %Y %I:%M %p",
        "%d %b %Y %H:%M"
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(s, fmt)
            # assume local naive -> treat as UTC for feed (or you may change)
            dt = dt.replace(tzinfo=timezone.utc)
            return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")
        except Exception:
            continue
    return ""


def extract_from_media_blocks(soup, base, url_filter):
    """
    Primary extractor: iterate 'div.media' blocks which correspond to list items
    present in editorial / latest / opinion pages.
    """
    out = []
    for block in soup.select("div.media"):
        link = block.select_one("a.linkOverlay")
        if not link or not link.get("href"):
            # sometimes anchor wraps image or title - try first anchor with href
            link = block.find("a", href=True)
            if not link:
                continue
        url = _norm_url(base, link.get("href"))
        if url_filter and url_filter not in url:
            continue

        title = _pick_title(block)
        if not title:
            # skip items with no title (likely not an article)
            continue

        desc = _pick_description(block)
        pub = _pick_pubdate(block)
        img = _pick_image(block.find("img"))

        out.append({
            "url": url,
            "title": title,
            "desc": desc,
            "pub": pub,
            "img": img
        })
    return out


def extract_from_link_overlay_anywhere(soup, base, url_filter):
    """
    Find any <a class="linkOverlay"> anywhere (covers some edge cases)
    and inspect its surrounding container(s).
    """
    out = []
    for link in soup.select("a.linkOverlay"):
        if not link.get("href"):
            continue
        url = _norm_url(base, link.get("href"))
        if url_filter and url_filter not in url:
            continue

        # container heuristics: parent up to 3 levels search for a media-like div
        parent = None
        p = link
        for _ in range(4):
            p = p.parent
            if p is None:
                break
            if getattr(p, "name", "") in ("div", "article"):
                parent = p
                # Prefer containers that contain img or h tags
                if parent.find("img") or parent.find(["h1", "h2", "h3"]):
                    break

        if parent is None:
            parent = link.parent

        title = _pick_title(parent)
        if not title:
            # try link text
            if link.get_text(strip=True):
                title = link.get_text(strip=True)
            else:
                continue

        desc = _pick_description(parent)
        pub = _pick_pubdate(parent)
        img = _pick_image(parent.find("img"))

        out.append({
            "url": url,
            "title": title,
            "desc": desc,
            "pub": pub,
            "img": img
        })
    return out


def extract_from_lead_blocks(soup, base, url_filter):
    """
    Handles lead article blocks e.g. .desktopSectionLead used on printversion
    """
    out = []
    for lead in soup.select(".desktopSectionLead, .DCatLead, .Catcards"):
        # linkOverlay may be at the bottom of the lead block
        link = lead.select_one("a.linkOverlay") or lead.find("a", href=True)
        if not link:
            continue
        url = _norm_url(base, link.get("href"))
        if url_filter and url_filter not in url:
            continue

        title = _pick_title(lead)
        if not title:
            continue

        desc = _pick_description(lead)
        pub = _pick_pubdate(lead)
        img = _pick_image(lead.find("img"))

        out.append({
            "url": url,
            "title": title,
            "desc": desc,
            "pub": pub,
            "img": img
        })
    return out


def extract_all(html_file, base, url_filter):
    if not os.path.exists(html_file):
        return []

    with open(html_file, "r", encoding="utf-8") as fh:
        soup = BeautifulSoup(fh.read(), "html.parser")

    collected = []
    # Strategy order: media blocks (primary), linkOverlay-anywhere (catch-alls), lead blocks (printlead)
    collected.extend(extract_from_media_blocks(soup, base, url_filter))
    collected.extend(extract_from_link_overlay_anywhere(soup, base, url_filter))
    collected.extend(extract_from_lead_blocks(soup, base, url_filter))

    # Normalize and deduplicate by URL, preserving first-seen (which tends to be the best data)
    seen = set()
    unique = []
    for a in collected:
        if not a.get("url"):
            continue
        if a["url"] in seen:
            continue
        seen.add(a["url"])
        # ensure full absolute image URL
        if a.get("img"):
            a["img"] = urljoin(base, a["img"])
        unique.append(a)

    return unique


def ensure_channel(root, title_text, link_text, description_text):
    channel = root.find("channel")
    if channel is None:
        channel = ET.SubElement(root, "channel")
        ET.SubElement(channel, "title").text = title_text
        ET.SubElement(channel, "link").text = link_text
        ET.SubElement(channel, "description").text = description_text
    return channel


def load_or_create_tree(xml_file):
    if os.path.exists(xml_file):
        try:
            tree = ET.parse(xml_file)
            root = tree.getroot()
            return tree, root
        except ET.ParseError:
            pass
    root = ET.Element("rss", version="2.0")
    tree = ET.ElementTree(root)
    return tree, root


def write_feed(xml_file, channel_title, channel_link, articles):
    tree, root = load_or_create_tree(xml_file)
    channel = ensure_channel(root, channel_title, channel_link, channel_title)

    # gather existing URLs
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

        pub_rfc = ""
        if art.get("pub"):
            pub_rfc = _try_parse_to_rfc822(art["pub"])
        if not pub_rfc:
            pub_rfc = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")
        ET.SubElement(item, "pubDate").text = pub_rfc

        img = art.get("img")
        if img:
            ctype, _ = mimetypes.guess_type(img)
            if not ctype:
                ctype = "image/jpeg"
            ET.SubElement(item, "enclosure", {"url": img, "type": ctype})

        new_count += 1

    # Trim to MAX_ITEMS (keep newest at end; remove oldest from start)
    all_items = channel.findall("item")
    if len(all_items) > MAX_ITEMS:
        remove_count = len(all_items) - MAX_ITEMS
        for old_item in all_items[:remove_count]:
            channel.remove(old_item)

    # Pretty indent and write
    try:
        ET.indent(tree, space="  ")
    except Exception:
        # older python may not support indent; ignore
        pass
    tree.write(xml_file, encoding="utf-8", xml_declaration=True)
    return new_count, len(channel.findall("item"))


def main():
    total_new = 0
    for key, cfg in SOURCES.items():
        html_file = cfg["html"]
        xml_file = cfg["xml"]
        base = cfg["base"]
        url_filter = cfg.get("url_contains")

        articles = extract_all(html_file, base, url_filter)

        # If no articles found, still create/ensure XML file skeleton
        channel_title = "Daily Sun " + key.replace("-", " ").title()
        channel_link = urljoin(base, cfg.get("url_contains") or "/")

        new_count, total_items = write_feed(xml_file, channel_title, channel_link, articles)

        print(f"[{key}] found {len(articles)} unique articles, added {new_count} new, total in feed: {total_items}")
        total_new += new_count

    print(f"Total new articles added across all feeds: {total_new}")


if __name__ == "__main__":
    main()