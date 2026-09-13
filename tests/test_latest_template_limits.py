"""Resource limits for user-defined Latest notification templates."""

from pathlib import Path

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


ADVANCED_NOTIFICATION_TEMPLATE = """
{% macro pick_audio(version) -%}
{%- set candidates = [] -%}
{%- if version.audio_details -%}
  {%- set candidates = version.audio_details.split(' · ') -%}
{%- elif version.audio_langs -%}
  {%- set candidates = version.audio_langs.split(',') -%}
{%- endif -%}
{%- set choice = namespace(selected=None) -%}
{%- for audio in candidates -%}
  {%- set cleaned = audio|trim -%}
  {%- if choice.selected is none and 'ita' in cleaned|lower -%}
    {%- set choice.selected = cleaned -%}
  {%- endif -%}
{%- endfor -%}
{%- if choice.selected is none and candidates|length -%}
  {%- set choice.selected = candidates[0]|trim -%}
{%- endif -%}
{{- choice.selected -}}
{%- endmacro %}
{% set ratings = namespace(values=[]) %}
{% if trakt_rating %}
  {% set ratings.values = ratings.values + ['<b>' ~ trakt_rating ~ '</b> Trakt'] %}
{% endif %}
{% if metacritic_rating %}
  {% set score = metacritic_rating|float / 10 %}
  {% set score_text = '%.1f'|format(score) %}
  {% set ratings.values = ratings.values + ['<b>' ~ score_text ~ '</b> MetaCritic'] %}
{% endif %}
{{ ratings.values|join(' - ')|safe }}
{{ overview|default('')|striptags|truncate(245, False, ' [...]') }}
{% for version in versions %}
Audio - {{ pick_audio(version) }}
{% endfor %}
"""

MIGRATED_COMPLETE_TEMPLATE = (
    Path(__file__).parent / "fixtures" / "latest_complete_notification_template.j2"
).read_text(encoding="utf-8")


def test_template_validation_rejects_expensive_multiplication():
    with pytest.raises(TemplateResourceLimitError, match="Mul"):
        validate_template("{{ 'x' * 20000000 }}")


def test_template_validation_rejects_oversized_source():
    with pytest.raises(TemplateResourceLimitError, match="troppo lungo"):
        validate_template("x" * (MAX_TEMPLATE_SOURCE_LENGTH + 1))


