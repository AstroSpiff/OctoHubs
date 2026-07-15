"""FastAPI routes for Telegram configuration."""

from typing import Any, Callable, Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from core.storage import StorageError
from telegram import (
    _load_telegram_settings,
    _save_telegram_settings,
    _telegram_check_bot_identity,
    _telegram_lookup_chat_with_type,
    _check_telegram_chat,
    _telegram_extract_chat_name,
    _telegram_lookup_chat,
    _telegram_check_bot_membership,
)

router = APIRouter()

_require_auth: Optional[Callable[[Request], Any]] = None
_validate_csrf: Optional[Callable[[Request, Optional[str]], bool]] = None
_flash: Optional[Callable[[Request, str, str], None]] = None
_resolve_next_url: Optional[Callable[[Optional[str], str], str]] = None
_ensure_db_backend: Optional[Callable[[], Any]] = None
_load_config: Optional[Callable[[], Any]] = None


def init_telegram_routes(
    require_auth: Callable[[Request], Any],
    validate_csrf: Callable[[Request, Optional[str]], bool],
    flash: Callable[[Request, str, str], None],
    resolve_next_url: Callable[[Optional[str], str], str],
    ensure_db_backend: Callable[[], Any],
    load_config: Callable[[], Any],
) -> None:
    global _require_auth, _validate_csrf, _flash, _resolve_next_url, _ensure_db_backend, _load_config
    _require_auth = require_auth
    _validate_csrf = validate_csrf
    _flash = flash
    _resolve_next_url = resolve_next_url
    _ensure_db_backend = ensure_db_backend
    _load_config = load_config


def _require_auth_dep(request: Request):
    if _require_auth is None:
        raise RuntimeError("Telegram routes not initialized: require_auth missing")
    return _require_auth(request)


def _validate_csrf_dep(request: Request, token: Optional[str]) -> bool:
    if _validate_csrf is None:
        raise RuntimeError("Telegram routes not initialized: validate_csrf missing")
    return _validate_csrf(request, token)


def _flash_dep(request: Request, message: str, category: str = "message") -> None:
    if _flash is None:
        raise RuntimeError("Telegram routes not initialized: flash missing")
    _flash(request, message, category)


def _resolve_next_url_dep(next_url: Optional[str], fallback_endpoint: str) -> str:
    if _resolve_next_url is None:
        raise RuntimeError("Telegram routes not initialized: resolve_next_url missing")
    return _resolve_next_url(next_url, fallback_endpoint)


def _ensure_db_backend_dep() -> None:
    if _ensure_db_backend is None:
        raise RuntimeError("Telegram routes not initialized: ensure_db_backend missing")
    _ensure_db_backend()


def _load_config_dep():
    if _load_config is None:
        raise RuntimeError("Telegram routes not initialized: load_config missing")
    return _load_config()


