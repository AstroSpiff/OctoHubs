"""Focused R27 contract, log-safety, and header regression canaries."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic import ValidationError

from tests.workflow_test_support import attach_test_operation_tracker


def test_workflow_public_context_rejects_unknown_large_and_forged_fields():
    from services.workflow_api_models import WorkflowStartRequest

    with pytest.raises(ValidationError):
        WorkflowStartRequest.model_validate({
            "type": "smart",
            "context": {"access_token": "x" * 900_000},
        })
    with pytest.raises(ValidationError):
        WorkflowStartRequest.model_validate({
            "type": "smart",
            "context": {"server_id": "green\nFORGED"},
        })


def test_workflow_manager_projects_internal_context_before_every_sink():
    from core.tasks import WorkflowManager

    manager = WorkflowManager()
    attach_test_operation_tracker(manager)
    manager._start_workflow_thread_locked = lambda *_args, **_kwargs: None

    assert manager.start(
        workflow_type="library",
        context={
            "server_id": "green",
            "library_id": "movies",
            "access_token": "WORKFLOW_SECRET_CANARY",
            "nested": {"payload": "x" * 100_000},
        },
    ) is True

    assert manager.get_status()["context"] == {
        "server_id": "green",
        "library_id": "movies",
    }


def test_workflow_logging_omits_context_values_and_log_forging():
    from services.workflows import _wf_trigger_scan

    canary = "WORKFLOW_SECRET_CANARY"
    with (
        patch("emby_libraries.scan_snapshots._build_scan_group_tracked_snapshot", return_value=({"success": False}, 400)),
        patch("builtins.print") as output,
    ):
        _wf_trigger_scan({
            "group_name": canary,
            "libraries": [{"server_id": "green", "library_id": "movies"}],
        })

    rendered = "\n".join(" ".join(map(str, call.args)) for call in output.call_args_list)
    assert canary not in rendered
    assert "libraries=1" in rendered


def test_torrent_filename_header_is_ascii_safe_and_preserves_unicode_name():
    from search.manager import _guess_torrent_filename, _torrent_content_disposition

    filename = _guess_torrent_filename(
        "https://example.test/download",
        {"content-disposition": "attachment; filename*=UTF-8''%E2%82%ACvil%00%09.torrent"},
    )
    header = _torrent_content_disposition(filename)

    header.encode("ascii")
    assert "\x00" not in header
    assert "\t" not in header
    assert "filename*=UTF-8''%E2%82%ACvil__.torrent" in header


@pytest.mark.parametrize("control", ["\x00", "\r", "\n", "\t", "\x7f"])
def test_application_secret_policy_rejects_every_control_character(control):
    from core.secret_strength import is_strong_secret

    assert is_strong_secret(f"strong-secret-material-{control}-0123456789abcdef") is False


def test_emby_stop_payload_never_reaches_logs_or_public_error():
    from emby_runtime import snapshots

    canary = "EMBY_STOP_SECRET_CANARY\nFORGED"
    with (
        patch.object(snapshots, "load_config", return_value=({
            "EMBY": {"SERVERS": [{"id": "green", "enabled": True}]},
        }, True)),
        patch.object(snapshots, "_fetch_emby_scheduled_tasks", return_value=([{
            "id": "task-1",
            "is_running": True,
        }], None)),
        patch.object(snapshots, "_stop_emby_task", return_value=(False, canary)),
        patch.object(snapshots.logger, "debug") as debug,
    ):
        payload, status = snapshots._build_emby_stop_task_snapshot({
            "server_id": "green",
            "task_id": "task-1",
        })

    assert status == 500
    assert canary not in str(payload)
    assert canary not in str(debug.call_args_list)
