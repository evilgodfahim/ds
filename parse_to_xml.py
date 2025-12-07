import sys
import os
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from datetime import datetime

HTML_FILE = "opinion.html"
XML_FILE = "articles.xml"
MAX_ITEMS = 500

# Load HTML
if not os.path.exists(HTML_FILE):
    print("HTML not found")
    sys.exit(1)

with open(HTML_FILE, "r", encoding="utf-8") as f:
    soup = BeautifulSoup(f.read(), "html.parser")

articles = []
seen_urls = set()

# --- Strategy 1: Find all <a> tags with opinion URLs ---
for link in soup.find_all("a", href=True):
    url = link.get("href", "")
    
    # Filter for opinion articles
    if "/opinion/" not in url or url in seen_urls:
        continue
    
    seen_urls.add(url)
    
    # Try to find title from various heading tags
    title = None
    desc = ""
    pub = ""
    img = ""
    
    # Look for title in the link itself or parent container
    h1 = link.find("h1")
    h2 = link.find("h2")
    h3 = link.find("h3")
    
    if h1:
        title = h1.get_text(strip=True)
    elif h2:
        title = h2.get_text(strip=True)
    elif h3:
        title = h3.get_text(strip=True)
    
    # If no title in link, check parent media or container
    if not title:
        parent = link.find_parent("div", class_=["media", "Catcards", "DCatLead"])
        if parent:
            for heading in parent.find_all(["h1", "h2", "h3"]):
                title = heading.get_text(strip=True)
                if title:
                    break
    
    # Skip if no title found
    if not title:
        continue
    
    # Find description
    parent_container = link.find_parent(["div", "article"])
    if parent_container:
        # Look for description in various classes
        desc_tag = parent_container.find("p", class_=["desktopSummary", "CatDesc", "summary"])
        if desc_tag:
            desc = desc_tag.get_text(strip=True)
        
        # Look for publication date
        pub_tag = parent_container.find(class_=["desktopTime", "publishTime", "time"])
        if pub_tag:
            pub = pub_tag.get_text(strip=True)
        
        # Look for image
        img_tag = parent_container.find("img")
        if img_tag:
            img = img_tag.get("src", "")
    
    articles.append({
        "url": url,
        "title": title,
        "desc": desc,
        "pub": pub,
        "img": img
    })

# --- Strategy 2: Target specific structural patterns ---
# Pattern 1: media positionRelative with linkOverlay
for media_div in soup.find_all("div", class_="media"):
    link = media_div.find("a", class_="linkOverlay")
    if not link:
        continue
    
    url = link.get("href", "")
    if not url or url in seen_urls or "/opinion/" not in url:
        continue
    
    seen_urls.add(url)
    
    # Extract title
    title = None
    for heading in media_div.find_all(["h1", "h2", "h3"]):
        title = heading.get_text(strip=True)
        if title:
            break
    
    if not title:
        continue
    
    # Extract description
    desc = ""
    desc_tag = media_div.find("p", class_=["desktopSummary", "summary"])
    if desc_tag:
        desc = desc_tag.get_text(strip=True)
    
    # Extract publication date
    pub = ""
    pub_tag = media_div.find(class_=["desktopTime", "publishTime"])
    if pub_tag:
        pub = pub_tag.get_text(strip=True)
    
    # Extract image
    img = ""
    img_tag = media_div.find("img")
    if img_tag:
        img = img_tag.get("src", "")
    
    articles.append({
        "url": url,
        "title": title,
        "desc": desc,
        "pub": pub,
        "img": img
    })

# Remove duplicates based on URL
unique_articles = []
final_urls = set()
for art in articles:
    if art["url"] not in final_urls:
        final_urls.add(art["url"])
        unique_articles.append(art)

articles = unique_articles

print(f"Found {len(articles)} unique articles")

# --- Load or create XML ---
if os.path.exists(XML_FILE):
    try:
        tree = ET.parse(XML_FILE)
        root = tree.getroot()
    except ET.ParseError:
        root = ET.Element("rss", version="2.0")
        tree = ET.ElementTree(root)
else:
    root = ET.Element("rss", version="2.0")
    tree = ET.ElementTree(root)

# Ensure channel exists
channel = root.find("channel")
if channel is None:
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = "Daily Sun Opinion"
    ET.SubElement(channel, "link").text = "https://www.daily-sun.com/opinion"
    ET.SubElement(channel, "description").text = "Latest opinion articles from Daily Sun"

# Deduplicate existing URLs
existing = set()
for item in channel.findall("item"):
    link_tag = item.find("link")
    if link_tag is not None and link_tag.text:
        existing.add(link_tag.text.strip())

# Append new unique articles
new_count = 0
for art in articles:
    if art["url"] in existing:
        continue
    
    item = ET.SubElement(channel, "item")
    ET.SubElement(item, "title").text = art["title"]
    ET.SubElement(item, "link").text = art["url"]
    ET.SubElement(item, "description").text = art["desc"]
    
    # Handle publication date
    if art["pub"]:
        ET.SubElement(item, "pubDate").text = art["pub"]
    else:
        ET.SubElement(item, "pubDate").text = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")
    
    if art["img"]:
        ET.SubElement(item, "enclosure", url=art["img"], type="image/jpeg")
    
    new_count += 1

print(f"Added {new_count} new articles to XML")

# Trim to last MAX_ITEMS
all_items = channel.findall("item")
if len(all_items) > MAX_ITEMS:
    for old_item in all_items[:-MAX_ITEMS]:
        channel.remove(old_item)
    print(f"Trimmed to {MAX_ITEMS} items")

# Format and save XML
ET.indent(tree, space="  ")
tree.write(XML_FILE, encoding="utf-8", xml_declaration=True)

print(f"XML saved to {XML_FILE}")
print(f"Total items in feed: {len(channel.findall('item'))}") 
