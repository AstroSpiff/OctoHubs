"""Class canaries for bounded persistence identities discovered during R44."""

from __future__ import annotations

from types import SimpleNamespace
import time

import pytest
from pydantic import TypeAdapter, ValidationError

from core import auth
from core.auth_field_limits import (
    ACCOUNT_EMAIL_MAX_LENGTH,
    ACCOUNT_USERNAME_MAX_LENGTH,
    API_TOKEN_NAME_MAX_LENGTH,
)
from core.storage.field_limits import (
    REQUEST_RULE_ID_MAX_LENGTH,
    TELEGRAM_DESTINATION_KEY_MAX_LENGTH,
    TELEGRAM_IDENTIFIER_MAX_LENGTH,
)
from core.storage.storage_jellyseerr import (
    JELLYSEERR_MEDIA_TYPE_MAX_LENGTH,
    JELLYSEERR_REQUESTED_BY_MAX_LENGTH,
    JELLYSEERR_REQUEST_ID_MAX_LENGTH,
    JELLYSEERR_STATUS_LABEL_MAX_LENGTH,
    JELLYSEERR_STATUS_MAX_LENGTH,
    StorageJellyseerrMixin,
    normalize_jellyseerr_request_entries,
)
from core.storage.storage_image_cache import StorageImageCacheMixin
from core.storage.storage_latest_notifications import StorageLatestNotificationMixin
from core.storage.storage_latest import StorageLatestMixin
from core.storage.storage_probe import StorageProbeMixin
from core.storage.storage_requests import StorageRequestsMixin
from emby_latest.notification_dispatcher import destination_key
from web.account_api_models import AccountCreateRequest, ApiTokenCreateRequest


class _NoSession:
    def _get_session(self):
        raise AssertionError("validation must finish before opening a session")


class _NoSessionJellyseerr(_NoSession, StorageJellyseerrMixin):
    pass


class _NoSessionLatest(_NoSession, StorageLatestNotificationMixin):
    pass


class _NoSessionLatestCache(_NoSession, StorageLatestMixin):
    pass


class _NoSessionRequests(_NoSession, StorageRequestsMixin):
    pass


class _NoSessionImageCache(_NoSession, StorageImageCacheMixin):
    pass


class _ProbeNormalizer(_NoSession, StorageProbeMixin):
    pass


def test_jellyseerr_identity_is_rejected_before_snapshot_session() -> None:
    invalid = [{"request_id": "r" * (JELLYSEERR_REQUEST_ID_MAX_LENGTH + 1)}]

    with pytest.raises(ValueError, match="request_id exceeds"):
        _NoSessionJellyseerr().save_jellyseerr_requests(invalid)

    with pytest.raises(ValueError, match="NUL"):
        _NoSessionJellyseerr().save_jellyseerr_requests(
            [{"request_id": "same\x00identity"}]
        )


def test_jellyseerr_descriptive_projection_covers_every_varchar() -> None:
    entry = normalize_jellyseerr_request_entries(
        [
            {
                "request_id": "r" * JELLYSEERR_REQUEST_ID_MAX_LENGTH,
                "media_type": "m" * (JELLYSEERR_MEDIA_TYPE_MAX_LENGTH + 1),
                "status": "s" * (JELLYSEERR_STATUS_MAX_LENGTH + 1),
                "status_label": "l" * (JELLYSEERR_STATUS_LABEL_MAX_LENGTH + 1),
                "requested_by": "u" * (JELLYSEERR_REQUESTED_BY_MAX_LENGTH + 1),
            }
        ]
    )[0]

    assert len(entry["request_id"]) == JELLYSEERR_REQUEST_ID_MAX_LENGTH
    assert len(entry["media_type"]) == JELLYSEERR_MEDIA_TYPE_MAX_LENGTH
    assert len(entry["status"]) == JELLYSEERR_STATUS_MAX_LENGTH
    assert len(entry["status_label"]) == JELLYSEERR_STATUS_LABEL_MAX_LENGTH
    assert len(entry["requested_by"]) == JELLYSEERR_REQUESTED_BY_MAX_LENGTH


def test_descriptive_projection_removes_nul_without_rejecting_upstream_data() -> None:
    from core.persisted_text import project_persisted_text

    assert project_persisted_text("A\x00B", 10) == "AB"
    assert project_persisted_text("x" * 11, 10) == "x" * 10


