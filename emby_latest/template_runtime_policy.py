"""Runtime resource limits for Latest notification templates."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from typing import Any, Callable

from jinja2.utils import Namespace
from markupsafe import Markup


MAX_TEMPLATE_ITERATION_ITEMS = 256
MAX_TEMPLATE_WORK_UNITS = 1_024


class TemplateResourceLimitError(ValueError):
    """Raised when a Latest template exceeds its safe execution budget."""


class _TemplateIterationBudget:
    def __init__(self) -> None:
        self.remaining = MAX_TEMPLATE_WORK_UNITS

    def consume(self, units: int = 1) -> None:
        if units > self.remaining:
            raise TemplateResourceLimitError("Budget di lavoro template superato")
        self.remaining -= units


_ACTIVE_ITERATION_BUDGET: ContextVar[_TemplateIterationBudget | None] = ContextVar(
    "latest_template_iteration_budget",
    default=None,
)


def _bounded_iterator(values: Iterable[Any]) -> Iterator[Any]:
    budget = _ACTIVE_ITERATION_BUDGET.get()
    for index, value in enumerate(values):
        if index >= MAX_TEMPLATE_ITERATION_ITEMS:
            break
        if budget is not None:
            budget.consume()
        yield value


def consume_template_work(units: int = 1) -> None:
    """Charge work performed by Jinja operations outside iterable wrappers."""
    budget = _ACTIVE_ITERATION_BUDGET.get()
    if budget is not None:
        budget.consume(units)


@contextmanager
def template_iteration_budget() -> Iterator[None]:
    """Apply one aggregate iteration budget to a complete render."""
    token = _ACTIVE_ITERATION_BUDGET.set(_TemplateIterationBudget())
    try:
        yield
    finally:
        _ACTIVE_ITERATION_BUDGET.reset(token)


class _BoundedTemplateString(str):
    """String whose template-visible iteration and splitting are bounded."""

    def __iter__(self):
        return _bounded_iterator(str(self))

    def __getitem__(self, index):  # noqa: ANN001, ANN201 - mirrors str
        value = str.__getitem__(self, index)
        return _BoundedTemplateString(value)

    def split(self, sep=None, maxsplit=-1):  # noqa: ANN001, ANN201 - mirrors str
        budget = _ACTIVE_ITERATION_BUDGET.get()
        if budget is not None:
            budget.consume(1 + min(MAX_TEMPLATE_ITERATION_ITEMS, len(self) // 1_024))
        requested = MAX_TEMPLATE_ITERATION_ITEMS - 1
        if isinstance(maxsplit, int) and maxsplit >= 0:
            requested = min(maxsplit, requested)
        return _BoundedTemplateList(
            _BoundedTemplateString(part) for part in str(self).split(sep, requested)
        )


class _BoundedTemplateList(list[Any]):
    """List whose template-visible iteration cannot exceed the policy budget."""

    def __iter__(self):
        return _bounded_iterator(list.__iter__(self))

    def __getitem__(self, index):  # noqa: ANN001, ANN201 - mirrors list
        value = list.__getitem__(self, index)
        if isinstance(index, slice):
            return _BoundedTemplateList(value[:MAX_TEMPLATE_ITERATION_ITEMS])
        return value


class _BoundedTemplateTuple(tuple[Any, ...]):
    """Tuple whose template-visible iteration cannot exceed the policy budget."""

    def __iter__(self):
        return _bounded_iterator(tuple.__iter__(self))

    def __getitem__(self, index):  # noqa: ANN001, ANN201 - mirrors tuple
        value = tuple.__getitem__(self, index)
        if isinstance(index, slice):
            return _BoundedTemplateTuple(value[:MAX_TEMPLATE_ITERATION_ITEMS])
        return value


class _BoundedTemplateMarkup(Markup):
    """Markup variant preserving safety while bounding template iteration."""

    def __iter__(self):
        return _bounded_iterator(str(self))

    def __getitem__(self, index):  # noqa: ANN001, ANN201 - mirrors Markup
        return _BoundedTemplateMarkup(str.__getitem__(self, index))


class _BoundedTemplateDict(dict[Any, Any]):
    """Dictionary whose direct iteration is bounded like other collections."""

    def __iter__(self):
        return _bounded_iterator(dict.__iter__(self))


def bound_template_context(value: Any) -> Any:
    """Recursively wrap template data so every iterable has a hard ceiling."""
    if isinstance(value, Markup):
        return _BoundedTemplateMarkup(value)
    if isinstance(value, str):
        return _BoundedTemplateString(value)
    if isinstance(value, dict):
        return _BoundedTemplateDict(
            (bound_template_context(key), bound_template_context(item))
            for key, item in value.items()
        )
    if isinstance(value, list):
        return _BoundedTemplateList(bound_template_context(item) for item in value)
    if isinstance(value, tuple):
        return _BoundedTemplateTuple(bound_template_context(item) for item in value)
    if isinstance(value, set):
        return _BoundedTemplateList(
            bound_template_context(item)
            for item in list(value)[:MAX_TEMPLATE_ITERATION_ITEMS]
        )
    return value


def bounded_template_filter(callback: Callable[..., Any]) -> Callable[..., Any]:
    """Preserve Jinja filter metadata and bound every iterable filter result."""

    @wraps(callback)
    def bounded(*args: Any, **kwargs: Any) -> Any:
        consume_template_work(template_work_units((*args, *kwargs.values())))
        return bound_template_context(callback(*args, **kwargs))

    return bounded


def _measure_mapping(value: dict[Any, Any], active: frozenset[int]) -> int:
    units = 1
    for key, entry in value.items():
        units += _measure_template_value(key, active)
        units += _measure_template_value(entry, active)
        if units > MAX_TEMPLATE_WORK_UNITS:
            break
    return units


def _measure_sequence(value: Iterable[Any], active: frozenset[int]) -> int:
    units = 1
    for item in value:
        units += _measure_template_value(item, active)
        if units > MAX_TEMPLATE_WORK_UNITS:
            break
    return units


def _measure_template_value(value: Any, active: frozenset[int]) -> int:
    if isinstance(value, (str, bytes, Markup)):
        return 1 + (len(value) + 1_023) // 1_024
    if isinstance(value, Namespace):
        attributes = object.__getattribute__(value, "_Namespace__attrs")
        return _measure_template_value(attributes, active)
    if not isinstance(value, (list, tuple, set, dict)):
        return 1
    identity = id(value)
    if identity in active:
        return MAX_TEMPLATE_WORK_UNITS + 1
    next_active = active | {identity}
    if isinstance(value, dict):
        return _measure_mapping(value, next_active)
    return _measure_sequence(value, next_active)


def template_work_units(values: Iterable[Any]) -> int:
    """Estimate nested filter input work before the operation starts."""
    total = 1
    for candidate in values:
        total += _measure_template_value(candidate, frozenset())
        if total > MAX_TEMPLATE_WORK_UNITS:
            break
    return total


__all__ = [
    "MAX_TEMPLATE_ITERATION_ITEMS",
    "MAX_TEMPLATE_WORK_UNITS",
    "TemplateResourceLimitError",
    "bounded_template_filter",
    "bound_template_context",
    "consume_template_work",
    "template_work_units",
    "template_iteration_budget",
]
