"""Bounded workflow failure details safe for persistence and operator display."""

from __future__ import annotations

from typing import Any


WORKFLOW_FAILURE_MESSAGE = "Errore durante l'esecuzione del workflow"
WORKFLOW_SCAN_ERROR_KEY = "_workflow_scan_error"

SCAN_FAILURE_REQUIRES_SERVER = (
    "La scansione di una libreria richiede anche il relativo server"
)
SCAN_FAILURE_CONFIG_UNAVAILABLE = "Configurazione non disponibile"
SCAN_FAILURE_NO_ENABLED_SERVERS = "Nessun server Emby abilitato"
SCAN_FAILURE_LIBRARY_NOT_FOUND = (
    "La libreria richiesta non è presente nell'inventario Emby corrente"
)
SCAN_FAILURE_INVENTORIES_UNAVAILABLE = (
    "Impossibile leggere gli inventari librerie dai server Emby"
)
SCAN_FAILURE_NO_LIBRARIES = "Nessuna libreria Emby scansionabile trovata"
SCAN_FAILURE_NOT_ACCEPTED = (
    "Il gestore delle scansioni non ha accettato alcuna libreria"
)

_SAFE_SCAN_FAILURES = frozenset(
    {
        SCAN_FAILURE_REQUIRES_SERVER,
        SCAN_FAILURE_CONFIG_UNAVAILABLE,
        SCAN_FAILURE_NO_ENABLED_SERVERS,
        SCAN_FAILURE_LIBRARY_NOT_FOUND,
        SCAN_FAILURE_INVENTORIES_UNAVAILABLE,
        SCAN_FAILURE_NO_LIBRARIES,
        SCAN_FAILURE_NOT_ACCEPTED,
    }
)


class WorkflowStepFailure(RuntimeError):
    """A bounded, operator-facing workflow failure safe to persist and expose."""


def set_workflow_scan_failure(context: dict[str, Any], message: str) -> None:
    if message not in _SAFE_SCAN_FAILURES:
        raise ValueError("Dettaglio errore workflow non registrato")
    context[WORKFLOW_SCAN_ERROR_KEY] = message


def workflow_scan_failure_message(context: dict[str, Any]) -> str:
    message = str(context.get(WORKFLOW_SCAN_ERROR_KEY) or "")
    if message in _SAFE_SCAN_FAILURES:
        return message
    return WORKFLOW_FAILURE_MESSAGE


__all__ = [
    "SCAN_FAILURE_CONFIG_UNAVAILABLE",
    "SCAN_FAILURE_INVENTORIES_UNAVAILABLE",
    "SCAN_FAILURE_LIBRARY_NOT_FOUND",
    "SCAN_FAILURE_NOT_ACCEPTED",
    "SCAN_FAILURE_NO_ENABLED_SERVERS",
    "SCAN_FAILURE_NO_LIBRARIES",
    "SCAN_FAILURE_REQUIRES_SERVER",
    "WORKFLOW_FAILURE_MESSAGE",
    "WORKFLOW_SCAN_ERROR_KEY",
    "WorkflowStepFailure",
    "set_workflow_scan_failure",
    "workflow_scan_failure_message",
]
