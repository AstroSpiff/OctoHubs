"""Public-safe messages for failures from outbound HTTP requests."""

from __future__ import annotations

import requests


def safe_http_error_message(error: requests.RequestException) -> str:
    """Describe an HTTP failure without exposing its URL, query, headers or body."""
    if isinstance(error, requests.Timeout):
        return "Timeout durante la connessione al servizio"
    if isinstance(error, requests.ConnectionError):
        return "Servizio remoto non raggiungibile"
    if isinstance(error, requests.HTTPError):
        status_code = getattr(getattr(error, "response", None), "status_code", None)
        if isinstance(status_code, int) and 100 <= status_code <= 599:
            return f"Servizio remoto ha risposto HTTP {status_code}"
        return "Servizio remoto ha rifiutato la richiesta"
    return "Errore durante la connessione al servizio"


__all__ = ["safe_http_error_message"]
