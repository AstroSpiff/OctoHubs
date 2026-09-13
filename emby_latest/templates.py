"""
Template rendering for Latest Publications messages.

This module handles Jinja2 template rendering for notification messages.
"""

import re
from typing import Any, Dict, Optional
from jinja2 import Undefined, TemplateSyntaxError
from jinja2.sandbox import SandboxedEnvironment
from markupsafe import Markup

from emby_latest.template_policy import (
    ALLOWED_FILTERS,
    MAX_TEMPLATE_MACRO_OUTPUT_PARTS,
    TemplateResourceLimitError,
    bound_template_context,
    bounded_template_filter,
    consume_template_work,
    template_work_units,
    template_iteration_budget,
    validate_template_ast,
)


# Image token constants - tokens that represent image URLs
LATEST_IMAGE_TOKENS = (
    "image_url",
    "tmdb_poster_url",
    "poster_url",
    "tmdb_backdrop_url",
    "backdrop_url",
    "tmdb_logo_url",
    "logo_url",
    "tmdb_banner_url",
    "banner_url",
    "tmdb_thumb_url",
    "thumb_url"
)

# Regex patterns for template token matching
_LATEST_JINJA_TOKEN_REGEX = re.compile(r"{{\s*([a-zA-Z0-9_]+)[^}]*}}")

# Global template environment singleton
_TEMPLATE_ENV = None
MAX_TEMPLATE_SOURCE_LENGTH = 16_384
MAX_TEMPLATE_OUTPUT_LENGTH = 65_536
MAX_TEMPLATE_CONTEXT_SIZE = 262_144
MAX_TEMPLATE_CONTEXT_ITEMS = 5_000
MAX_TEMPLATE_CONTEXT_STRING_LENGTH = 65_536


def _finalize_template_value(value: Any) -> Any:
    """Charge an expression before Jinja converts or escapes its output."""
    consume_template_work(template_work_units((value,)))
    return value


class _LatestTemplateEnvironment(SandboxedEnvironment):
    """Keep `.split()` bound to actual strings at runtime."""

    def getattr(self, obj: Any, attribute: str) -> Any:
        if attribute == "split":
            if not isinstance(obj, str):
                raise TemplateResourceLimitError("Receiver split non consentito")
            return bound_template_context(str(obj)).split
        return super().getattr(obj, attribute)

    def call(self, context: Any, obj: Any, *args: Any, **kwargs: Any) -> Any:
        from jinja2.runtime import Macro

        if isinstance(obj, Macro):
            consume_template_work(MAX_TEMPLATE_MACRO_OUTPUT_PARTS)
        return super().call(context, obj, *args, **kwargs)


def _validate_context_budget(value: Any, *, depth: int = 0) -> tuple[int, int]:
    if depth > 8:
        raise TemplateResourceLimitError("Contesto template troppo annidato")
    if value is None or isinstance(value, (bool, int, float)):
        return 16, 1
    if isinstance(value, str):
        if len(value) > MAX_TEMPLATE_CONTEXT_STRING_LENGTH:
            raise TemplateResourceLimitError("Valore del contesto template troppo grande")
        return len(value), 1
    if isinstance(value, dict):
        size = 0
        count = 1
        for key, item in value.items():
            child_size, child_count = _validate_context_budget(item, depth=depth + 1)
            size += len(str(key)) + child_size
            count += child_count
        return size, count
    if isinstance(value, (list, tuple, set)):
        size = 0
        count = 1
        for item in value:
            child_size, child_count = _validate_context_budget(item, depth=depth + 1)
            size += child_size
            count += child_count
        return size, count
    return len(str(value)), 1


def validate_template(template: str) -> str:
    """Validate source size and reject expensive Jinja constructs."""
    normalized = normalize_template(template)
    if len(normalized) > MAX_TEMPLATE_SOURCE_LENGTH:
        raise TemplateResourceLimitError("Template troppo lungo")
    parsed = get_template_env().parse(normalized)
    validate_template_ast(parsed)
    return normalized


def get_template_env():
    """
    Get or create the Jinja2 template environment.

    Returns:
        SandboxedEnvironment configured for Latest templates
    """
    global _TEMPLATE_ENV
    if _TEMPLATE_ENV is None:
        env = _LatestTemplateEnvironment(
            autoescape=True,
            finalize=_finalize_template_value,
            undefined=Undefined,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True
        )

        def _filter_safe(value):
            if value is None:
                return Markup("")
            return Markup(str(value))

        env.filters["safe"] = _filter_safe
        for filter_name in ALLOWED_FILTERS:
            template_filter = env.filters.get(filter_name)
            if template_filter is not None:
                env.filters[filter_name] = bounded_template_filter(template_filter)
        env.globals["nl"] = "\n"
        env.globals["br"] = Markup("<br>")
        _TEMPLATE_ENV = env

    return _TEMPLATE_ENV


