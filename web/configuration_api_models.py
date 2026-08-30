"""OpenAPI contracts for the configuration workspace control API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator


class ConfigurationApiModel(BaseModel):
    """Keep settings payloads forward-compatible while documenting stable fields."""

    model_config = ConfigDict(extra="allow")


class ConfigurationInputModel(BaseModel):
    """Reject unknown write fields instead of silently accepting typos."""

    model_config = ConfigDict(extra="forbid")


class AutomationTask(ConfigurationApiModel):
    enabled: StrictBool = False
    mode: Literal["interval", "fixed"] = "interval"
    interval_minutes: int = Field(default=60, ge=5, le=10080)
    times: list[str] = Field(default_factory=list)


class ConfigurationAutomationsPayload(ConfigurationApiModel):
    tasks: dict[str, AutomationTask] = Field(default_factory=dict)
    collections: AutomationTask = Field(default_factory=AutomationTask)


class RequestRefreshStatus(ConfigurationApiModel):
    running: bool = False
    last_status: str | None = None
    last_warning: str | None = None
    last_warning_at: str | None = None
    last_error: str | None = None
    completed_at: str | None = None


class DatabaseServiceSettings(ConfigurationApiModel):
    enabled: bool = False
    host: str = ""
    port: str = ""
    name: str = ""
    user: str = ""
    driver: str = "postgresql+psycopg2"
    url_configured: bool = False
    params: str = ""
    password_configured: bool = False


class ServiceConnection(ConfigurationApiModel):
    url: str = ""
    api_key_configured: bool = False


class QbittorrentConnection(ServiceConnection):
    username: str = ""
    password_configured: bool = False


class TmdbConnection(ConfigurationApiModel):
    language: str = "it-IT"
    api_key_configured: bool = False


class ApiKeyCollection(ConfigurationApiModel):
    api_keys_configured: int = 0


class ConfigurationConnections(ConfigurationApiModel):
    jellyseerr: ServiceConnection = Field(default_factory=ServiceConnection)
    prowlarr: ServiceConnection = Field(default_factory=ServiceConnection)
    jackett: ServiceConnection = Field(default_factory=ServiceConnection)
    qbittorrent: QbittorrentConnection = Field(default_factory=QbittorrentConnection)
    tmdb: TmdbConnection = Field(default_factory=TmdbConnection)
    mdblist: ApiKeyCollection = Field(default_factory=ApiKeyCollection)
    omdb: ApiKeyCollection = Field(default_factory=ApiKeyCollection)


class TraktServiceSettings(ConfigurationApiModel):
    enabled: bool = False
    client_id: str = ""
    client_secret_configured: bool = False
    access_token_configured: bool = False
    expires_at: str = ""


class JustWatchServiceSettings(ConfigurationApiModel):
    enabled: bool = False
    locale: str = "it_IT"


class ConfigurationServicesPayload(ConfigurationApiModel):
    database: DatabaseServiceSettings = Field(default_factory=DatabaseServiceSettings)
    connections: ConfigurationConnections = Field(default_factory=ConfigurationConnections)
    trakt: TraktServiceSettings = Field(default_factory=TraktServiceSettings)
    justwatch: JustWatchServiceSettings = Field(default_factory=JustWatchServiceSettings)


class ConfigurationSettingsResponse(ConfigurationApiModel):
    success: bool
    has_config: bool
    automations: ConfigurationAutomationsPayload
    request_refresh: RequestRefreshStatus
    services: ConfigurationServicesPayload
    message: str | None = None


class DatabaseServiceSettingsInput(ConfigurationInputModel):
    host: StrictStr = ""
    port: StrictStr | StrictInt = ""
    name: StrictStr = ""
    user: StrictStr = ""
    driver: StrictStr = "postgresql+psycopg2"
    params: StrictStr = ""
    password: StrictStr = ""
    url: StrictStr = ""
    clear_password: StrictBool = False
    clear_url: StrictBool = False

    @field_validator("port")
    @classmethod
    def validate_port(cls, value: str | int) -> str | int:
        if value == "":
            return value
        if isinstance(value, bool):
            raise ValueError("port must be an integer between 1 and 65535")
        if isinstance(value, str):
            if not value.isdigit():
                raise ValueError("port must be an integer between 1 and 65535")
            numeric_value = int(value)
        else:
            numeric_value = value
        if not 1 <= numeric_value <= 65535:
            raise ValueError("port must be an integer between 1 and 65535")
        return value


class ServiceConnectionInput(ConfigurationInputModel):
    url: StrictStr = ""
    api_key: StrictStr = ""
    clear_api_key: StrictBool = False


class QbittorrentConnectionInput(ConfigurationInputModel):
    url: StrictStr = ""
    username: StrictStr = ""
    password: StrictStr = ""
    clear_password: StrictBool = False


class TmdbConnectionInput(ConfigurationInputModel):
    language: StrictStr = "it-IT"
    api_key: StrictStr = ""
    clear_api_key: StrictBool = False


class ApiKeyCollectionInput(ConfigurationInputModel):
    api_keys: list[StrictStr] = Field(default_factory=list)
    clear_api_keys: StrictBool = False


class ConfigurationConnectionsInput(ConfigurationInputModel):
    jellyseerr: ServiceConnectionInput = Field(default_factory=ServiceConnectionInput)
    prowlarr: ServiceConnectionInput = Field(default_factory=ServiceConnectionInput)
    jackett: ServiceConnectionInput = Field(default_factory=ServiceConnectionInput)
    qbittorrent: QbittorrentConnectionInput = Field(default_factory=QbittorrentConnectionInput)
    tmdb: TmdbConnectionInput = Field(default_factory=TmdbConnectionInput)
    mdblist: ApiKeyCollectionInput = Field(default_factory=ApiKeyCollectionInput)
    omdb: ApiKeyCollectionInput = Field(default_factory=ApiKeyCollectionInput)


class TraktServiceSettingsInput(ConfigurationInputModel):
    enabled: StrictBool = False
    client_id: StrictStr = ""
    client_secret: StrictStr = ""
    clear_client_secret: StrictBool = False
    access_token: StrictStr = ""


class JustWatchServiceSettingsInput(ConfigurationInputModel):
    enabled: StrictBool = False
    locale: StrictStr = "it_IT"


class ConfigurationServicesUpdateRequest(ConfigurationInputModel):
    database: DatabaseServiceSettingsInput = Field(default_factory=DatabaseServiceSettingsInput)
    connections: ConfigurationConnectionsInput = Field(default_factory=ConfigurationConnectionsInput)
    trakt: TraktServiceSettingsInput = Field(default_factory=TraktServiceSettingsInput)
    justwatch: JustWatchServiceSettingsInput = Field(default_factory=JustWatchServiceSettingsInput)
