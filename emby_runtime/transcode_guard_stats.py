"""Aggregations for Transcode Guard stream history."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional


PERIODS = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}

ISSUE_ACTIONS = {
    "warn",
    "warning_error",
    "stop",
    "partial_resolved",
    "relapse",
}

INTERESTING_NON_ISSUE_ACTIONS = {
    "resolved",
    "resolved_later",
    "resolution_change",
}


def build_user_stream_stats(
    rows: Iterable[Dict[str, Any]],
    filters: Optional[Dict[str, Any]] = None,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Return user-oriented stream statistics from normalized stream history rows."""

    filters = dict(filters or {})
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    limit = _bounded_int(filters.get("limit"), 1, 500, 160)
    source_rows = list(rows or [])
    filtered = _filter_rows(source_rows, filters, now)
    facet_rows = _filter_rows(source_rows, {
        "period": filters.get("period"),
        "issues_only": filters.get("issues_only"),
    }, now)
    filtered = sorted(filtered, key=_row_sort_key, reverse=True)
    history_rows = [_history_row(row) for row in filtered[:limit]]
    users = _sort_users(_aggregate_users(filtered), str(filters.get("sort") or "issues_desc"))
    summary = _summary(filtered, users)
    return {
        "ok": True,
        "filters": {
            "period": str(filters.get("period") or "7d"),
            "server_id": str(filters.get("server_id") or ""),
            "user": str(filters.get("user") or ""),
            "client": str(filters.get("client") or ""),
            "issues_only": _to_bool(filters.get("issues_only"), False),
            "sort": str(filters.get("sort") or "issues_desc"),
            "limit": limit,
        },
        "summary": summary,
        "users": users,
        "history": history_rows,
        "facets": _facets(facet_rows),
    }


def get_stream_history_detail(
    rows: Iterable[Dict[str, Any]],
    stream_id: str,
) -> Optional[Dict[str, Any]]:
    """Return one normalized monitored stream without duplicating the stats contract."""

    wanted_id = str(stream_id or "").strip()
    if not wanted_id:
        return None
    for row in rows or []:
        if isinstance(row, dict) and str(row.get("id") or "") == wanted_id:
            return _history_row(row)
    return None


def _filter_rows(rows: List[Dict[str, Any]], filters: Dict[str, Any], now: datetime) -> List[Dict[str, Any]]:
    period = str(filters.get("period") or "7d")
    threshold = None if period == "all" else now - PERIODS.get(period, PERIODS["7d"])
    server_id = str(filters.get("server_id") or "").strip()
    user = str(filters.get("user") or "").strip().lower()
    client = str(filters.get("client") or "").strip().lower()
    issues_only = _to_bool(filters.get("issues_only"), False)

    filtered: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_time = _parse_datetime(row.get("updated_at") or row.get("last_seen_at") or row.get("started_at"))
        if threshold is not None and row_time is not None and row_time < threshold:
            continue
        if server_id and str(row.get("server_id") or "") != server_id:
            continue
        if user and user not in str(row.get("user") or "").lower():
            continue
        if client and client not in str(row.get("client") or "").lower():
            continue
        if issues_only and not _row_is_interesting(row):
            continue
        filtered.append(dict(row))
    return filtered


def _summary(rows: List[Dict[str, Any]], users: List[Dict[str, Any]]) -> Dict[str, Any]:
    streams = len(rows)
    correct = sum(1 for row in rows if _row_is_correct(row))
    issue_streams = sum(1 for row in rows if _row_is_issue(row))
    active = sum(1 for row in rows if not row.get("ended_at"))
    return {
        "users": len(users),
        "streams": streams,
        "correct": correct,
        "issue_streams": issue_streams,
        "technical_issues": sum(len(row.get("violations_committed") or []) for row in rows),
        "warnings": sum(1 for row in rows if _has_action(row, {"warn", "warning_error"})),
        "stops": sum(1 for row in rows if _has_action(row, {"stop"})),
        "resolved": sum(1 for row in rows if _has_action(row, {"resolved", "resolved_later"})),
        "exits": sum(1 for row in rows if _has_action(row, {"exit"})),
        "resolution_changes": sum(1 for row in rows if _has_action(row, {"resolution_change"})),
        "relapses": sum(1 for row in rows if _has_action(row, {"relapse"})),
        "active": active,
        "problem_rate": round((issue_streams / streams * 100.0), 1) if streams else 0.0,
    }


