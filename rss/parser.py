from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from core.utils import _parse_date_value


def _strip_xml_tag(tag):
    if not tag:
        return ""
    return tag.split("}")[-1].lower()


def _extract_first_text(element, tag_names):
    for node in element.iter():
        if _strip_xml_tag(node.tag) in tag_names and node.text:
            text = node.text.strip()
            if text:
                return text
    return ""


def _extract_link_value(item):
    for node in item:
        if _strip_xml_tag(node.tag) != "link":
            continue
        href = node.attrib.get("href") if hasattr(node, "attrib") else None
        rel = node.attrib.get("rel") if hasattr(node, "attrib") else None
        if href and (not rel or rel == "alternate"):
            return href
        if node.text:
            return node.text.strip()
    return ""


def _inspect_rss_content(xml_bytes, sample_limit=5):
    root = ET.fromstring(xml_bytes)
    root_tag = _strip_xml_tag(root.tag)
    feed_type = "rss"
    channel = None
    items = []
    if root_tag == "feed":
        feed_type = "atom"
        channel = root
        items = list(root.findall(".//{*}entry"))
    else:
        channel = root.find(".//{*}channel") or root
        items = list(root.findall(".//{*}item"))

    channel_title = _extract_first_text(channel, {"title"})
    channel_link = _extract_first_text(channel, {"link"})
    channel_desc = _extract_first_text(channel, {"description", "subtitle"})

    results = []
    fields = set()
    for item in items[:sample_limit]:
        item_fields = {_strip_xml_tag(child.tag) for child in item}
        fields.update(item_fields)
        results.append({
            "title": _extract_first_text(item, {"title"}),
            "link": _extract_link_value(item) or _extract_first_text(item, {"link"}),
            "guid": _extract_first_text(item, {"guid", "id"}),
            "published": _extract_first_text(item, {"pubdate", "published", "updated", "date"}),
            "author": _extract_first_text(item, {"author", "creator"})
        })

    return {
        "feed_type": feed_type,
        "channel": {
            "title": channel_title,
            "link": channel_link,
            "description": channel_desc
        },
        "item_count": len(items),
        "fields": sorted(fields),
        "items": results
    }


def _parse_epoch_value(value):
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    if number > 10**14:
        number = number / 1_000_000
    elif number > 10**11:
        number = number / 1_000
    return datetime.fromtimestamp(number, tz=timezone.utc)


def _parse_rss_date(value):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return _parse_epoch_value(text)
    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError):
        dt = None
    if dt is None:
        return _parse_date_value(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _extract_rss_categories(item):
    categories = []
    for node in item.iter():
        if _strip_xml_tag(node.tag) == "category" and node.text:
            value = node.text.strip()
            if value:
                categories.append(value)
    return categories


def _parse_rss_feed(xml_bytes):
    root = ET.fromstring(xml_bytes)
    root_tag = _strip_xml_tag(root.tag)
    feed_type = "rss"
    channel = None
    entries = []
    if root_tag == "feed":
        feed_type = "atom"
        channel = root
        entries = list(root.findall(".//{*}entry"))
    else:
        channel = root.find(".//{*}channel") or root
        entries = list(root.findall(".//{*}item"))

    channel_title = _extract_first_text(channel, {"title"})
    channel_link = _extract_link_value(channel) or _extract_first_text(channel, {"link"})
    channel_desc = _extract_first_text(channel, {"description", "subtitle"})

    items = []
    for entry in entries:
        title = _extract_first_text(entry, {"title"})
        link = _extract_link_value(entry) or _extract_first_text(entry, {"link"})
        guid = _extract_first_text(entry, {"guid", "id"})
        if not link and guid:
            link = guid
        author = _extract_first_text(entry, {"author", "creator", "name"})
        summary = _extract_first_text(entry, {"summary", "description"})
        content = _extract_first_text(entry, {"content", "encoded"})
        if not summary and content:
            summary = content
        published_text = _extract_first_text(entry, {"pubdate", "published", "updated", "date"})
        updated_text = _extract_first_text(entry, {"updated", "modified"})
        published_at = _parse_rss_date(published_text)
        updated_at = _parse_rss_date(updated_text) or _parse_rss_date(published_text)
        categories = _extract_rss_categories(entry)
        raw_xml = ET.tostring(entry, encoding="unicode")
        items.append({
            "title": title or None,
            "link": link or None,
            "guid": guid or None,
            "author": author or None,
            "summary": summary or None,
            "content": content or None,
            "categories": categories or None,
            "published_at": published_at,
            "updated_at": updated_at,
            "extra": {
                "feed_type": feed_type,
                "raw": raw_xml
            }
        })

    return {
        "feed_type": feed_type,
        "channel": {
            "title": channel_title,
            "link": channel_link,
            "description": channel_desc
        },
        "items": items
    }


def _extract_json_link(item):
    for key in ("canonical", "alternate"):
        value = item.get(key)
        if isinstance(value, list):
            for entry in value:
                if isinstance(entry, dict) and entry.get("href"):
                    return entry["href"]
        elif isinstance(value, dict) and value.get("href"):
            return value["href"]
    origin = item.get("origin")
    if isinstance(origin, dict):
        if origin.get("htmlUrl"):
            return origin["htmlUrl"]
    return ""


def _extract_json_summary(item):
    summary = item.get("summary")
    if isinstance(summary, dict):
        return summary.get("content") or ""
    if isinstance(summary, str):
        return summary
    return ""


def _extract_json_source(origin):
    if not isinstance(origin, dict):
        return "", "", ""
    source_title = origin.get("title") or ""
    source_url = origin.get("htmlUrl") or ""
    stream_id = origin.get("streamId") or ""
    if not source_url and isinstance(stream_id, str) and stream_id.startswith("feed/"):
        source_url = stream_id[5:]
    return source_title, source_url, stream_id


def _parse_json_import(payload):
    items = []
    candidates = []
    if isinstance(payload, list):
        candidates = payload
    elif isinstance(payload, dict):
        for key in ("items", "entries", "results", "data"):
            entry = payload.get(key)
            if isinstance(entry, list):
                candidates = entry
                break
    for entry in candidates:
        if not isinstance(entry, dict):
            continue
        origin = entry.get("origin") if isinstance(entry.get("origin"), dict) else {}
        source_title, source_url, stream_id = _extract_json_source(origin)
        summary = _extract_json_summary(entry)
        link = _extract_json_link(entry)
        published_at = _parse_epoch_value(entry.get("published"))
        updated_at = _parse_epoch_value(entry.get("updated")) or _parse_epoch_value(entry.get("crawlTimeMsec"))
        if updated_at is None:
            updated_at = _parse_epoch_value(entry.get("timestampUsec"))
        categories = entry.get("categories")
        if not isinstance(categories, list):
            categories = []
        items.append({
            "source_name": source_title or None,
            "source_url": source_url or None,
            "source_tags": [],
            "title": entry.get("title") or None,
            "link": link or None,
            "guid": entry.get("id") or None,
            "author": entry.get("author") or None,
            "summary": summary or None,
            "content": summary or None,
            "categories": categories or None,
            "published_at": published_at,
            "updated_at": updated_at,
            "extra": {
                "origin": origin,
                "stream_id": stream_id,
                "raw": entry
            }
        })
    return items
