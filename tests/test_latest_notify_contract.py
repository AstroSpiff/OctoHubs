"""The Latest notify OpenAPI response matches its runtime payload."""

from emby_latest.api_models import LatestNotifyResponse
from emby_latest.notification_dispatcher import failure_result, no_notifications_result
from emby_latest.routes import _notify_failure_diagnostics


def test_latest_notify_response_documents_runtime_errors():
    schema = LatestNotifyResponse.model_json_schema()

    assert "errors" in schema["properties"]
    assert "results" not in schema["properties"]
    assert LatestNotifyResponse.model_validate(no_notifications_result()).errors == []
    assert LatestNotifyResponse.model_validate(failure_result("failed", ["canary"])).errors == [
        "canary"
    ]


def test_latest_notify_failure_diagnostics_are_actionable_and_redacted():
    token = "123456789:AAExampleTelegramTokenValue"
    message, error_count, first_error = _notify_failure_diagnostics(
        {
            "message": "Nessuna notifica inviata",
            "errors": [f"Telegram https://api.telegram.org/bot{token}/sendMessage failed"],
        }
    )

    assert message == "Nessuna notifica inviata"
    assert error_count == 1
    assert token not in first_error
    assert "[REDACTED]" in first_error
