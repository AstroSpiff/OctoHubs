"""
Template rendering for Latest Publications messages.

This module handles Jinja2 template rendering for notification messages.
Migrated from app.py template functions.
"""

import re
from typing import Any, Dict, Optional
from jinja2 import Undefined, TemplateSyntaxError
from jinja2.sandbox import SandboxedEnvironment
from markupsafe import Markup


# Image token constants - tokens that represent image URLs
LATEST_IMAGE_TOKENS = (
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
_LATEST_LEGACY_TOKEN_REGEX = re.compile(r"(?<!{){\s*([a-zA-Z0-9_][^}]*)\s*}(?!})")
_LATEST_JINJA_TOKEN_REGEX = re.compile(r"{{\s*([a-zA-Z0-9_]+)[^}]*}}")

# Global template environment singleton
_TEMPLATE_ENV = None


def get_template_env():
    """
    Get or create the Jinja2 template environment.

    Returns:
        SandboxedEnvironment configured for Latest templates
    """
    global _TEMPLATE_ENV
    if _TEMPLATE_ENV is None:
        env = SandboxedEnvironment(
            autoescape=True,
            undefined=Undefined,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True
        )

        def _filter_safe(value):
            if value is None:
                return Markup("")
            return Markup(str(value))

        def _filter_format(value, *args, **kwargs):
            fmt = "" if value is None else str(value)
            try:
                if args or kwargs:
                    try:
                        return fmt % (args[0] if len(args) == 1 and not kwargs else args or kwargs)
                    except Exception:
                        return fmt.format(*args, **kwargs)
                return fmt
            except Exception:
                return fmt

        env.filters["safe"] = _filter_safe
        env.filters["format"] = _filter_format
        env.globals["nl"] = "\n"
        env.globals["br"] = Markup("<br>")
        _TEMPLATE_ENV = env

    return _TEMPLATE_ENV


def normalize_template(template: Optional[str]) -> str:
    """
    Normalize template by converting legacy {token} syntax to Jinja2 {{token}} format.

    Args:
        template: Template string with legacy or Jinja2 syntax

    Returns:
        Normalized template string with Jinja2 syntax
    """
    text = template or ""
    # Convert legacy {token} to {{token}} (but not {{{token}}})
    return _LATEST_LEGACY_TOKEN_REGEX.sub(lambda match: f"{{{{ {match.group(1).strip()} }}}}", text)


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

    normalized = normalize_template(template)
    env = get_template_env()

    try:
        return env.from_string(normalized).render(context or {})
    except (TemplateSyntaxError, ValueError) as exc:
        if strict:
            raise exc
        return ""
    except Exception as exc:
        if strict:
            raise exc
        return ""


def apply_template(template: str, context: Dict[str, Any]) -> str:
    """
    Apply template with simple string replacement (legacy method).

    Args:
        template: Template string
        context: Context dict for replacement

    Returns:
        Template with tokens replaced
    """
    text = template or ""
    if not context:
        return text

    for key, value in context.items():
        # Legacy single-brace format
        legacy_token = f"{{{key}}}"
        text = text.replace(legacy_token, str(value) if value is not None else "")

        # Jinja2 double-brace format (simple replacement)
        text = re.sub(r"{{\s*" + re.escape(str(key)) + r"[^}]*}}", str(value) if value is not None else "", text)

    return text