def _aggregate_users(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[_user_label(row)].append(row)

    users = []
    for user, items in grouped.items():
        items = sorted(items, key=_row_sort_key, reverse=True)
        streams = len(items)
        issue_streams = sum(1 for row in items if _row_is_issue(row))
        stops = sum(1 for row in items if _has_action(row, {"stop"}))
        exits = sum(1 for row in items if _has_action(row, {"exit"}))
        relapses = sum(1 for row in items if _has_action(row, {"relapse"}))
        warning_errors = sum(1 for row in items if _has_action(row, {"warning_error"}))
        risk_score = issue_streams * 2 + stops * 4 + relapses * 3 + warning_errors * 2
        users.append({
            "user": user,
            "streams": streams,
            "correct": sum(1 for row in items if _row_is_correct(row)),
            "issue_streams": issue_streams,
            "technical_issues": sum(len(row.get("violations_committed") or []) for row in items),
            "warnings": sum(1 for row in items if _has_action(row, {"warn", "warning_error"})),
            "stops": stops,
            "resolved": sum(1 for row in items if _has_action(row, {"resolved", "resolved_later"})),
            "exits": exits,
            "resolution_changes": sum(1 for row in items if _has_action(row, {"resolution_change"})),
            "relapses": relapses,
            "active": sum(1 for row in items if not row.get("ended_at")),
            "problem_rate": round((issue_streams / streams * 100.0), 1) if streams else 0.0,
            "risk_score": risk_score,
            "last_seen_at": str(items[0].get("updated_at") or items[0].get("last_seen_at") or items[0].get("started_at") or ""),
            "clients": _top_values(items, "client"),
            "servers": _top_named_values(items, "server_id", "server_name"),
            "trend": [_trend_item(row) for row in items[:12]],
        })
    return users


def _sort_users(users: List[Dict[str, Any]], mode: str) -> List[Dict[str, Any]]:
    if mode == "streams_desc":
        return sorted(users, key=lambda item: (int(item.get("streams") or 0), str(item.get("last_seen_at") or "")), reverse=True)
    if mode == "recent_desc":
        return sorted(users, key=lambda item: str(item.get("last_seen_at") or ""), reverse=True)
    if mode == "user_asc":
        return sorted(users, key=lambda item: str(item.get("user") or "").lower())
    return sorted(
        users,
        key=lambda item: (
            int(item.get("risk_score") or 0),
            int(item.get("issue_streams") or 0),
            int(item.get("streams") or 0),
            str(item.get("last_seen_at") or ""),
        ),
        reverse=True,
    )


def _history_row(row: Dict[str, Any]) -> Dict[str, Any]:
    action_records = [
        {
            "action": str(item.get("action") or ""),
            "source": str(item.get("source") or ""),
            "at": str(item.get("at") or ""),
        }
        for item in row.get("actions") or []
        if isinstance(item, dict) and str(item.get("action") or "").strip()
    ]
    return {
        "id": str(row.get("id") or ""),
        "at": str(row.get("updated_at") or row.get("last_seen_at") or row.get("started_at") or ""),
        "started_at": str(row.get("started_at") or ""),
        "ended_at": str(row.get("ended_at") or ""),
        "user": _user_label(row),
        "title": str(row.get("title") or "Stream"),
        "server_id": str(row.get("server_id") or ""),
        "server_name": str(row.get("server_name") or row.get("server_id") or "Server"),
        "client": str(row.get("client") or ""),
        "device": str(row.get("device") or ""),
        "quality": _quality(row),
        "outcome": _row_outcome(row),
        "tags": list(row.get("tags") or []),
        "violations_committed": list(row.get("violations_committed") or []),
        "actions": [item["action"] for item in action_records],
        "action_records": action_records,
        "duration_seconds": _to_number(row.get("duration_seconds")),
        "playback_percent": _to_number(row.get("playback_percent")),
        "rule_name": str(row.get("last_rule_name") or ""),
        "reason": str(row.get("last_decision_reason") or ""),
    }


def _trend_item(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(row.get("id") or ""),
        "status": _row_outcome(row),
        "label": _outcome_label(_row_outcome(row)),
        "at": str(row.get("updated_at") or row.get("started_at") or ""),
        "title": str(row.get("title") or "Stream"),
        "server": str(row.get("server_name") or row.get("server_id") or ""),
        "client": str(row.get("client") or ""),
        "device": str(row.get("device") or ""),
        "quality": _quality(row),
    }


def _facets(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    return {
        "servers": _facet_named(rows, "server_id", "server_name"),
        "users": _facet_simple(rows, "user"),
        "clients": _facet_simple(rows, "client"),
    }


def _facet_simple(rows: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    counts = Counter(str(row.get(key) or "").strip() for row in rows)
    counts.pop("", None)
    return [
        {"id": value, "name": value, "count": count}
        for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))
    ]


def _facet_named(rows: List[Dict[str, Any]], id_key: str, name_key: str) -> List[Dict[str, Any]]:
    counts: Counter[str] = Counter()
    names: Dict[str, str] = {}
    for row in rows:
        item_id = str(row.get(id_key) or "").strip()
        if not item_id:
            continue
        counts[item_id] += 1
        names.setdefault(item_id, str(row.get(name_key) or item_id))
    return [
        {"id": item_id, "name": names.get(item_id, item_id), "count": count}
        for item_id, count in sorted(counts.items(), key=lambda item: (-item[1], names.get(item[0], item[0]).lower()))
    ]


def _top_values(rows: List[Dict[str, Any]], key: str, limit: int = 4) -> List[Dict[str, Any]]:
    return _facet_simple(rows, key)[:limit]


def _top_named_values(rows: List[Dict[str, Any]], id_key: str, name_key: str, limit: int = 4) -> List[Dict[str, Any]]:
    return _facet_named(rows, id_key, name_key)[:limit]


def _row_outcome(row: Dict[str, Any]) -> str:
    actions = _actions(row)
    if "stop" in actions:
        return "stop"
    if "warning_error" in actions:
        return "error"
    if "relapse" in actions:
        return "relapse"
    if "partial_resolved" in actions:
        return "partial"
    if "resolution_change" in actions:
        return "resolution_change"
    if "resolved" in actions or "resolved_later" in actions:
        return "resolved"
    if "warn" in actions:
        return "warning"
    if row.get("violations_committed"):
        return "issue"
    if _row_is_correct(row):
        return "correct"
    if "exit" in actions:
        return "exit"
    return "observed"


def _outcome_label(outcome: str) -> str:
    return {
        "correct": "Corretto",
        "warning": "Avviso",
        "stop": "Stop del Guard",
        "resolved": "Risolto",
        "resolution_change": "Cambio risoluzione",
        "partial": "Risolto parzialmente",
        "exit": "Uscito",
        "relapse": "Ricaduta",
        "error": "Errore",
        "issue": "Problema rilevato",
        "observed": "Osservato",
    }.get(outcome, outcome or "Osservato")


def _row_is_correct(row: Dict[str, Any]) -> bool:
    tags = {str(tag or "").lower() for tag in row.get("tags") or []}
    return "corretta" in tags and not row.get("violations_committed")


def _row_is_issue(row: Dict[str, Any]) -> bool:
    return bool(row.get("violations_committed")) or any(action in ISSUE_ACTIONS for action in _actions(row))


def _row_is_interesting(row: Dict[str, Any]) -> bool:
    return _row_is_issue(row) or any(action in INTERESTING_NON_ISSUE_ACTIONS for action in _actions(row))


def _has_action(row: Dict[str, Any], actions: Iterable[str]) -> bool:
    wanted = {str(action or "") for action in actions}
    return any(action in wanted for action in _actions(row))


def _actions(row: Dict[str, Any]) -> List[str]:
    result = []
    for action in row.get("actions") or []:
        if isinstance(action, dict):
            text = str(action.get("action") or "").strip()
            if text:
                result.append(text)
    return result


def _row_sort_key(row: Dict[str, Any]) -> str:
    return str(row.get("updated_at") or row.get("last_seen_at") or row.get("started_at") or "")


def _user_label(row: Dict[str, Any]) -> str:
    return str(row.get("user") or "Utente sconosciuto").strip() or "Utente sconosciuto"


def _quality(row: Dict[str, Any]) -> str:
    if row.get("quality"):
        return str(row.get("quality"))
    try:
        height = int(row.get("source_height") or row.get("video_height") or 0)
    except (TypeError, ValueError):
        height = 0
    return f"{height}p" if height > 0 else ""


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "si", "sì"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _bounded_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _to_number(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