def test_template_rendering_stops_before_returning_oversized_output():
    with pytest.raises(TemplateResourceLimitError, match="Output"):
        render_template(
            "{{ first }}{{ second }}",
            {
                "first": "x" * (MAX_TEMPLATE_OUTPUT_LENGTH // 2 + 1),
                "second": "x" * (MAX_TEMPLATE_OUTPUT_LENGTH // 2 + 1),
            },
            strict=True,
        )


def test_template_rendering_preserves_safe_templates():
    assert render_template("Hello {{ title | upper }}", {"title": "OctoHubs"}) == "Hello OCTOHUBS"


def test_template_rendering_preserves_advanced_notification_contract():
    rendered = render_template(
        ADVANCED_NOTIFICATION_TEMPLATE,
        {
            "trakt_rating": "8.4",
            "metacritic_rating": "81",
            "overview": "<script>ignored</script>A film",
            "versions": [
                {
                    "audio_details": "English DTS · Italiano AC3",
                    "audio_langs": "",
                }
            ],
        },
        strict=True,
    )

    assert "<b>8.4</b> Trakt - <b>8.1</b> MetaCritic" in rendered
    assert "ignoredA film" in rendered
    assert "Audio - Italiano AC3" in rendered


def test_template_rendering_preserves_the_migrated_complete_series_preset():
    rendered = render_template(
        MIGRATED_COMPLETE_TEMPLATE,
        {
            "type": "series",
            "title": "Fauda",
            "year": "2015",
            "genres": "Dramma · Azione",
            "overview": "Una serie",
            "season_count": "1",
            "episodes_compact": "S01 E01-02",
            "season_number": "1",
            "versions": [
                {
                    "quality": "2160p",
                    "video_codec": "HEVC",
                    "audio_details": "English DTS · Italiano AC3",
                    "audio_langs": "eng,ita",
                },
                {
                    "quality": "2160p",
                    "video_codec": "HEVC",
                    "audio_details": "Italiano AAC",
                    "audio_langs": "ita",
                },
                {
                    "quality": "1080p",
                    "video_codec": "H264",
                    "audio_details": "Italiano AC3",
                    "audio_langs": "ita",
                },
            ],
            "library_name": "Serie TV",
            "update_label": "Nuovi episodi",
        },
        strict=True,
    )

    assert "Fauda" in rendered
    assert rendered.count("<b>Versione 2160p</b>") == 1
    assert rendered.count("<b>Versione 1080p</b>") == 1
    assert "Audio – Italiano AC3" in rendered


def test_template_iteration_is_bounded_for_context_and_split_values():
    rendered_context = render_template(
        "{% for value in values %}x{% endfor %}",
        {"values": list(range(1_000))},
        strict=True,
    )
    rendered_split = render_template(
        "{% set values = text.split(',') %}{% for value in values %}x{% endfor %}",
        {"text": ",".join("x" for _ in range(1_000))},
        strict=True,
    )

    assert len(rendered_context) == 256
    assert len(rendered_split) == 256


@pytest.mark.parametrize(
    ("template", "context"),
    [
        (
            "{% set values = values[:] %}{% for value in values %}x{% endfor %}",
            {"values": list(range(1_000))},
        ),
        (
            "{% set values = text|lower %}{% for value in values %}x{% endfor %}",
            {"text": "X" * 1_000},
        ),
        (
            "{% set values = source|safe %}{% for value in values %}x{% endfor %}",
            {"source": "X" * 1_000},
        ),
    ],
)
def test_template_iteration_cannot_bypass_bounds_via_slices_or_filters(template, context):
    assert len(render_template(template, context, strict=True)) == 256


@pytest.mark.parametrize(
    "template",
    [
        "{{ range(1000)|list }}",
        "{{ value.center(1000000, 'x') }}",
        "{% macro recurse() %}{{ recurse() }}{% endmacro %}{{ recurse() }}",
        "{% macro a() %}{{ b() }}{% endmacro %}{% macro b() %}{{ a() }}{% endmacro %}{{ a() }}",
        "{{ '%1000000s'|format(value) }}",
        "{{ values|join(separator) }}",
        "{{ '%1000000s' % value }}",
        "{% for a in values %}{% for b in values %}{% for c in values %}x{% endfor %}{% endfor %}{% endfor %}",
        "{% for value in values %}{% set ns.items = ns.items + [title] %}{% endfor %}",
        "{% set ns=namespace(items=[]) %}{% for value in values %}{% if (ns.items|length < 2) or true %}{% set ns.items=ns.items+[value] %}{% endif %}{% endfor %}",
        "{% set ns=namespace(items=[], guard=[]) %}{% for value in values %}{% if ns.guard|length < 2 %}{% set ns.items=ns.items+[value] %}{% endif %}{% endfor %}",
        "{% set ns=namespace(items=[]) %}{% for value in values %}{% if ns.items|length < 33 %}{% set ns.items=ns.items+[value] %}{% endif %}{% endfor %}",
        "{% set values = title ~ title %}{% for value in values %}x{% endfor %}",
        "{% macro duplicate() %}{{ title }}{{ title }}{% endmacro %}{% set values = duplicate() %}{% for value in values %}x{% endfor %}",
        "{% macro inner(values) %}{% for c in values %}x{% endfor %}{% endmacro %}{% for a in values %}{% for b in values %}{{ inner(values) }}{% endfor %}{% endfor %}",
        "{% macro recurse() %}{{ ns.split() }}{% endmacro %}{% set ns=namespace(split=recurse) %}{{ ns.split() }}",
        "{% macro recurse() %}{{ d.split() }}{% endmacro %}{% set d={'split': recurse} %}{{ d.split() }}",
        "{% set expanded=value ~ value %}{% set alias=expanded %}{% for c in alias %}x{% endfor %}",
        "{% set alias=(value ~ value)[:] %}{% for c in alias %}x{% endfor %}",
        "{% set alias=value if ok else value ~ value %}{% for c in alias %}x{% endfor %}",
        "{% macro duplicate() %}{{ value }}{{ value }}{% endmacro %}{% set expanded=duplicate() %}{% set alias=expanded %}{% for c in alias %}x{% endfor %}",
        "{% set mapping={'payload': value ~ value} %}{% for c in mapping.payload %}x{% endfor %}",
        "{% set expanded=value ~ value %}{% set mapping={'payload': expanded} %}{% for c in mapping.payload %}x{% endfor %}",
        "{% set expanded=value ~ value %}{% set ns=namespace(payload=expanded) %}{% for c in ns.payload %}x{% endfor %}",
        "{% for c in '" + ("a" * 257) + "' %}x{% endfor %}",
        "{% set ns=namespace(values=[]) %}"
        + "{% set ns.values=ns.values+[1,2,3,4,5,6,7,8] %}" * 16
        + "{% for a in ns.values %}{% for b in ns.values %}x{% endfor %}{% endfor %}",
        "{% for a in outer %}{% for b in inner %}{% set sink=payload ~ payload %}{% endfor %}{% endfor %}",
        "{% for value in values %}"
        + "{% if needle in haystack %}{% endif %}" * 9
        + "{% endfor %}",
        "{% for value in values %}{% if needle is in(haystack) %}{% endif %}{% endfor %}",
        "{% macro expand() %}" + "{{ payload }}" * 9 + "{% endmacro %}{{ expand() }}",
        "{% macro expand(values) %}{% for value in values %}{{ payload }}{% endfor %}{% endmacro %}{{ expand(values) }}",
        "{% set row=[payload,payload,payload,payload,payload,payload,payload,payload] %}{% set matrix=[row,row,row,row,row,row,row,row] %}{{ matrix }}",
        "{% set row=[payload,payload,payload,payload,payload,payload,payload,payload] %}{% set matrix=[row,row,row,row,row,row,row,row] %}{% set ignored=matrix ~ '' %}",
        "{% set values=[payload,payload,payload,payload,payload,payload,payload,payload] %}{% set ns=namespace() %}{% set ns.payload=values %}{{ ns }}",
        "{% set values=[payload,payload,payload,payload,payload,payload,payload,payload] %}{% set ns=namespace() %}{% set ns.payload=values %}{% set ignored=ns ~ '' %}",
        "{% set a=payload ~ payload ~ payload ~ payload %}{% set b=a ~ a ~ a ~ a %}{% set c=b ~ b ~ b ~ b %}{{ c|length }}",
    ],
)
def test_advanced_template_policy_rejects_unbounded_variants(template):
    with pytest.raises(TemplateResourceLimitError):
        validate_template(template)


def test_template_rendering_has_one_aggregate_iteration_budget():
    with pytest.raises(TemplateResourceLimitError, match="Budget di lavoro"):
        render_template(
            "{% for outer in values %}{% for inner in values %}{% endfor %}{% endfor %}",
            {"values": list(range(256))},
            strict=True,
        )


def test_template_rendering_rejects_one_oversized_context_string():
    with pytest.raises(TemplateResourceLimitError, match="Valore del contesto"):
        render_template("{{ value }}", {"value": "x" * 65_537}, strict=True)


def test_filter_budget_counts_nested_template_collections():
    template = """
    {% set row = [payload, payload, payload, payload, payload, payload, payload, payload] %}
    {% set matrix = [row, row, row, row, row, row, row, row] %}
    {% set ignored = matrix|safe %}
    """
    with pytest.raises(TemplateResourceLimitError, match="Budget di lavoro"):
        render_template(template, {"payload": "x" * 32_768}, strict=True)


def test_filter_budget_handles_small_namespace_values():
    rendered = render_template(
        "{% set ns=namespace(value='ok') %}{{ ns|safe }}",
        {},
        strict=True,
    )
    assert "ok" in rendered


def test_single_brace_tokens_are_plain_text_not_runtime_compatibility_syntax():
    assert normalize_template("Hello {title}") == "Hello {title}"
    assert render_template("Hello {title}", {"title": "OctoHubs"}) == "Hello {title}"


@pytest.mark.parametrize("template", [
    "{{ value | replace('x', 'xx') }}",
    "{{ dynamic_format | format(value) }}",
    "{{ " + " ~ ".join(["value"] * 17) + " }}",
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
