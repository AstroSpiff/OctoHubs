"""Indexer configuration helpers."""

from __future__ import annotations


def _prowlarr_configured(config):
    """Check if Prowlarr is configured."""
    return bool(config.get("PROWLARR_URL") and config.get("PROWLARR_API_KEY"))


def _jackett_configured(config):
    """Check if Jackett is configured."""
    return bool(config.get("JACKETT_URL") and config.get("JACKETT_API_KEY"))

def _should_use_prowlarr(config):
    """Determine if Prowlarr should be used."""
    rules = config.get("SEARCH_RULES", {})
    use_prowlarr_rule = rules.get("use_prowlarr", True)
    return _prowlarr_configured(config) and use_prowlarr_rule


def _should_use_jackett(config):
    """Determine if Jackett should be used."""
    rules = config.get("SEARCH_RULES", {})
    use_jackett_rule = rules.get("use_jackett", False)
    return _jackett_configured(config) and use_jackett_rule


def _search_rules(config):
    """Get search rules from config."""
    return config.get("SEARCH_RULES", {})
