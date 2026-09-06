"""Opaque search-download reference security contracts."""

import json

import pytest

from search.download_references import (
    DownloadReferenceCodec,
    DownloadReferenceError,
    protect_download_references,
    resolve_download_reference,
    configure_download_reference_secret,
)


def test_provider_download_secrets_are_replaced_and_bound_to_one_subject():
    configure_download_reference_secret("r15-test-secret")
    raw_torrent = "https://indexer.example/download/42?apikey=secret-key&passkey=private"
    raw_magnet = "magnet:?xt=urn:btih:abc&tr=https%3A%2F%2Ftracker.example%2Fprivate-passkey"
    payload = {
        "torrent": raw_torrent,
        "downloadUrl": raw_torrent,
        "guid": raw_magnet,
        "web": "https://indexer.example/details/42?apikey=secret-key",
    }

    protected = protect_download_references(payload, owner_id=41)
    serialized = json.dumps(protected)

    assert raw_torrent not in serialized
    assert raw_magnet not in serialized
    assert "secret-key" not in serialized
    assert protected["has_torrent"] is True
    assert protected["has_magnet"] is True
    assert resolve_download_reference(41, protected["torrent_ref"], expected_kind="torrent") == raw_torrent
    assert resolve_download_reference(41, protected["magnet_ref"], expected_kind="magnet") == raw_magnet
    with pytest.raises(DownloadReferenceError):
        resolve_download_reference(42, protected["torrent_ref"])


def test_source_id_is_stable_non_reversible_and_bound_to_the_subject():
    configure_download_reference_secret("r22-source-id-secret")
    raw_torrent = "https://indexer.example/download/42?apikey=private-canary"
    payload = {"title": "Same title", "torrent": raw_torrent}

    first = protect_download_references(payload, owner_id=41)
    second = protect_download_references(payload, owner_id=41)
    other_owner = protect_download_references(payload, owner_id=42)

    assert first["source_id"].startswith("ohsid_")
    assert first["source_id"] == second["source_id"]
    assert first["torrent_ref"] != second["torrent_ref"]
    assert first["source_id"] != other_owner["source_id"]
    assert raw_torrent not in json.dumps(first)
    assert "private-canary" not in first["source_id"]


def test_persisted_source_id_is_rebound_when_history_is_read_by_a_subject():
    configure_download_reference_secret("r22-history-source-id-secret")
    payload = {
        "title": "History result",
        "torrent": "https://indexer.example/download/42?apikey=private-canary",
    }

    persisted = protect_download_references(payload, persisted=True)
    restored = protect_download_references(persisted, owner_id=41)
    direct = protect_download_references(payload, owner_id=41)

    assert persisted["source_id"] != restored["source_id"]
    assert restored["source_id"] == direct["source_id"]
    assert "private-canary" not in json.dumps(persisted)
    assert "private-canary" not in json.dumps(restored)


def test_persisted_references_cannot_be_redeemed_until_reissued_for_a_user():
    codec = DownloadReferenceCodec("shared-test-secret")
    persisted = codec.issue(
        0,
        "https://indexer.example/download/42?apikey=secret",
        "torrent",
        persisted=True,
    )

    with pytest.raises(DownloadReferenceError):
        codec.resolve(41, persisted)

    subject_reference = codec.reissue(persisted, 41, persisted=False)
    assert codec.resolve(41, subject_reference).startswith("https://indexer.example/")
    with pytest.raises(DownloadReferenceError):
        codec.resolve(42, subject_reference)
    with pytest.raises(DownloadReferenceError):
        codec.reissue(subject_reference, 42, persisted=False)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("torrent", "ftp://account:canary@indexer.example/file.torrent"),
        ("downloadUrl", "/api/download?apikey=canary"),
        ("guid", "urn:indexer:private-canary"),
        ("link", {"unexpected": "private-canary"}),
    ],
)
def test_noncanonical_download_fields_fail_closed(field, value):
    protected = protect_download_references(
        {field: value, "title": "Safe title"},
        owner_id=41,
    )

    assert field not in protected
    assert "canary" not in json.dumps(protected)
    assert protected["title"] == "Safe title"


@pytest.mark.parametrize(
    "query_key",
    [
        "access_token",
        "auth-token",
        "password",
        "sessionid",
        "x-api-key",
        "api-token",
        "private_key",
        "id_token",
        "refresh-token",
        "X-Amz-Signature",
    ],
)
def test_sensitive_information_urls_are_removed(query_key):
    protected = protect_download_references(
        {
            "infoUrl": f"https://indexer.example/details?{query_key}=private-canary",
            "web": "https://indexer.example/details/42",
        },
        owner_id=41,
    )

    assert "infoUrl" not in protected
    assert protected["web"] == "https://indexer.example/details/42"
    assert "private-canary" not in json.dumps(protected)
