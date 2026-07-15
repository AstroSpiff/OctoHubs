from __future__ import annotations

import traceback

import requests

from rss.db import _ensure_db_backend
from rss.parser import _parse_rss_feed


def _trigger_rss_polling(config):
    """
    Esegue il polling automatico dei feed RSS configurati.

    Args:
        config: Configurazione completa dell'app

    Returns:
        dict: Risultato con statistiche del polling
    """
    print("[RSS_POLLING] Avvio polling automatico feed RSS")

    rss_import = (config or {}).get("RSS_IMPORT") or {}
    if not rss_import.get("ENABLED"):
        print("[RSS_POLLING] RSS Import non abilitato")
        return None

    sources = rss_import.get("SOURCES") or []
    enabled_sources = [s for s in sources if s.get("enabled")]

    if not enabled_sources:
        print("[RSS_POLLING] Nessuna sorgente RSS abilitata")
        return None

    dedup_keep = rss_import.get("DEDUP_KEEP", "newest")

    print(f"[RSS_POLLING] Polling di {len(enabled_sources)} sorgenti RSS")

    all_items = []
    stats = {"total": 0, "success": 0, "failed": 0, "items": 0}

    for source in enabled_sources:
        source_url = source.get("url", "").strip()
        source_name = source.get("name", "").strip() or source_url
        source_tags = source.get("tags") or []

        if not source_url:
            continue

        stats["total"] += 1

        try:
            print(f"[RSS_POLLING] Fetching: {source_name} ({source_url})")

            response = requests.get(source_url, timeout=30)
            response.raise_for_status()

            parsed_feed = _parse_rss_feed(response.content)
            parsed_items = parsed_feed.get("items", []) if isinstance(parsed_feed, dict) else []

            for item in parsed_items:
                if not isinstance(item, dict):
                    print(f"[RSS_POLLING] WARN item non è un dict: {type(item)}")
                    continue

                enriched_item = dict(item)
                enriched_item["source_name"] = source_name
                enriched_item["source_url"] = source_url
                enriched_item["source_tags"] = source_tags
                all_items.append(enriched_item)
            stats["success"] += 1
            stats["items"] += len(parsed_items)

            print(f"[RSS_POLLING] OK {source_name}: {len(parsed_items)} articoli")

        except Exception as exc:
            print(f"[RSS_POLLING] ERR fetch {source_name}: {exc}")
            stats["failed"] += 1

    if all_items:
        try:
            db_settings = (config or {}).get("DATABASE", {})
            backend = _ensure_db_backend(db_settings)
            result = backend.save_rss_items(all_items, dedup_keep=dedup_keep)
            stats["db_inserted"] = result.get("inserted", 0)
            stats["db_updated"] = result.get("updated", 0)
            stats["db_skipped"] = result.get("skipped", 0)
            stats["db_removed"] = result.get("removed", 0)

            print(
                f"[RSS_POLLING] Database: +{result['inserted']} ~{result['updated']} ={result['skipped']} -{result['removed']}"
            )
        except Exception as exc:
            print(f"[RSS_POLLING] Errore salvataggio database: {exc}")
            traceback.print_exc()

    print(
        f"[RSS_POLLING] Completato: {stats['success']}/{stats['total']} sorgenti, {stats['items']} articoli totali"
    )

    return stats