def test_backup_username_is_projected_without_losing_the_backup(tmp_path) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from core.storage import DatabaseStorage, EmbyUserBackup

    database_url = f"sqlite:///{tmp_path / 'backup.db'}"
    engine = create_engine(database_url, future=True)
    EmbyUserBackup.__table__.create(engine)
    storage = DatabaseStorage({"URL": database_url})
    storage._engine = engine
    storage._Session = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        backup_id = storage.create_user_backup(
            "server",
            "user",
            "A\x00" + ("u" * 300),
            "manual",
            {},
        )
        with storage._Session() as session:
            row = session.get(EmbyUserBackup, backup_id)
            assert row is not None
            assert "\x00" not in row.username
            assert len(row.username) == 255
    finally:
        engine.dispose()


def test_image_cache_identity_is_rejected_before_session() -> None:
    with pytest.raises(ValueError, match="cache_key exceeds"):
        _NoSessionImageCache().save_emby_image_cache(
            "k" * 256,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            "image/png",
            b"data",
            60,
        )


def test_probe_upstream_descriptions_are_projected_before_session() -> None:
    normalized = _ProbeNormalizer()._normalize_probe_queue_items(
        [
            {
                "server_id": "server",
                "item_id": "item",
                "library_name": "l" * 501,
                "name": "n" * 501,
                "series_name": "s" * 501,
                "media_type": "m" * 51,
                "path": "A\x00B",
            }
        ]
    )[0]

    assert len(normalized["library_name"]) == 500
    assert len(normalized["name"]) == 500
    assert len(normalized["series_name"]) == 500
    assert len(normalized["media_type"]) == 50
    assert normalized["path"] == "AB"

    history = _ProbeNormalizer()._normalize_probe_history_data(
        {
            "server_id": "server",
            "item_id": "item",
            "error_details": "A\x00B",
        }
    )
    assert history["error_details"] == "AB"


@pytest.mark.parametrize("operation", ["get", "save", "save-if-present"])
def test_probe_config_uses_the_canonical_server_identity_before_session(
    operation: str,
) -> None:
    storage = _ProbeNormalizer()
    invalid = "s" * 37
    if operation == "save-if-present":
        assert storage.save_probe_config_if_server_exists(invalid, {}) is False
        return
    with pytest.raises(ValueError, match="server_id exceeds"):
        if operation == "get":
            storage.get_probe_config(invalid)
        else:
            storage.save_probe_config(invalid, {})


@pytest.mark.parametrize("operation", ["save", "patch-update", "patch-delete"])
def test_request_rule_ids_are_rejected_before_session(operation: str) -> None:
    invalid = "r" * (REQUEST_RULE_ID_MAX_LENGTH + 1)
    storage = _NoSessionRequests()

    with pytest.raises(ValueError, match="request_id exceeds"):
        if operation == "save":
            storage.save_request_rules({invalid: {}})
        elif operation == "patch-update":
            storage.patch_request_rules({invalid: {}}, ())
        else:
            storage.patch_request_rules({}, (invalid,))


def test_telegram_destination_composed_boundary_and_writer_preflight() -> None:
    key = destination_key(
        "b" * TELEGRAM_IDENTIFIER_MAX_LENGTH,
        "c" * TELEGRAM_IDENTIFIER_MAX_LENGTH,
    )
    assert len(key) == TELEGRAM_DESTINATION_KEY_MAX_LENGTH

    with pytest.raises(ValueError, match="bot_id exceeds"):
        destination_key("b" * (TELEGRAM_IDENTIFIER_MAX_LENGTH + 1), "chat")

    with pytest.raises(ValueError, match="destination_key exceeds"):
        _NoSessionLatest().claim_latest_notification_delivery(
            delivery_key="d" * 64,
            server_id="server",
            publication_key="publication",
            destination_key="x" * (TELEGRAM_DESTINATION_KEY_MAX_LENGTH + 1),
            claim_token="c" * 32,
        )


def test_latest_cache_server_identity_is_rejected_before_session() -> None:
    with pytest.raises(ValueError, match="server_id exceeds"):
        _NoSessionLatestCache().save_latest_cache(
            "batch",
            {"movies": [{"server_id": "s" * 37}]},
            1,
            1,
        )

    with pytest.raises(ValueError, match="server_id exceeds"):
        _NoSessionLatestCache().save_latest_cache(
            "batch",
            {"errors": [{"server_id": "s" * 37, "message": "error"}]},
            1,
            1,
        )


