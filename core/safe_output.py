"""Single-line, bounded compatibility output for legacy console diagnostics."""

from __future__ import annotations

import builtins
from typing import Any, TextIO

from core.log_sanitization import TrustedDiagnosticText, sanitize_diagnostic_text


def safe_print(
    *values: Any,
    sep: str = " ",
    end: str = "\n",
    file: TextIO | None = None,
    flush: bool = False,
) -> None:
    """Print diagnostics only after applying the canonical log boundary."""
    rendered = sep.join(
        str(value)
        if isinstance(value, TrustedDiagnosticText)
        else sanitize_diagnostic_text(value)
        for value in values
    )
    builtins.print(rendered, end=end, file=file, flush=flush)


__all__ = ["safe_print"]
