"""Small reusable OpenAPI fragments for non-JSON external API responses."""

from __future__ import annotations


def binary_response(media_type: str, description: str) -> dict:
    """Describe an authenticated image or download without pretending it is JSON."""

    return {
        "description": description,
        "content": {
            media_type: {
                "schema": {"type": "string", "format": "binary"},
            }
        },
    }
