from unittest.mock import Mock

from emby_collections.operations import start_source_list_operation


def test_source_list_refresh_reuses_an_active_operation(monkeypatch):
    active = {
        "id": "operation-1",
        "kind": "collections_trakt_lists",
        "status": "running",
    }
    tracker = Mock()
    tracker.list_operations.return_value = [active]
    starter = Mock()
    monkeypatch.setattr("app_state.get_operation_tracker", lambda: tracker)
    monkeypatch.setattr(
        "emby_collections.operations.start_tracked_background_job",
        starter,
    )

    operation = start_source_list_operation(
        source_key="trakt",
        title="Liste Trakt",
        fetcher=Mock(),
    )

    assert operation == active
    starter.assert_not_called()


def test_source_list_refresh_starts_after_the_previous_operation_finishes(monkeypatch):
    tracker = Mock()
    tracker.list_operations.return_value = [
        {
            "id": "operation-old",
            "kind": "collections_trakt_lists",
            "status": "success",
        }
    ]
    starter = Mock(return_value={"id": "operation-new"})
    monkeypatch.setattr("app_state.get_operation_tracker", lambda: tracker)
    monkeypatch.setattr(
        "emby_collections.operations.start_tracked_background_job",
        starter,
    )

    operation = start_source_list_operation(
        source_key="trakt",
        title="Liste Trakt",
        fetcher=Mock(),
    )

    assert operation == {"id": "operation-new"}
    starter.assert_called_once()
