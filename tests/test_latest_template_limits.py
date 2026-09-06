"""Resource limits for user-defined Latest notification templates."""

import pytest

from emby_latest.templates import (
    MAX_TEMPLATE_OUTPUT_LENGTH,
    MAX_TEMPLATE_SOURCE_LENGTH,
    TemplateResourceLimitError,
    apply_template,
    normalize_template,
    render_template,
    validate_template,
)


def test_template_validation_rejects_expensive_multiplication():
    with pytest.raises(TemplateResourceLimitError, match="Mul"):
        validate_template("{{ 'x' * 20000000 }}")


def test_template_validation_rejects_oversized_source():
    with pytest.raises(TemplateResourceLimitError, match="troppo lungo"):
        validate_template("x" * (MAX_TEMPLATE_SOURCE_LENGTH + 1))


def test_template_rendering_stops_before_returning_oversized_output():
    with pytest.raises(TemplateResourceLimitError, match="Output"):
        render_template(
            "{{ value }}",
            {"value": "x" * (MAX_TEMPLATE_OUTPUT_LENGTH + 1)},
            strict=True,
        )


def test_template_rendering_preserves_safe_templates():
    assert render_template("Hello {{ title | upper }}", {"title": "OctoHubs"}) == "Hello OCTOHUBS"


def test_single_brace_tokens_are_plain_text_not_runtime_compatibility_syntax():
    assert normalize_template("Hello {title}") == "Hello {title}"
    assert render_template("Hello {title}", {"title": "OctoHubs"}) == "Hello {title}"


@pytest.mark.parametrize("template", [
    "{{ value | replace('x', 'xx') }}",
    "{{ '%s' | format(value) }}",
    "{{ value ~ value }}",
])
def test_template_validation_rejects_expanding_operators_and_filters(template):
    with pytest.raises(TemplateResourceLimitError):
        validate_template(template)


def test_bounded_fallback_rejects_expansion_before_replacement():
    with pytest.raises(TemplateResourceLimitError, match="Output"):
        apply_template(
            "{{ value }}" * 128,
            {"value": "x" * (MAX_TEMPLATE_OUTPUT_LENGTH // 2)},
        )
