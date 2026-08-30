"""Runtime validation for Request-based JSON endpoints."""

from __future__ import annotations

from typing import Any, TypeVar

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, ValidationError


RequestModel = TypeVar("RequestModel", bound=BaseModel)
JsonPayload = dict[str, Any] | list[Any]


class StrictRequestModel(BaseModel):
    """Default contract for state-changing JSON payloads."""

    model_config = ConfigDict(extra="forbid", strict=True)


def _validation_error(
    *,
    error_type: str,
    message: str,
    body: Any,
) -> RequestValidationError:
    return RequestValidationError(
        [
            {
                "type": error_type,
                "loc": ("body",),
                "msg": message,
                "input": body,
            }
        ],
        body=body,
    )


async def _request_body_is_empty(request: Request) -> bool:
    body_reader = getattr(request, "body", None)
    if not callable(body_reader):
        return True
    try:
        return not await body_reader()
    except Exception:
        return False


async def validated_json_payload(
    request: Request,
    model: type[RequestModel],
    *,
    required: bool = True,
) -> JsonPayload:
    """Parse JSON and enforce the documented Pydantic contract at runtime."""
    try:
        body = await request.json()
    except Exception as exc:
        if not required and await _request_body_is_empty(request):
            body = {}
        else:
            raise _validation_error(
                error_type="json_invalid",
                message="JSON non valido",
                body=None,
            ) from exc

    try:
        validated = model.model_validate(body, strict=True)
    except ValidationError as exc:
        errors = []
        for error in exc.errors(include_url=False):
            errors.append({**error, "loc": ("body", *error.get("loc", ()))})
        raise RequestValidationError(errors, body=body) from exc

    return validated.model_dump(mode="python", by_alias=True, exclude_unset=True)