def normalize_template(template: Optional[str]) -> str:
    """Return the canonical Jinja2 template source."""
    return template or ""


def template_has_image_token(template: Optional[str]) -> bool:
    """
    Check if template contains image URL tokens.

    Args:
        template: Template string to check

    Returns:
        True if template contains at least one image token
    """
    if not template:
        return False

    normalized = normalize_template(template)
    for match in _LATEST_JINJA_TOKEN_REGEX.finditer(normalized):
        token = match.group(1)
        if token in LATEST_IMAGE_TOKENS:
            return True
    return False


def strip_image_tokens(template: Optional[str]) -> str:
    """
    Remove image URL tokens from template.

    Args:
        template: Template string

    Returns:
        Template with image tokens removed
    """
    if not template:
        return ""

    normalized = normalize_template(template)
    output = normalized

    for token in LATEST_IMAGE_TOKENS:
        # Remove {{token...}} patterns
        output = re.sub(r"{{\s*" + re.escape(token) + r"[^}]*}}", "", output)

    return output


def extract_image_url(template: Optional[str], context: Dict[str, Any]) -> str:
    """
    Extract first available image URL from template context.

    Args:
        template: Template string
        context: Context dict with variable values

    Returns:
        First available image URL from context, or empty string
    """
    if not template or not context:
        return ""

    normalized = normalize_template(template)
    seen = set()

    for match in _LATEST_JINJA_TOKEN_REGEX.finditer(normalized):
        token = match.group(1)
        if token in seen or token not in LATEST_IMAGE_TOKENS:
            continue

        seen.add(token)
        value = context.get(token)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return ""


def render_template(template: str, context: Dict[str, Any], strict: bool = False) -> str:
    """
    Render a Jinja2 template with given context.

    Args:
        template: Template string
        context: Context dict for rendering
        strict: If True, raise exceptions on errors

    Returns:
        Rendered template string
    """
    if not template:
        return ""

    normalized = validate_template(template)
    env = get_template_env()

    try:
        context_size, context_items = _validate_context_budget(context or {})
        if context_size > MAX_TEMPLATE_CONTEXT_SIZE or context_items > MAX_TEMPLATE_CONTEXT_ITEMS:
            raise TemplateResourceLimitError("Contesto template troppo grande")
        chunks = []
        output_size = 0
        bounded_context = bound_template_context(context or {})
        with template_iteration_budget():
            for chunk in env.from_string(normalized).generate(bounded_context):
                output_size += len(chunk)
                if output_size > MAX_TEMPLATE_OUTPUT_LENGTH:
                    raise TemplateResourceLimitError("Output template troppo grande")
                chunks.append(chunk)
        return "".join(chunks)
    except (TemplateSyntaxError, ValueError) as exc:
        if strict:
            raise exc
        return ""
    except Exception as exc:
        if strict:
            raise exc
        return ""


def apply_template(template: str, context: Dict[str, Any]) -> str:
    """Apply bounded replacement to canonical Jinja2 value tokens."""
    text = template or ""
    if len(text) > MAX_TEMPLATE_SOURCE_LENGTH:
        raise TemplateResourceLimitError("Template troppo lungo")
    context_size, context_items = _validate_context_budget(context or {})
    if context_size > MAX_TEMPLATE_CONTEXT_SIZE or context_items > MAX_TEMPLATE_CONTEXT_ITEMS:
        raise TemplateResourceLimitError("Contesto template troppo grande")
    if not context:
        return text

    for key, value in context.items():
        replacement = str(value) if value is not None else ""
        pattern = re.compile(r"{{\s*" + re.escape(str(key)) + r"[^}]*}}")
        matches = tuple(pattern.finditer(text))
        if matches:
            _ensure_bounded_replacement(
                text,
                len(matches),
                sum(match.end() - match.start() for match in matches),
                replacement,
            )
            text = pattern.sub(replacement, text)

    return text


def _ensure_bounded_replacement(
    text: str,
    count: int,
    removed_length: int,
    replacement: str,
) -> None:
    """Reject an expansion before ``replace``/``re.sub`` allocates it."""
    projected_length = len(text) - removed_length + count * len(replacement)
    if projected_length > MAX_TEMPLATE_OUTPUT_LENGTH:
        raise TemplateResourceLimitError("Output template troppo grande")
