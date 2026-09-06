"""The Latest notify OpenAPI response matches its runtime payload."""

from emby_latest.api_models import LatestNotifyResponse
from emby_latest.notification_dispatcher import failure_result, no_notifications_result


def test_latest_notify_response_documents_runtime_errors():
    schema = LatestNotifyResponse.model_json_schema()

    assert "errors" in schema["properties"]
    assert "results" not in schema["properties"]
    assert LatestNotifyResponse.model_validate(no_notifications_result()).errors == []
    assert LatestNotifyResponse.model_validate(failure_result("failed", ["canary"])).errors == [
        "canary"
    ]
