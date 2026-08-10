import os
from pathlib import Path

import pytest


PLUGIN_DIR = Path(
    os.getenv("OCTOHUBS_EVENT_BRIDGE_PLUGIN_DIR")
    or os.getenv("OCTOHUB_EVENT_BRIDGE_PLUGIN_DIR")
    or Path(__file__).resolve().parents[2] / "emby_plugins" / "OctoHubs.EventBridge"
)

pytestmark = pytest.mark.skipif(
    not PLUGIN_DIR.exists(),
    reason="Event Bridge plugin source lives outside the OctoHubs repository.",
)


def read_plugin_file(name: str) -> str:
    return (PLUGIN_DIR / name).read_text(encoding="utf-8")


def test_event_bridge_plugin_source_files_exist():
    project_file = "OctoHubs.EventBridge.csproj"
    if not (PLUGIN_DIR / project_file).exists():
        project_file = "OctoHub.EventBridge.csproj"
    expected = {
        project_file,
        "Plugin.cs",
        "PluginConfiguration.cs",
        "ServerEntryPoint.cs",
        "EventEnvelopeBuilder.cs",
        "EventBridgeConfigurationService.cs",
        "EventPublisher.cs",
        "README.md",
    }

    assert expected <= {path.name for path in PLUGIN_DIR.iterdir()}


def test_event_bridge_plugin_subscribes_to_real_emby_events():
    source = read_plugin_file("ServerEntryPoint.cs")

    assert "_sessionManager.PlaybackStart += OnPlaybackStart" in source
    assert "_sessionManager.PlaybackProgress += OnPlaybackProgress" in source
    assert "_sessionManager.PlaybackStopped += OnPlaybackStopped" in source
    assert "_sessionManager.SessionStarted += OnSessionStarted" in source
    assert "_sessionManager.SessionEnded += OnSessionEnded" in source
    assert "ShouldForwardPlayback" in source
    configuration = read_plugin_file("PluginConfiguration.cs")
    assert '"PlaybackStart"' in configuration
    assert '"PlaybackStopped"' in configuration


def test_event_bridge_plugin_posts_stable_webhook_envelope():
    publisher = read_plugin_file("EventPublisher.cs")
    builder = read_plugin_file("EventEnvelopeBuilder.cs")

    assert '"/api/emby/event-bridge/events"' in publisher
    assert '"X-Webhook-Secret"' in publisher
    assert any(header in publisher for header in ('"X-OctoHubs-Event-Bridge"', '"X-OctoHub-Event-Bridge"'))
    assert any(schema in builder for schema in ('"octohubs.emby.event.v1"', '"octohub.emby.event.v1"'))
    assert any(source in builder for source in ('"OctoHubs.EventBridge"', '"OctoHub.EventBridge"'))
    assert '["event"] = new Dictionary<string, object?>' in builder
    assert 'envelope["session"]' in builder
    assert 'envelope["media"]' in builder


def test_event_bridge_plugin_exposes_authenticated_configuration_endpoint():
    source = read_plugin_file("EventBridgeConfigurationService.cs")

    assert '"/OctoHubs/EventBridge/Configuration"' in source
    assert "ApplyEventBridgeConfiguration" in source
    assert "IReturn<EventBridgeConfigurationResponse>" in source
    assert "Plugin.Instance" in source
    assert "ApplyRemoteSettingsWithResult" in source


def test_event_bridge_plugin_has_startup_and_send_diagnostics():
    entrypoint = read_plugin_file("ServerEntryPoint.cs")
    publisher = read_plugin_file("EventPublisher.cs")
    builder = read_plugin_file("EventEnvelopeBuilder.cs")

    assert '"plugin.start"' in entrypoint
    assert '"plugin.config_saved"' in entrypoint
    assert "PublishResult" in publisher
    assert "LastPublishStatus" in " ".join(read_plugin_file("PluginConfiguration.cs").split())
    assert "BuildPluginEnvelope" in builder
    assert "RecordPublishResult" in entrypoint


def test_event_bridge_playback_builder_accepts_multiple_arg_types():
    source = read_plugin_file("EventEnvelopeBuilder.cs")

    assert "object args" in source
    assert 'Value(args, "Session") ?? Value(args, "SessionInfo")' in source
    assert 'Value(args, "PlaybackPositionTicks")' in source
    assert 'Value(args, "MediaSourceId") ?? Value(mediaSource, "Id")' in source
