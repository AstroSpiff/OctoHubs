#!/usr/bin/env python3
import argparse
import sys

from core.config_manager import _ensure_db_backend, load_config
from core.storage import StorageError


def main() -> int:
    parser = argparse.ArgumentParser(description="Pulisce i risultati di ricerca salvati nel DB.")
    parser.add_argument(
        "--scan",
        action="store_true",
        help="Pulisce i risultati di Ricerche & Riepilogo (scan_results).",
    )
    parser.add_argument(
        "--manual",
        action="store_true",
        help="Pulisce lo storico Ricerca Indipendente (manual_search_history).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Pulisce sia scan_results che manual_search_history (default).",
    )
    parser.add_argument(
        "--keep-last",
        type=int,
        default=0,
        help="Mantiene gli ultimi N risultati per ogni categoria.",
    )

    args = parser.parse_args()

    if not (args.scan or args.manual or args.all):
        args.all = True

    config, is_valid = load_config()
    if not is_valid or not config:
        print("Config non valida o mancante.")
        return 1

    try:
        backend = _ensure_db_backend()
    except StorageError as exc:
        print(f"Errore backend DB: {exc}")
        return 1

    keep_last = max(0, int(args.keep_last or 0))
    deleted_scan = 0
    deleted_manual = 0

    if args.all or args.scan:
        deleted_scan = backend.delete_scan_results(keep_last=keep_last)
        print(f"Scan results eliminati: {deleted_scan}")
    if args.all or args.manual:
        deleted_manual = backend.delete_manual_searches(keep_last=keep_last)
        print(f"Manual search eliminati: {deleted_manual}")

    if keep_last:
        print(f"Tenuti gli ultimi {keep_last} elementi per categoria.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
