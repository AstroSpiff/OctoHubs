"""CSV cell hardening for data originating from media servers."""

from __future__ import annotations

from typing import Any
import csv
from datetime import datetime
import tempfile
import time


_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
MAX_PROBE_CSV_EXPORT_ROWS = 50_000
MAX_PROBE_CSV_EXPORT_BYTES = 50 * 1024 * 1024
MAX_PROBE_CSV_EXPORT_PAGES = 100
MAX_PROBE_CSV_EXPORT_SECONDS = 60.0
MAX_PROBE_CSV_CELL_CHARS = 10_000


def safe_csv_cell(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    value = value[:MAX_PROBE_CSV_CELL_CHARS]
    if value.startswith(_FORMULA_PREFIXES):
        return f"'{value}"
    return value


def build_probe_csv_export(fetch_page, server_id, scope, server_name_map):
    """Build a complete bounded-memory CSV before an HTTP response is committed."""
    spool = tempfile.SpooledTemporaryFile(
        max_size=1024 * 1024,
        mode="w+",
        encoding="utf-8",
        newline="",
    )
    writer = csv.writer(spool)
    writer.writerow([
        "Tipo", "Server", "Titolo", "Libreria", "Tipo Errore",
        "Dettaglio Errore", "Tentativi", "Data Ultimo Tentativo",
    ])
    started_at = time.monotonic()
    rows_written = 0
    pages_read = 0
    page, status_code = fetch_page(server_id, "0", None, scope, "500", "0")
    while status_code == 200:
        pages_read += 1
        rows_written += _write_page(writer, page, server_name_map)
        spool.flush()
        if rows_written > MAX_PROBE_CSV_EXPORT_ROWS:
            spool.close()
            return None, {"error": "Esportazione oltre il limite di righe"}, 413
        if spool.tell() > MAX_PROBE_CSV_EXPORT_BYTES:
            spool.close()
            return None, {"error": "Esportazione oltre il limite di dimensione"}, 413
        if pages_read > MAX_PROBE_CSV_EXPORT_PAGES:
            spool.close()
            return None, {"error": "Esportazione oltre il limite di pagine"}, 413
        if time.monotonic() - started_at > MAX_PROBE_CSV_EXPORT_SECONDS:
            spool.close()
            return None, {"error": "Tempo massimo di esportazione superato"}, 503
        next_offset = page.get("next_offset")
        if next_offset is None:
            spool.seek(0)
            return spool, None, 200
        page, status_code = fetch_page(
            server_id, "0", None, scope, "500", str(next_offset)
        )
    spool.close()
    return None, page, status_code


def _write_page(writer, page, server_name_map):
    written = 0
    for item in page.get("blacklist", []):
        error_type = item.get("error_type", "")
        retry_count = item.get("retry_count", 0)
        if error_type == "INCOMPLETE":
            row_type = "Incompleto"
        elif retry_count >= 3:
            row_type = "Errore"
        else:
            continue
        failed_at = _format_failed_at(item.get("failed_at", ""))
        server_id = item.get("server_id", "")
        writer.writerow([safe_csv_cell(value) for value in [
            row_type,
            server_name_map.get(server_id, server_id),
            item.get("item_name", ""),
            item.get("library_name", ""),
            error_type,
            item.get("reason", ""),
            retry_count,
            failed_at,
        ]])
        written += 1
    return written


def _format_failed_at(value):
    if not value:
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except (TypeError, ValueError):
        return value


__all__ = [
    "MAX_PROBE_CSV_EXPORT_BYTES",
    "MAX_PROBE_CSV_CELL_CHARS",
    "MAX_PROBE_CSV_EXPORT_PAGES",
    "MAX_PROBE_CSV_EXPORT_ROWS",
    "MAX_PROBE_CSV_EXPORT_SECONDS",
    "build_probe_csv_export",
    "safe_csv_cell",
]
