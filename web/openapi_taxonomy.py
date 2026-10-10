"""Domain-oriented taxonomy for the internal and external OpenAPI catalogs."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any


_HTTP_OPERATIONS = frozenset({"get", "put", "post", "delete", "patch", "head", "options"})
UNCLASSIFIED_TAG = "Sistema · Altro"


@dataclass(frozen=True)
class OpenApiTag:
    name: str
    description: str


OPENAPI_TAGS = (
    OpenApiTag(
        "Accesso · Sessione e installazione",
        "Accesso browser, chiusura della sessione e bootstrap iniziale dell'installazione.",
    ),
    OpenApiTag(
        "Account · Profilo e preferenze",
        "Profilo corrente, sessione applicativa e preferenze personali.",
    ),
    OpenApiTag(
        "Account · Token API",
        "Creazione, rotazione, revoca e audit dei token personali per l'API esterna.",
    ),
    OpenApiTag(
        "Amministrazione · Account",
        "Gestione amministrativa degli account OctoHubs e dei relativi ruoli.",
    ),
    OpenApiTag(
        "Sistema · Configurazione",
        "Configurazione persistente, automazioni e verifica delle integrazioni.",
    ),
    OpenApiTag(
        "Sistema · Stato e diagnostica",
        "Stato operativo, diagnostica e aggiornamenti realtime dell'applicazione.",
    ),
    OpenApiTag(
        "Sistema · Operazioni e workflow",
        "Avvio, arresto, avanzamento e storico delle operazioni applicative coordinate.",
    ),
    OpenApiTag(
        "Emby · Server e librerie",
        "Server Emby, disponibilità, ordinamento e struttura delle librerie configurate.",
    ),
    OpenApiTag(
        "Emby · Operazioni libreria",
        "Scansioni e azioni tracciate sulle librerie Emby.",
    ),
    OpenApiTag(
        "Emby · Catalogo multimediale",
        "Lookup, associazioni e dettagli di film, serie, stagioni, episodi e versioni.",
    ),
    OpenApiTag(
        "Emby · Utenti",
        "Utenti Emby, gruppi, accessi, password, sincronizzazione e preset.",
    ),
    OpenApiTag(
        "Emby · Icone utente",
        "Profili, regole e associazioni per le icone degli utenti Emby.",
    ),
    OpenApiTag(
        "Emby · Collezioni",
        "Collezioni, sorgenti esterne, immagini e sincronizzazione tra server.",
    ),
    OpenApiTag(
        "Emby · Pubblicazioni",
        "Ultime pubblicazioni, arricchimento, regole e notifiche.",
    ),
    OpenApiTag(
        "Emby · Media Probe",
        "Individuazione, coda, analisi tecnica, storico e blacklist dei file multimediali.",
    ),
    OpenApiTag(
        "Emby · Live e Transcode Guard",
        "Stream attivi, eventi Emby e protezione delle sessioni di riproduzione.",
    ),
    OpenApiTag(
        "Ricerca · Catalogo e disponibilità",
        "Metadati, dettaglio dei contenuti e verifica della disponibilità sui server.",
    ),
    OpenApiTag(
        "Ricerca · Ricerche",
        "Ricerca manuale, streaming dei risultati, regole e cronologia.",
    ),
    OpenApiTag(
        "Ricerca · Richieste",
        "Creazione e aggiornamento delle richieste di contenuti.",
    ),
    OpenApiTag(
        "Ricerca · Download",
        "Preparazione e inoltro controllato dei risultati torrent.",
    ),
    OpenApiTag(
        "Integrazioni · Telegram",
        "Configurazione e azioni dell'integrazione Telegram.",
    ),
    OpenApiTag(
        "Integrazioni · Trakt",
        "Autorizzazione e gestione del collegamento Trakt.",
    ),
    OpenApiTag(
        "Integrazioni · Event Bridge",
        "Configurazione, credenziali e stato del bridge eventi Emby.",
    ),
    OpenApiTag(
        "API esterna · Contratto",
        "Catalogo versionato delle operazioni disponibili ai client esterni.",
    ),
    OpenApiTag(
        UNCLASSIFIED_TAG,
        "Route non ancora assegnate a un dominio; il gate di contratto impedisce l'uso involontario di questo gruppo.",
    ),
)


def _starts_with(path: str, *prefixes: str) -> bool:
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in prefixes)


_EXACT_PATH_TAGS = {
    "/login": "Accesso · Sessione e installazione",
    "/logout": "Accesso · Sessione e installazione",
    "/setup": "Accesso · Sessione e installazione",
    "/setup/db": "Accesso · Sessione e installazione",
    "/setup/user": "Accesso · Sessione e installazione",
    "/api/test-connections": "Sistema · Configurazione",
    "/api/scan-status": "Sistema · Stato e diagnostica",
    "/api/emby/event-bridge/events": "Emby · Live e Transcode Guard",
    "/api/emby/events-stream": "Emby · Live e Transcode Guard",
    "/api/emby/status-stream": "Emby · Live e Transcode Guard",
    "/api/emby/stop-task": "Emby · Operazioni libreria",
    "/api/emby/status": "Emby · Server e librerie",
    "/api/external/openapi.json": "API esterna · Contratto",
}

_PATH_PREFIX_TAGS = (
    (("/api/account/tokens",), "Account · Token API"),
    (("/api/account/me", "/api/ui"), "Account · Profilo e preferenze"),
    (("/api/admin/accounts",), "Amministrazione · Account"),
    (("/api/configuration",), "Sistema · Configurazione"),
    (("/api/operations", "/api/workflow"), "Sistema · Operazioni e workflow"),
    (("/api/system/status", "/api/realtime"), "Sistema · Stato e diagnostica"),
    (("/api/emby/users",), "Emby · Utenti"),
    (("/api/emby/icons",), "Emby · Icone utente"),
    (("/api/emby/collections",), "Emby · Collezioni"),
    (("/api/emby/latest",), "Emby · Pubblicazioni"),
    (("/api/emby/probe",), "Emby · Media Probe"),
    (
        ("/api/emby/transcode-guard", "/api/emby/streams"),
        "Emby · Live e Transcode Guard",
    ),
    (
        (
            "/api/emby/actions",
            "/api/emby/active-library-scans",
            "/api/emby/active-scan-jobs",
            "/api/emby/active-scans",
            "/api/emby/scan-group-tracked",
            "/api/emby/scan-job",
            "/api/emby/scan-jobs",
            "/api/emby/scan-library",
            "/api/emby/scan-library-tracked",
        ),
        "Emby · Operazioni libreria",
    ),
    (
        (
            "/api/emby/servers",
            "/api/emby/server-order",
            "/api/emby/server-status",
            "/api/emby/group-order",
            "/api/emby/grouped-libraries",
        ),
        "Emby · Server e librerie",
    ),
    (("/api/emby",), "Emby · Catalogo multimediale"),
    (
        ("/api/research/requests", "/api/research/request-rules"),
        "Ricerca · Richieste",
    ),
    (("/api/research/torrents",), "Ricerca · Download"),
    (
        ("/api/research/tmdb", "/api/research/media/details"),
        "Ricerca · Catalogo e disponibilità",
    ),
    (("/api/research",), "Ricerca · Ricerche"),
    (("/api/telegram",), "Integrazioni · Telegram"),
    (("/api/trakt",), "Integrazioni · Trakt"),
    (("/api/event-bridge",), "Integrazioni · Event Bridge"),
)


def classify_openapi_path(path: str) -> str:
    """Return the single domain/subdomain tag owned by one documented path."""
    normalized = str(path or "").rstrip("/") or "/"
    exact_tag = _EXACT_PATH_TAGS.get(normalized)
    if exact_tag is not None:
        return exact_tag
    for prefixes, tag in _PATH_PREFIX_TAGS:
        if _starts_with(normalized, *prefixes):
            return tag
    return UNCLASSIFIED_TAG


def apply_openapi_taxonomy(schema: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """Attach one canonical domain tag to every operation and order its catalog."""
    used_tags: set[str] = set()
    paths = schema.get("paths")
    if isinstance(paths, Mapping):
        for path, path_item in paths.items():
            if not isinstance(path_item, MutableMapping):
                continue
            tag = classify_openapi_path(str(path))
            for method, operation in path_item.items():
                if method.lower() not in _HTTP_OPERATIONS or not isinstance(operation, MutableMapping):
                    continue
                operation["tags"] = [tag]
                used_tags.add(tag)

    schema["tags"] = [
        {"name": definition.name, "description": definition.description}
        for definition in OPENAPI_TAGS
        if definition.name in used_tags
    ]
    schema["x-octohubs-taxonomy"] = "domain-subdomain-v1"
    return schema


def configure_openapi_taxonomy(app: Any) -> None:
    """Wrap FastAPI's schema builder without changing application routes."""
    original_openapi: Callable[[], MutableMapping[str, Any]] = app.openapi

    def domain_openapi() -> MutableMapping[str, Any]:
        schema = original_openapi()
        if schema.get("x-octohubs-taxonomy") != "domain-subdomain-v1":
            apply_openapi_taxonomy(schema)
        return schema

    app.openapi = domain_openapi