def test_account_http_contracts_match_auth_schema_lengths() -> None:
    with pytest.raises(ValidationError):
        AccountCreateRequest.model_validate(
            {
                "username": "user",
                "password": "password",
                "email": "a" * (ACCOUNT_EMAIL_MAX_LENGTH - 10) + "@example.test",
            }
        )
    with pytest.raises(ValidationError):
        AccountCreateRequest.model_validate(
            {
                "username": "bad\x00name",
                "password": "password",
            }
        )
    with pytest.raises(ValidationError):
        ApiTokenCreateRequest.model_validate(
            {
                "name": "t" * (API_TOKEN_NAME_MAX_LENGTH + 1),
                "permission_profile": "read_only",
            }
        )

    assert auth.User.email.type.length == ACCOUNT_EMAIL_MAX_LENGTH
    assert auth.User.username.type.length == ACCOUNT_USERNAME_MAX_LENGTH
    assert auth.ApiToken.name.type.length == API_TOKEN_NAME_MAX_LENGTH


@pytest.mark.parametrize(
    "type_path",
    ["collection", "library", "request", "preset"],
)
def test_persisted_http_identifiers_reject_nul(type_path: str) -> None:
    if type_path == "collection":
        from emby_collections.api_models import CollectionDefinitionId

        contract = CollectionDefinitionId
    elif type_path == "library":
        from emby_libraries.scan_api_models import LibraryCollectionType

        contract = LibraryCollectionType
    elif type_path == "request":
        from search.rule_contracts import RequestIdentifier

        contract = RequestIdentifier
    else:
        from emby_users.api_models import SettingsPresetIdentifier

        contract = SettingsPresetIdentifier

    with pytest.raises(ValidationError):
        TypeAdapter(contract).validate_python("bad\x00identity")


def test_justwatch_nul_projection_does_not_alias_a_clean_title() -> None:
    from core.justwatch_manager import JustWatchManager

    assert JustWatchManager._cache_title("AB") != JustWatchManager._cache_title(
        "A\x00B"
    )


def test_auth_core_rejects_oversized_values_before_storage(monkeypatch) -> None:
    class _ExplodingSession:
        def __bool__(self):
            raise AssertionError("storage must not be inspected")

        def __call__(self):
            raise AssertionError("storage must not be opened")

    monkeypatch.setattr(auth, "db_session", _ExplodingSession())

    assert auth.get_user_by_username("bad\x00name") is None
    assert (
        auth.create_user(
            "user",
            "password",
            email="e" * (ACCOUNT_EMAIL_MAX_LENGTH + 1),
        )
        is None
    )


def test_audit_projection_removes_nul_from_every_persisted_text(monkeypatch) -> None:
    class _AuditSession:
        entry = None

        def __bool__(self):
            return True

        def add(self, entry):
            self.entry = entry

        def commit(self):
            return None

    session = _AuditSession()
    monkeypatch.setattr(auth, "db_session", session)
    monkeypatch.setattr(auth, "_last_audit_prune_at", time.monotonic())
    request = SimpleNamespace(
        headers={"User-Agent": "agent\x00unsafe"},
        url=SimpleNamespace(path="/bad\x00path"),
        path="/bad\x00path",
        method="PO\x00ST",
        scope={},
        client=None,
    )

    auth.log_audit_event(
        SimpleNamespace(id=1, username="user\x00name"),
        "act\x00ion",
        "detail\x00text",
        request,
    )

    assert session.entry is not None
    for value in (
        session.entry.username,
        session.entry.action,
        session.entry.detail,
        session.entry.path,
        session.entry.method,
        session.entry.user_agent,
    ):
        assert "\x00" not in value
    assert (
        auth.create_user(
            "u" * (ACCOUNT_USERNAME_MAX_LENGTH + 1),
            "password",
        )
        is None
    )
    assert (
        auth.create_api_token(
            SimpleNamespace(id=1),
            "t" * (API_TOKEN_NAME_MAX_LENGTH + 1),
            ["read:status"],
        )
        is None
    )
