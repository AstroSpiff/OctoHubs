"""Outcome and immutable-target canaries for the R31 remediation."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_probe_workflow_rejects_a_target_removed_during_the_run(monkeypatch):
    from services import workflows

    status_calls = []
    manager = SimpleNamespace(
        _global_workers={},
        get_status=lambda server_id: status_calls.append(server_id) or {},
    )
    monkeypatch.setattr(workflows, "get_probe_manager", lambda: manager)
    monkeypatch.setattr(
        workflows,
        "load_config",
        lambda: (
            {"EMBY": {"SERVERS": [{"id": "other", "enabled": True}]}},
            True,
        ),
    )

    with pytest.raises(RuntimeError, match="verificare il completamento Probe"):
        workflows._wf_check_probe(
            {"_probe_run_id": "run-1", "_probe_server_ids": ["deleted-server"]}
        )
    assert status_calls == []


@pytest.mark.parametrize(
    "result",
    [
        {"success": False, "message": "failed"},
        {"success": True, "status": "partial", "message": "partial"},
        {"status": "error", "message": "error"},
    ],
)
def test_background_job_boundary_rejects_negative_application_outcomes(result):
    from services.background_jobs import _require_complete_result

    with pytest.raises(RuntimeError):
        _require_complete_result(result)


@pytest.mark.parametrize(
    ("synced", "error_count", "expected_status", "expected_success"),
    [
        (2, 0, "success", True),
        (1, 1, "partial", False),
        (0, 1, "error", False),
    ],
)
def test_collection_sync_all_reports_aggregate_outcome(
    monkeypatch,
    synced,
    error_count,
    expected_status,
    expected_success,
):
    from emby_collections import operations

    captured = {}

    class Context:
        @staticmethod
        def raise_if_cancelled():
            return None

        @staticmethod
        def update(**_kwargs):
            return None

    def run_immediately(**kwargs):
        captured.update(kwargs["work"](Context()))
        return {"id": "operation-r31"}

    monkeypatch.setattr(operations, "start_tracked_background_job", run_immediately)
    operation = operations.start_collection_sync_all_operation(
        runner=lambda: {
            "summary": {
                "synced": synced,
                "errors": [{"id": str(index)} for index in range(error_count)],
            }
        }
    )

    assert operation["id"] == "operation-r31"
    assert captured["status"] == expected_status
    assert captured["success"] is expected_success


def test_partial_notification_outcome_is_not_successful():
    from emby_latest.notification_delivery_workflow import DeliveryOutcome

    result = DeliveryOutcome(errors=["destination failed"], sent=1, failed=1).result()

    assert result["success"] is False
    assert result["status"] == "partial"


def test_workflow_rejects_partial_notification_outcome():
    from core.tasks import WorkflowManager

    manager = WorkflowManager()
    manager._status["workflow_id"] = "workflow-r31"
    manager._status["steps"] = [
        {"id": "notify", "label": "Notify", "status": "pending"}
    ]
    manager._notify_func = lambda _context: {
        "success": False,
        "status": "partial",
        "message": "One destination failed",
        "sent": 1,
        "failed": 1,
        "errors": ["failed"],
    }

    with pytest.raises(Exception, match="One destination failed"):
        manager._execute_notify_step(0, {}, "workflow-r31")