@router.post("/telegram/config")
async def telegram_save_config_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    telegram_bot_alias: str = Form(""),
    telegram_bot_token: str = Form(""),
    telegram_bot_id: str = Form(""),
    csrf_token: str = Form(None, alias="csrf_token"),
):
    """Save/update Telegram bot configuration."""
    _require_auth_dep(request)

    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/configuration", status_code=303)

    import uuid

    next_url = _resolve_next_url_dep(next_page, "configuration")
    config, is_valid = _load_config_dep()

    if not is_valid or not config:
        _flash_dep(request, "Config non valida.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend_dep()
    except StorageError as exc:
        _flash_dep(request, f"Errore DB: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    bot_alias = telegram_bot_alias.strip()
    bot_token = telegram_bot_token.strip()
    bot_id = telegram_bot_id.strip()

    if not bot_token:
        _flash_dep(request, "Token bot mancante.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    telegram_settings = _load_telegram_settings()
    bots = telegram_settings.get("BOTS") or []

    if bot_id:
        existing = next((bot for bot in bots if bot.get("id") == bot_id), None)
        if not existing:
            _flash_dep(request, "Bot Telegram non trovato.", "error")
            return RedirectResponse(url=next_url, status_code=303)

        duplicate = next((bot for bot in bots if bot.get("token") == bot_token and bot.get("id") != bot_id), None)
        if duplicate:
            _flash_dep(request, "Token bot già associato a un altro bot.", "error")
            return RedirectResponse(url=next_url, status_code=303)

        existing["alias"] = bot_alias
        existing["token"] = bot_token
        ok, message = _telegram_check_bot_identity(existing)
        _flash_dep(request, "Bot Telegram aggiornato.", "success")
    else:
        existing = next((bot for bot in bots if bot.get("token") == bot_token), None)
        if existing:
            existing["alias"] = bot_alias
            ok, message = _telegram_check_bot_identity(existing)
            _flash_dep(request, "Bot Telegram aggiornato.", "success")
        else:
            bot_entry = {
                "id": str(uuid.uuid4()),
                "alias": bot_alias,
                "original_name": "",
                "token": bot_token,
                "username": "",
                "user_id": "",
                "verified": False,
                "verified_at": "",
                "last_check": "",
                "last_error": "",
            }
            ok, message = _telegram_check_bot_identity(bot_entry)
            bots.append(bot_entry)
            _flash_dep(request, "Bot Telegram salvato.", "success")

    telegram_settings["BOTS"] = bots
    _save_telegram_settings(telegram_settings)

    if "message" in locals() and message and not message.startswith("Bot verificato"):
        _flash_dep(request, message, "warning")

    return RedirectResponse(url=next_url, status_code=303)


@router.post("/telegram/bot/add")
async def telegram_add_bot_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    telegram_bot_alias: str = Form(""),
    telegram_bot_token: str = Form(""),
    telegram_bot_id: str = Form(""),
    csrf_token: str = Form(None, alias="csrf_token"),
):
    """Add Telegram bot - delegates to telegram_save_config_route."""
    return await telegram_save_config_route(
        request,
        next_page,
        telegram_bot_alias,
        telegram_bot_token,
        telegram_bot_id,
        csrf_token,
    )


@router.post("/telegram/bot/verify")
async def telegram_verify_bot_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    telegram_bot_id: str = Form(""),
    csrf_token: str = Form(None, alias="csrf_token"),
):
    """Verify Telegram bot identity."""
    _require_auth_dep(request)

    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/configuration", status_code=303)

    next_url = _resolve_next_url_dep(next_page, "configuration")
    config, is_valid = _load_config_dep()

    if not is_valid or not config:
        _flash_dep(request, "Config non valida.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend_dep()
    except StorageError as exc:
        _flash_dep(request, f"Errore DB: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    bot_id = telegram_bot_id.strip()
    if not bot_id:
        _flash_dep(request, "Bot Telegram non valido.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    telegram_settings = _load_telegram_settings()
    bots = telegram_settings.get("BOTS") or []
    bot = next((item for item in bots if item.get("id") == bot_id), None)

    if not bot:
        _flash_dep(request, "Bot Telegram non trovato.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    ok, message = _telegram_check_bot_identity(bot)
    telegram_settings["BOTS"] = bots
    _save_telegram_settings(telegram_settings)

    if ok:
        _flash_dep(request, message, "success")
    else:
        _flash_dep(request, f"Errore bot: {message}", "error")

    return RedirectResponse(url=next_url, status_code=303)


@router.post("/telegram/bot/remove")
async def telegram_remove_bot_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    telegram_bot_id: str = Form(""),
    csrf_token: str = Form(None, alias="csrf_token"),
):
    """Remove Telegram bot and clean up references in presets."""
    _require_auth_dep(request)

    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/configuration", status_code=303)

    next_url = _resolve_next_url_dep(next_page, "configuration")
    config, is_valid = _load_config_dep()

    if not is_valid or not config:
        _flash_dep(request, "Config non valida.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend_dep()
    except StorageError as exc:
        _flash_dep(request, f"Errore DB: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    bot_id = telegram_bot_id.strip()
    if not bot_id:
        _flash_dep(request, "Bot Telegram non valido.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    telegram_settings = _load_telegram_settings()
    bots = telegram_settings.get("BOTS") or []
    updated = [bot for bot in bots if bot.get("id") != bot_id]

    if len(updated) == len(bots):
        _flash_dep(request, "Bot Telegram non trovato.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    presets = telegram_settings.get("PRESETS") or []
    for preset in presets:
        preset["bot_ids"] = [value for value in preset.get("bot_ids", []) if value != bot_id]
        alerts = preset.get("alerts")
        if isinstance(alerts, dict):
            for key in ("groups", "channels"):
                items = alerts.get(key)
                if not isinstance(items, dict):
                    continue
                for chat_id, checks in list(items.items()):
                    if not isinstance(checks, list):
                        continue
                    remaining = [check for check in checks if check.get("bot_id") != bot_id]
                    if remaining:
                        items[chat_id] = remaining
                    else:
                        items.pop(chat_id, None)

    telegram_settings["BOTS"] = updated
    telegram_settings["PRESETS"] = presets
    _save_telegram_settings(telegram_settings)

    _flash_dep(request, "Bot Telegram rimosso.", "success")
    return RedirectResponse(url=next_url, status_code=303)


@router.post("/telegram/bot/alias")
async def telegram_update_bot_alias_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    telegram_bot_id: str = Form(""),
    telegram_bot_alias: str = Form(""),
    csrf_token: str = Form(None, alias="csrf_token"),
):
    """Update Telegram bot alias."""
    _require_auth_dep(request)

    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/configuration", status_code=303)

    next_url = _resolve_next_url_dep(next_page, "configuration")
    config, is_valid = _load_config_dep()

    if not is_valid or not config:
        _flash_dep(request, "Config non valida.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend_dep()
    except StorageError as exc:
        _flash_dep(request, f"Errore DB: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    bot_id = telegram_bot_id.strip()
    if not bot_id:
        _flash_dep(request, "Bot Telegram non valido.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    alias = telegram_bot_alias.strip()

    telegram_settings = _load_telegram_settings()
    bots = telegram_settings.get("BOTS") or []
    bot = next((item for item in bots if item.get("id") == bot_id), None)

    if not bot:
        _flash_dep(request, "Bot Telegram non trovato.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    bot["alias"] = alias
    if not bot.get("original_name"):
        _telegram_check_bot_identity(bot)

    telegram_settings["BOTS"] = bots
    _save_telegram_settings(telegram_settings)

    _flash_dep(request, "Alias bot aggiornato.", "success")
    return RedirectResponse(url=next_url, status_code=303)


@router.post("/telegram/chat/add")
async def telegram_add_chat_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    telegram_kind: str = Form(""),
    telegram_alias: str = Form(""),
    telegram_chat_id: str = Form(""),
    telegram_id: str = Form(""),
    csrf_token: str = Form(None, alias="csrf_token"),
):
    """Add or update Telegram chat (group or channel)."""
    _require_auth_dep(request)

    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/configuration", status_code=303)

    from datetime import datetime, timezone
    import uuid

    next_url = _resolve_next_url_dep(next_page, "configuration")
    config, is_valid = _load_config_dep()

    if not is_valid or not config:
        _flash_dep(request, "Config non valida.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend_dep()
    except StorageError as exc:
        _flash_dep(request, f"Errore DB: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    kind = telegram_kind.strip().lower()
    if kind not in ("group", "channel"):
        _flash_dep(request, "Tipo Telegram non valido.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    alias = telegram_alias.strip()
    chat_id = telegram_chat_id.strip()
    entry_id = telegram_id.strip()

    if not chat_id:
        _flash_dep(request, "Chat ID Telegram mancante.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    telegram_settings = _load_telegram_settings()
    list_key = "GROUPS" if kind == "group" else "CHANNELS"
    entries = telegram_settings.get(list_key) or []
    existing = None

    if entry_id:
        existing = next((entry for entry in entries if entry.get("id") == entry_id), None)
        if not existing:
            _flash_dep(request, "Chat Telegram non trovata.", "error")
            return RedirectResponse(url=next_url, status_code=303)

        duplicate = next((entry for entry in entries if entry.get("chat_id") == chat_id and entry.get("id") != entry_id), None)
        if duplicate:
            _flash_dep(request, "Chat ID già associato a un'altra voce.", "error")
            return RedirectResponse(url=next_url, status_code=303)

        if existing.get("chat_id") != chat_id:
            existing["chat_id"] = chat_id
            existing["original_name"] = ""
            existing["verified"] = False
            existing["verified_at"] = ""
            existing["last_check"] = ""
            existing["last_error"] = ""

        existing["alias"] = alias
        _flash_dep(request, "Chat Telegram aggiornata.", "success")
    else:
        existing = next((entry for entry in entries if entry.get("chat_id") == chat_id), None)
        if existing:
            existing["alias"] = alias
            _flash_dep(request, "Chat Telegram aggiornata.", "success")
        else:
            existing = {
                "id": str(uuid.uuid4()),
                "alias": alias,
                "original_name": "",
                "chat_id": chat_id,
                "verified": False,
                "verified_at": "",
                "last_check": "",
                "last_error": "",
            }
            entries.append(existing)
            _flash_dep(request, "Chat Telegram salvata.", "success")

    bots = telegram_settings.get("BOTS") or []
    if bots:
        original_name, bot_id, chat_type = _telegram_lookup_chat_with_type(chat_id, bots)
        if original_name:
            if kind == "channel" and chat_type not in ("channel", ""):
                _flash_dep(request, f"Errore: {chat_id} non è un canale ma un {chat_type}.", "error")
                return RedirectResponse(url=next_url, status_code=303)
            if kind == "group" and chat_type not in ("group", "supergroup", ""):
                _flash_dep(request, f"Errore: {chat_id} non è un gruppo ma un {chat_type}.", "error")
                return RedirectResponse(url=next_url, status_code=303)

            now_stamp = datetime.now(timezone.utc).astimezone().isoformat()
            existing["original_name"] = original_name
            existing["last_bot_id"] = bot_id
            existing["verified"] = True
            existing["verified_at"] = now_stamp
            existing["last_check"] = now_stamp
            existing["last_error"] = ""

    telegram_settings[list_key] = entries
    _save_telegram_settings(telegram_settings)

    return RedirectResponse(url=next_url, status_code=303)


@router.post("/telegram/chat/verify")
async def telegram_verify_chat_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    telegram_kind: str = Form(""),
    telegram_id: str = Form(""),
    telegram_bot_id: str = Form(""),
    csrf_token: str = Form(None, alias="csrf_token"),
):
    """Verify Telegram chat using a bot."""
    _require_auth_dep(request)

    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/configuration", status_code=303)

    from datetime import datetime, timezone

    next_url = _resolve_next_url_dep(next_page, "configuration")
    config, is_valid = _load_config_dep()

    if not is_valid or not config:
        _flash_dep(request, "Config non valida.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend_dep()
    except StorageError as exc:
        _flash_dep(request, f"Errore DB: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    kind = telegram_kind.strip().lower()
    entry_id = telegram_id.strip()

    if kind not in ("group", "channel") or not entry_id:
        _flash_dep(request, "Dati Telegram non validi.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    telegram_settings = _load_telegram_settings()
    list_key = "GROUPS" if kind == "group" else "CHANNELS"
    entries = telegram_settings.get(list_key) or []
    entry = next((item for item in entries if item.get("id") == entry_id), None)

    if not entry:
        _flash_dep(request, "Chat Telegram non trovata.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    bot_id = telegram_bot_id.strip()
    bots = telegram_settings.get("BOTS") or []
    bot = None

    if bot_id:
        bot = next((item for item in bots if item.get("id") == bot_id), None)
    if not bot and bots:
        bot = bots[0]

    if not bot:
        _flash_dep(request, "Nessun bot disponibile.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    ok, message, result = _check_telegram_chat(bot.get("token", ""), entry.get("chat_id", ""))
    now_stamp = datetime.now(timezone.utc).astimezone().isoformat()
    entry["last_check"] = now_stamp
    entry["last_bot_id"] = bot.get("id") if bot else ""

    if ok:
        entry["verified"] = True
        entry["verified_at"] = now_stamp
        entry["last_error"] = ""
        original_name = _telegram_extract_chat_name(result)
        if original_name:
            entry["original_name"] = original_name
        _flash_dep(request, message, "success")
    else:
        entry["verified"] = False
        entry["last_error"] = message
        _flash_dep(request, message, "error")

    telegram_settings[list_key] = entries
    _save_telegram_settings(telegram_settings)

    return RedirectResponse(url=next_url, status_code=303)


@router.post("/telegram/chat/remove")
async def telegram_remove_chat_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    telegram_kind: str = Form(""),
    telegram_id: str = Form(""),
    csrf_token: str = Form(None, alias="csrf_token"),
):
    """Remove Telegram chat and clean up references in presets."""
    _require_auth_dep(request)

    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/configuration", status_code=303)

    next_url = _resolve_next_url_dep(next_page, "configuration")
    config, is_valid = _load_config_dep()

    if not is_valid or not config:
        _flash_dep(request, "Config non valida.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend_dep()
    except StorageError as exc:
        _flash_dep(request, f"Errore DB: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    kind = telegram_kind.strip().lower()
    entry_id = telegram_id.strip()

    if kind not in ("group", "channel") or not entry_id:
        _flash_dep(request, "Dati Telegram non validi.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    telegram_settings = _load_telegram_settings()
    list_key = "GROUPS" if kind == "group" else "CHANNELS"
    entries = telegram_settings.get(list_key) or []
    updated = [entry for entry in entries if entry.get("id") != entry_id]

    if len(updated) == len(entries):
        _flash_dep(request, "Chat Telegram non trovata.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    telegram_settings[list_key] = updated

    presets = telegram_settings.get("PRESETS") or []
    for preset in presets:
        if kind == "group":
            preset["group_ids"] = [value for value in preset.get("group_ids", []) if value != entry_id]
        else:
            preset["channel_ids"] = [value for value in preset.get("channel_ids", []) if value != entry_id]
        alerts = preset.get("alerts")
        if isinstance(alerts, dict):
            key = "groups" if kind == "group" else "channels"
            items = alerts.get(key)
            if isinstance(items, dict):
                items.pop(entry_id, None)

    telegram_settings["PRESETS"] = presets
    _save_telegram_settings(telegram_settings)

    _flash_dep(request, "Chat Telegram rimossa.", "success")
    return RedirectResponse(url=next_url, status_code=303)


@router.post("/telegram/chat/alias")
async def telegram_update_chat_alias_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    telegram_kind: str = Form(""),
    telegram_id: str = Form(""),
    telegram_alias: str = Form(""),
    csrf_token: str = Form(None, alias="csrf_token"),
):
    """Update Telegram chat alias."""
    _require_auth_dep(request)

    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/configuration", status_code=303)

    from datetime import datetime, timezone

    next_url = _resolve_next_url_dep(next_page, "configuration")
    config, is_valid = _load_config_dep()

    if not is_valid or not config:
        _flash_dep(request, "Config non valida.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend_dep()
    except StorageError as exc:
        _flash_dep(request, f"Errore DB: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    kind = telegram_kind.strip().lower()
    entry_id = telegram_id.strip()

    if kind not in ("group", "channel") or not entry_id:
        _flash_dep(request, "Dati Telegram non validi.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    alias = telegram_alias.strip()

    telegram_settings = _load_telegram_settings()
    list_key = "GROUPS" if kind == "group" else "CHANNELS"
    entries = telegram_settings.get(list_key) or []
    entry = next((item for item in entries if item.get("id") == entry_id), None)

    if not entry:
        _flash_dep(request, "Chat Telegram non trovata.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    entry["alias"] = alias

    if not entry.get("original_name"):
        bots = telegram_settings.get("BOTS") or []
        original_name, bot_id = _telegram_lookup_chat(entry.get("chat_id", ""), bots)
        if original_name:
            now_stamp = datetime.now(timezone.utc).astimezone().isoformat()
            entry["original_name"] = original_name
            entry["last_bot_id"] = bot_id
            entry["verified"] = True
            entry["verified_at"] = now_stamp
            entry["last_check"] = now_stamp
            entry["last_error"] = ""

    telegram_settings[list_key] = entries
    _save_telegram_settings(telegram_settings)

    _flash_dep(request, "Alias chat aggiornato.", "success")
    return RedirectResponse(url=next_url, status_code=303)


@router.post("/telegram/preset/add")
async def telegram_add_preset_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    telegram_preset_name: str = Form(""),
    telegram_preset_bot: str = Form(""),
    telegram_preset_groups: list[str] = Form([]),
    telegram_preset_channels: list[str] = Form([]),
    telegram_preset_id: str = Form(""),
    csrf_token: str = Form(None, alias="csrf_token"),
):
    """Add or update Telegram preset with bot and chat associations."""
    _require_auth_dep(request)

    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/configuration", status_code=303)

    from datetime import datetime, timezone
    import uuid

    next_url = _resolve_next_url_dep(next_page, "configuration")
    config, is_valid = _load_config_dep()

    if not is_valid or not config:
        _flash_dep(request, "Config non valida.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend_dep()
    except StorageError as exc:
        _flash_dep(request, f"Errore DB: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    preset_name = telegram_preset_name.strip()
    if not preset_name:
        _flash_dep(request, "Nome preconfigurazione mancante.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    bot_id = telegram_preset_bot.strip()
    group_ids = [value for value in telegram_preset_groups if value]
    channel_ids = [value for value in telegram_preset_channels if value]

    if not bot_id:
        _flash_dep(request, "Seleziona un bot.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    if not group_ids and not channel_ids:
        _flash_dep(request, "Seleziona almeno un gruppo o canale.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    bot_ids = [bot_id]

    telegram_settings = _load_telegram_settings()
    bots = telegram_settings.get("BOTS") or []
    groups = telegram_settings.get("GROUPS") or []
    channels = telegram_settings.get("CHANNELS") or []

    selected_bots = [bot for bot in bots if bot.get("id") in bot_ids]
    selected_groups = [entry for entry in groups if entry.get("id") in group_ids]
    selected_channels = [entry for entry in channels if entry.get("id") in channel_ids]

    if not selected_bots:
        _flash_dep(request, "Bot selezionati non validi.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    now_stamp = datetime.now(timezone.utc).astimezone().isoformat()
    alerts = {"groups": {}, "channels": {}}

    for bot in selected_bots:
        ok, message = _telegram_check_bot_identity(bot)
        if not ok:
            for group in selected_groups:
                alerts["groups"].setdefault(group["id"], []).append({
                    "bot_id": bot.get("id", ""),
                    "status": "error",
                    "message": message,
                    "checked_at": now_stamp,
                })
            for channel in selected_channels:
                alerts["channels"].setdefault(channel["id"], []).append({
                    "bot_id": bot.get("id", ""),
                    "status": "error",
                    "message": message,
                    "checked_at": now_stamp,
                })
            continue

        for group in selected_groups:
            status, status_message = _telegram_check_bot_membership(bot, group.get("chat_id", ""))
            alerts["groups"].setdefault(group["id"], []).append({
                "bot_id": bot.get("id", ""),
                "status": status,
                "message": status_message,
                "checked_at": now_stamp,
            })

        for channel in selected_channels:
            status, status_message = _telegram_check_bot_membership(bot, channel.get("chat_id", ""))
            alerts["channels"].setdefault(channel["id"], []).append({
                "bot_id": bot.get("id", ""),
                "status": status,
                "message": status_message,
                "checked_at": now_stamp,
            })

    presets = telegram_settings.get("PRESETS") or []
    preset_id = telegram_preset_id.strip()
    existing = next((preset for preset in presets if preset.get("id") == preset_id), None)

    if existing:
        existing["name"] = preset_name
        existing["bot_ids"] = bot_ids
        existing["group_ids"] = group_ids
        existing["channel_ids"] = channel_ids
        existing["alerts"] = alerts
        existing["updated_at"] = now_stamp
        existing["last_check"] = now_stamp
        existing["last_error"] = ""
        _flash_dep(request, "Preconfigurazione aggiornata.", "success")
    else:
        presets.append({
            "id": str(uuid.uuid4()),
            "name": preset_name,
            "bot_ids": bot_ids,
            "group_ids": group_ids,
            "channel_ids": channel_ids,
            "alerts": alerts,
            "created_at": now_stamp,
            "last_check": now_stamp,
            "last_error": "",
        })
        _flash_dep(request, "Preconfigurazione salvata.", "success")

    telegram_settings["BOTS"] = bots
    telegram_settings["PRESETS"] = presets
    _save_telegram_settings(telegram_settings)

    return RedirectResponse(url=next_url, status_code=303)


@router.post("/telegram/preset/remove")
async def telegram_remove_preset_route(
    request: Request,
    next_page: str = Form(None, alias="next"),
    telegram_preset_id: str = Form(""),
    csrf_token: str = Form(None, alias="csrf_token"),
):
    """Remove Telegram preset."""
    _require_auth_dep(request)

    if not _validate_csrf_dep(request, csrf_token):
        _flash_dep(request, "CSRF token non valido.", "error")
        return RedirectResponse(url="/configuration", status_code=303)

    next_url = _resolve_next_url_dep(next_page, "configuration")
    config, is_valid = _load_config_dep()

    if not is_valid or not config:
        _flash_dep(request, "Config non valida.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    try:
        _ensure_db_backend_dep()
    except StorageError as exc:
        _flash_dep(request, f"Errore DB: {exc}", "error")
        return RedirectResponse(url=next_url, status_code=303)

    preset_id = telegram_preset_id.strip()
    if not preset_id:
        _flash_dep(request, "Preconfigurazione non valida.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    telegram_settings = _load_telegram_settings()
    presets = telegram_settings.get("PRESETS") or []
    updated = [preset for preset in presets if preset.get("id") != preset_id]

    if len(updated) == len(presets):
        _flash_dep(request, "Preconfigurazione non trovata.", "error")
        return RedirectResponse(url=next_url, status_code=303)

    telegram_settings["PRESETS"] = updated
    _save_telegram_settings(telegram_settings)

    _flash_dep(request, "Preconfigurazione rimossa.", "success")
    return RedirectResponse(url=next_url, status_code=303)
