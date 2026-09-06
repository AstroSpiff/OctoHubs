"""Prevent unredacted exception text and traceback sinks in runtime modules."""

from __future__ import annotations

import ast
import io
import logging
from pathlib import Path

from core.log_sanitization import (
    format_exception_for_log,
    install_log_record_sanitizer,
)
from core.safe_output import safe_print


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {"alembic", "node_modules", "scripts", "tests", "venv", ".venv"}
LOG_METHODS = {"critical", "debug", "error", "exception", "info", "warning"}
SAFE_CALLS = {
    "format_exception_for_log",
    "safe_http_error_message",
    "sanitize_diagnostic_text",
    "sanitize_url_for_log",
    "type",
}


def _call_name(call: ast.Call) -> str:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return ""


def _contains_unprotected_name(node: ast.AST, name: str) -> bool:
    if isinstance(node, ast.Call) and _call_name(node) in SAFE_CALLS:
        return False
    if isinstance(node, ast.Name):
        return node.id == name
    return any(_contains_unprotected_name(child, name) for child in ast.iter_child_nodes(node))


def _has_truthy_exc_info(call: ast.Call) -> bool:
    for keyword in call.keywords:
        if keyword.arg != "exc_info":
            continue
        value = keyword.value
        return not (isinstance(value, ast.Constant) and value.value in (False, None))
    return False


def test_runtime_exception_logs_use_the_central_redaction_boundary():
    unsafe: list[str] = []
    for path in PROJECT_ROOT.rglob("*.py"):
        if any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        if path == PROJECT_ROOT / "core" / "safe_output.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for handler in (node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)):
            for call in (node for node in ast.walk(handler) if isinstance(node, ast.Call)):
                call_name = _call_name(call)
                is_log_sink = call_name == "print" or call_name in LOG_METHODS
                if not is_log_sink:
                    continue
                exposes_named_exception = bool(handler.name) and any(
                    _contains_unprotected_name(argument, handler.name or "")
                    for argument in (*call.args, *[keyword.value for keyword in call.keywords])
                )
                if call_name == "exception" or _has_truthy_exc_info(call) or exposes_named_exception:
                    unsafe.append(f"{path.relative_to(PROJECT_ROOT)}:{call.lineno}")

    assert unsafe == [], "Unredacted exception log sinks: " + ", ".join(unsafe)


def test_runtime_logging_boundary_neutralizes_messages_arguments_and_secrets():
    previous_factory = logging.getLogRecordFactory()
    stream = io.StringIO()
    logger = logging.getLogger("octohubs.test.log-boundary")
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    old_handlers = list(logger.handlers)
    old_level = logger.level
    old_propagate = logger.propagate
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        install_log_record_sanitizer()
        logger.info("legit\n[FORGED] token=message-secret")
        logger.info(
            "payload=%s",
            {"password": "argument-secret", "label": "safe\n[FORGED]"},
        )
    finally:
        logging.setLogRecordFactory(previous_factory)
        logger.handlers = old_handlers
        logger.setLevel(old_level)
        logger.propagate = old_propagate

    lines = stream.getvalue().splitlines()
    assert len(lines) == 2
    assert "[REDACTED]" in lines[0]
    assert "message-secret" not in lines[0]
    assert "argument-secret" not in lines[1]
    assert "password': '[REDACTED]'" in lines[1]
    assert all("\n" not in line for line in lines)


def test_redacted_exception_formatter_preserves_full_traceback_layout():
    try:
        raise RuntimeError("failed\n[FORGED] token=trace-secret")
    except RuntimeError as exc:
        rendered = format_exception_for_log(exc)

    assert "Traceback (most recent call last):" in rendered
    assert "test_redacted_exception_formatter_preserves_full_traceback_layout" in rendered
    assert "\n" in rendered
    assert "trace-secret" not in rendered
    assert "[REDACTED]" in rendered


def test_safe_console_boundary_preserves_only_trusted_traceback_layout(capsys):
    try:
        raise RuntimeError("failed\n[FORGED] token=trace-secret")
    except RuntimeError as exc:
        rendered = format_exception_for_log(exc)

    safe_print("context\n[FORGED]", rendered, sep="\n")
    output = capsys.readouterr().out
    assert output.startswith("context [FORGED]\nTraceback (most recent call last):")
    assert "trace-secret" not in output
    assert "[REDACTED]" in output


def test_application_factory_installs_the_process_wide_log_boundary():
    tree = ast.parse(
        (PROJECT_ROOT / "runtime" / "app_setup.py").read_text(encoding="utf-8")
    )
    create_app = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "create_app"
    )
    assert any(
        isinstance(node, ast.Call)
        and _call_name(node) == "install_log_record_sanitizer"
        for node in ast.walk(create_app)
    )


def test_dynamic_runtime_prints_use_the_safe_output_boundary():
    """Modules with request/upstream f-string prints must alias safe_print."""
    unsafe: list[str] = []
    for path in PROJECT_ROOT.rglob("*.py"):
        if any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        if path == PROJECT_ROOT / "core" / "safe_output.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        has_dynamic_print = any(
            isinstance(node, ast.Call)
            and _call_name(node) == "print"
            and any(not isinstance(argument, ast.Constant) for argument in node.args)
            for node in ast.walk(tree)
        )
        if not has_dynamic_print:
            continue
        aliases_safe_print = any(
            isinstance(node, ast.ImportFrom)
            and node.module == "core.safe_output"
            and any(alias.name == "safe_print" and alias.asname == "print" for alias in node.names)
            for node in tree.body
        )
        if not aliases_safe_print:
            unsafe.append(str(path.relative_to(PROJECT_ROOT)))

    assert unsafe == [], "Dynamic print sinks without safe_print: " + ", ".join(unsafe)
