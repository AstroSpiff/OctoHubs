"""Bounded Jinja policy for Latest notification templates.

The notification editor intentionally supports a useful Jinja subset, including
macros and short loops over media versions.  This module keeps that contract
without allowing arbitrary calls or unbounded expansion primitives.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from jinja2 import nodes

from emby_latest.template_runtime_policy import (
    MAX_TEMPLATE_ITERATION_ITEMS,
    MAX_TEMPLATE_WORK_UNITS,
    TemplateResourceLimitError,
    bound_template_context,
    bounded_template_filter,
    consume_template_work,
    template_iteration_budget,
    template_work_units,
)


MAX_TEMPLATE_AST_NODES = 1_024
MAX_TEMPLATE_CALLS = 64
MAX_TEMPLATE_CONCATS = 32
MAX_TEMPLATE_CONCAT_PARTS = 16
MAX_TEMPLATE_FILTERS = 96
MAX_TEMPLATE_LIST_APPENDS = 16
MAX_TEMPLATE_LOOPS = 8
MAX_TEMPLATE_LOOP_DEPTH = 2
MAX_TEMPLATE_REPEATED_COMPARISONS = 8
MAX_TEMPLATE_MACRO_CALL_DEPTH = 4
MAX_TEMPLATE_MACRO_OUTPUT_PARTS = 8
MAX_TEMPLATE_MACROS = 8
MAX_TEMPLATE_LITERAL_ITEMS = 32
MAX_TEMPLATE_FORMAT_WIDTH = 256

ALLOWED_FILTERS = {
    "default",
    "e",
    "escape",
    "float",
    "format",
    "int",
    "join",
    "length",
    "lower",
    "round",
    "safe",
    "striptags",
    "title",
    "trim",
    "truncate",
    "upper",
}
ALLOWED_TESTS = {
    "boolean",
    "defined",
    "escaped",
    "even",
    "false",
    "float",
    "integer",
    "iterable",
    "lower",
    "mapping",
    "none",
    "number",
    "odd",
    "sequence",
    "string",
    "true",
    "undefined",
    "upper",
}

_BANNED_NODES = (
    nodes.AssignBlock,
    nodes.Block,
    nodes.CallBlock,
    nodes.Extends,
    nodes.FilterBlock,
    nodes.FromImport,
    nodes.Import,
    nodes.Include,
    nodes.Mod,
    nodes.Mul,
    nodes.Pow,
)
_PERCENT_FORMAT_TOKEN = re.compile(
    r"%(?:\([^)]+\))?[#0 +\-]*(?P<width>\d+)?(?:\.(?P<precision>\d+))?[diouxXeEfFgGcrsa]"
)


def validate_template_ast(parsed: nodes.Template) -> None:
    """Accept the documented bounded Jinja subset and reject unsafe variants."""
    all_nodes = list(parsed.find_all(nodes.Node))
    if len(all_nodes) > MAX_TEMPLATE_AST_NODES:
        raise TemplateResourceLimitError("Template troppo complesso")

    banned = next(parsed.find_all(_BANNED_NODES), None)
    if banned is not None:
        raise TemplateResourceLimitError(
            f"Costrutto template non consentito: {type(banned).__name__}"
        )

    macros = list(parsed.find_all(nodes.Macro))
    loops = list(parsed.find_all(nodes.For))
    calls = list(parsed.find_all(nodes.Call))
    concats = list(parsed.find_all(nodes.Concat))
    filters = list(parsed.find_all(nodes.Filter))
    tests = list(parsed.find_all(nodes.Test))
    additions = list(parsed.find_all(nodes.Add))
    _validate_node_counts(
        (macros, MAX_TEMPLATE_MACROS, "Troppe macro nel template"),
        (loops, MAX_TEMPLATE_LOOPS, "Troppi cicli nel template"),
        (calls, MAX_TEMPLATE_CALLS, "Troppe chiamate nel template"),
        (concats, MAX_TEMPLATE_CONCATS, "Troppe concatenazioni nel template"),
        (filters, MAX_TEMPLATE_FILTERS, "Troppi filtri nel template"),
        (tests, MAX_TEMPLATE_FILTERS, "Troppi test nel template"),
        (additions, MAX_TEMPLATE_LIST_APPENDS, "Troppe append nel template"),
    )

    macro_names = {macro.name for macro in macros}
    assigned_names = {
        assignment.target.name
        for assignment in parsed.find_all(nodes.Assign)
        if isinstance(assignment.target, (nodes.Name, nodes.NSRef))
    }
    iterable_is_bounded = _build_bounded_iterable_checker(parsed)
    is_template_collection = _build_template_collection_checker(parsed)
    _validate_loop_depth(parsed)
    _validate_macro_graph(macros, macro_names)
    _validate_macro_outputs(macros, macro_names)
    _validate_effective_loop_depth(parsed, macros)
    _validate_loop_sources(parsed, iterable_is_bounded)
    for call in calls:
        _validate_call(call, macro_names, assigned_names, iterable_is_bounded)
    for concat in concats:
        if len(concat.nodes) > MAX_TEMPLATE_CONCAT_PARTS:
            raise TemplateResourceLimitError("Concatenazione template troppo complessa")
    for addition in additions:
        _validate_list_append(addition)
    _validate_repeated_operations(
        parsed,
        parents=_build_parent_map(parsed),
    )
    _validate_concat_chains(parsed)
    _validate_collection_materialization(
        parsed,
        is_template_collection,
        iterable_is_bounded,
    )
    for literal in parsed.find_all((nodes.List, nodes.Tuple, nodes.Dict)):
        _validate_literal_size(literal)
    for template_filter in filters:
        _validate_filter(template_filter)
    for template_test in tests:
        _validate_test(template_test)


def _validate_node_counts(*limits: tuple[list[Any], int, str]) -> None:
    for values, maximum, message in limits:
        if len(values) > maximum:
            raise TemplateResourceLimitError(message)


def _validate_loop_depth(node: nodes.Node, depth: int = 0) -> None:
    next_depth = depth + 1 if isinstance(node, nodes.For) else depth
    if next_depth > MAX_TEMPLATE_LOOP_DEPTH:
        raise TemplateResourceLimitError("Cicli template troppo annidati")
    if isinstance(node, nodes.For) and node.recursive:
        raise TemplateResourceLimitError("Cicli ricorsivi non consentiti")
    for child in node.iter_child_nodes():
        _validate_loop_depth(child, next_depth)


def _build_bounded_iterable_checker(
    parsed: nodes.Template,
) -> Callable[[nodes.Node], bool]:
    """Resolve whether an expression stays bounded when used as an iterable."""
    return _AssignmentGraph(parsed).is_bounded_iterable


def _build_template_collection_checker(
    parsed: nodes.Template,
) -> Callable[[nodes.Node], bool]:
    """Track collections assembled by the template through aliases/containers."""
    return _AssignmentGraph(parsed).is_template_collection


class _AssignmentGraph:
    """Resolve value provenance across assignments without recursive closures."""

    def __init__(self, parsed: nodes.Template) -> None:
        self.assignments: dict[tuple[str, ...], list[nodes.Node]] = {}
        for assignment in parsed.find_all(nodes.Assign):
            key = _assignment_target_key(assignment.target)
            if key is not None:
                self.assignments.setdefault(key, []).append(assignment.node)

    def _sources(self, key: tuple[str, ...]) -> list[nodes.Node]:
        sources = self.assignments.get(key)
        if sources is None and len(key) > 1:
            sources = self.assignments.get((key[0],))
        return sources or []

    def is_bounded_iterable(
        self,
        expression: nodes.Node,
        active_keys: frozenset[tuple[str, ...]] = frozenset(),
    ) -> bool:
        if isinstance(expression, nodes.Filter):
            return True
        if isinstance(expression, nodes.Call):
            return self._is_bounded_call(expression)
        if isinstance(expression, nodes.Const):
            return self._is_bounded_constant(expression)
        if isinstance(expression, (nodes.List, nodes.Tuple)):
            return self._is_bounded_sequence(expression, active_keys)
        if isinstance(expression, nodes.Dict):
            return self._is_bounded_dict(expression, active_keys)
        if isinstance(expression, nodes.CondExpr):
            return self._is_bounded_condition(expression, active_keys)
        if isinstance(expression, nodes.Getitem):
            return self.is_bounded_iterable(expression.node, active_keys)
        if isinstance(expression, nodes.Add):
            return self._is_bounded_list_append(expression, active_keys)
        return self._reference_is_bounded(expression, active_keys)

    def _is_bounded_list_append(
        self,
        expression: nodes.Add,
        active_keys: frozenset[tuple[str, ...]],
    ) -> bool:
        """Keep a statically guarded namespace-list append iterable."""
        if not isinstance(expression.right, nodes.List):
            return False
        if len(expression.right.items) > 8:
            return False
        key = _assignment_target_key(expression.left)
        if key is None:
            return False
        accumulated_items = sum(
            len(source.right.items)
            for source in self._sources(key)
            if isinstance(source, nodes.Add) and isinstance(source.right, nodes.List)
        )
        if accumulated_items > MAX_TEMPLATE_LITERAL_ITEMS:
            return False
        return self.is_bounded_iterable(expression.left, active_keys)

    @staticmethod
    def _is_bounded_call(expression: nodes.Call) -> bool:
        return (
            isinstance(expression.node, nodes.Getattr)
            and expression.node.attr == "split"
        )

    @staticmethod
    def _is_bounded_constant(expression: nodes.Const) -> bool:
        value = expression.value
        return not isinstance(value, str) or len(value) <= MAX_TEMPLATE_ITERATION_ITEMS

    def _is_bounded_sequence(
        self,
        expression: nodes.List | nodes.Tuple,
        active_keys: frozenset[tuple[str, ...]],
    ) -> bool:
        del active_keys
        return len(expression.items) <= MAX_TEMPLATE_LITERAL_ITEMS

    def _is_bounded_dict(
        self,
        expression: nodes.Dict,
        active_keys: frozenset[tuple[str, ...]],
    ) -> bool:
        return all(
            isinstance(pair.key, nodes.Const)
            and isinstance(pair.value, nodes.Const)
            and self.is_bounded_iterable(pair.key, active_keys)
            and self.is_bounded_iterable(pair.value, active_keys)
            for pair in expression.items
        )

    def _is_bounded_condition(
        self,
        expression: nodes.CondExpr,
        active_keys: frozenset[tuple[str, ...]],
    ) -> bool:
        return self.is_bounded_iterable(expression.expr1, active_keys) and (
            expression.expr2 is None
            or self.is_bounded_iterable(expression.expr2, active_keys)
        )

    def _reference_is_bounded(
        self,
        expression: nodes.Node,
        active_keys: frozenset[tuple[str, ...]],
    ) -> bool:
        key = _assignment_target_key(expression)
        if key is None:
            return False
        sources = self._sources(key)
        if not sources or key in active_keys:
            return True
        next_active = active_keys | {key}
        return all(self.is_bounded_iterable(value, next_active) for value in sources)

    def is_template_collection(
        self,
        expression: nodes.Node,
        active_keys: frozenset[tuple[str, ...]] = frozenset(),
    ) -> bool:
        if isinstance(expression, nodes.Filter):
            return False
        if isinstance(expression, (nodes.List, nodes.Tuple, nodes.Dict)):
            return True
        if isinstance(expression, nodes.Add):
            return isinstance(expression.right, nodes.List)
        if isinstance(expression, nodes.Call):
            return self._call_returns_collection(expression, active_keys)
        if isinstance(expression, nodes.Getitem):
            return self.is_template_collection(expression.node, active_keys)
        if isinstance(expression, nodes.CondExpr):
            return self._condition_returns_collection(expression, active_keys)
        key = _assignment_target_key(expression)
        if key is not None:
            return self._reference_is_collection(key, active_keys)
        return any(
            self.is_template_collection(child, active_keys)
            for child in expression.iter_child_nodes()
        )

    def _call_returns_collection(
        self,
        expression: nodes.Call,
        active_keys: frozenset[tuple[str, ...]],
    ) -> bool:
        if not isinstance(expression.node, nodes.Name):
            return False
        if expression.node.name != "namespace":
            return False
        return any(
            self.is_template_collection(item.value, active_keys)
            for item in expression.kwargs
        )

    def _condition_returns_collection(
        self,
        expression: nodes.CondExpr,
        active_keys: frozenset[tuple[str, ...]],
    ) -> bool:
        if self.is_template_collection(expression.expr1, active_keys):
            return True
        return expression.expr2 is not None and self.is_template_collection(
            expression.expr2,
            active_keys,
        )

    def _reference_is_collection(
        self,
        key: tuple[str, ...],
        active_keys: frozenset[tuple[str, ...]],
    ) -> bool:
        if key in active_keys:
            return False
        next_active = active_keys | {key}
        if any(
            self.is_template_collection(value, next_active)
            for value in self._sources(key)
        ):
            return True
        if len(key) != 1:
            return False
        return self._namespace_child_is_collection(key[0], next_active)

    def _namespace_child_is_collection(
        self,
        root: str,
        active_keys: frozenset[tuple[str, ...]],
    ) -> bool:
        for assignment_key, values in self.assignments.items():
            if len(assignment_key) <= 1 or assignment_key[0] != root:
                continue
            if any(self.is_template_collection(value, active_keys) for value in values):
                return True
        return False

    def derives_from_concat(
        self,
        expression: nodes.Node,
        active_keys: frozenset[tuple[str, ...]] = frozenset(),
    ) -> bool:
        if isinstance(expression, nodes.Concat):
            return True
        key = _assignment_target_key(expression)
        if key is not None and self._reference_derives_from_concat(key, active_keys):
            return True
        return any(
            self.derives_from_concat(child, active_keys)
            for child in expression.iter_child_nodes()
        )

    def _reference_derives_from_concat(
        self,
        key: tuple[str, ...],
        active_keys: frozenset[tuple[str, ...]],
    ) -> bool:
        sources = self._sources(key)
        if not sources or key in active_keys:
            return False
        next_active = active_keys | {key}
        return any(self.derives_from_concat(source, next_active) for source in sources)


def _validate_collection_materialization(
    parsed: nodes.Template,
    is_template_collection: Callable[[nodes.Node], bool],
    iterable_is_bounded: Callable[[nodes.Node], bool],
) -> None:
    """Reject eager stringification/comparison of template-built containers."""
    for output in parsed.find_all(nodes.Output):
        if any(is_template_collection(part) for part in output.nodes):
            raise TemplateResourceLimitError(
                "Output di collezione template non consentito"
            )
    for comparison in parsed.find_all((nodes.Compare, nodes.Test)):
        if isinstance(comparison, nodes.Compare) and _is_bounded_membership(
            comparison,
            iterable_is_bounded,
        ):
            continue
        if is_template_collection(comparison):
            raise TemplateResourceLimitError(
                "Confronto di collezione template non consentito"
            )
    for concatenation in parsed.find_all(nodes.Concat):
        if is_template_collection(concatenation):
            raise TemplateResourceLimitError(
                "Concatenazione di collezione template non consentita"
            )


def _is_bounded_membership(
    comparison: nodes.Compare,
    iterable_is_bounded: Callable[[nodes.Node], bool],
) -> bool:
    """Allow membership checks against a collection whose size is bounded."""
    return len(comparison.ops) == 1 and comparison.ops[0].op in {"in", "notin"} and (
        iterable_is_bounded(comparison.ops[0].expr)
    )


def _validate_loop_sources(
    parsed: nodes.Template,
    iterable_is_bounded: Callable[[nodes.Node], bool],
) -> None:
    """Reject loop sources that can escape the runtime iterable wrappers."""

    for loop in parsed.find_all(nodes.For):
        if not iterable_is_bounded(loop.iter):
            raise TemplateResourceLimitError("Sorgente ciclo non consentita")


def _assignment_target_key(target: nodes.Node) -> tuple[str, ...] | None:
    if isinstance(target, nodes.Name):
        return (target.name,)
    if isinstance(target, nodes.NSRef):
        return (target.name, target.attr)
    if isinstance(target, nodes.Getattr):
        parent = _assignment_target_key(target.node)
        return (*parent, target.attr) if parent is not None else None
    return None


def _validate_macro_graph(macros: list[nodes.Macro], macro_names: set[str]) -> None:
    graph: dict[str, set[str]] = {}
    for macro in macros:
        if len(macro.args) > 8 or len(macro.defaults) > 8:
            raise TemplateResourceLimitError("Macro template troppo complessa")
        graph[macro.name] = {
            call.node.name
            for call in macro.find_all(nodes.Call)
            if isinstance(call.node, nodes.Name) and call.node.name in macro_names
        }

    def visit(name: str, active: frozenset[str], depth: int) -> None:
        if name in active:
            raise TemplateResourceLimitError("Macro ricorsive non consentite")
        if depth > MAX_TEMPLATE_MACRO_CALL_DEPTH:
            raise TemplateResourceLimitError("Catena di macro troppo profonda")
        next_active = active | {name}
        for dependency in graph.get(name, set()):
            visit(dependency, next_active, depth + 1)

    for macro_name in graph:
        visit(macro_name, frozenset(), 1)


def _validate_macro_outputs(macros: list[nodes.Macro], macro_names: set[str]) -> None:
    """Bound Jinja's eagerly buffered macro return values."""
    for macro in macros:
        output_parts = sum(len(output.nodes) for output in macro.find_all(nodes.Output))
        if output_parts > MAX_TEMPLATE_MACRO_OUTPUT_PARTS:
            raise TemplateResourceLimitError("Output macro troppo complesso")
        nested_macro_calls = sum(
            1
            for call in macro.find_all(nodes.Call)
            if isinstance(call.node, nodes.Name) and call.node.name in macro_names
        )
        if nested_macro_calls > 1:
            raise TemplateResourceLimitError("Troppe chiamate dentro una macro")
        for loop in macro.find_all(nodes.For):
            for output in loop.find_all(nodes.Output):
                if any(
                    not isinstance(part, nodes.TemplateData) or part.data.strip()
                    for part in output.nodes
                ):
                    raise TemplateResourceLimitError(
                        "Output ripetuto dentro una macro non consentito"
                    )


def _validate_effective_loop_depth(
    parsed: nodes.Template,
    macros: list[nodes.Macro],
) -> None:
    """Count loop nesting across macro calls as it occurs at runtime."""
    macro_by_name = {macro.name: macro for macro in macros}

    def walk(node: nodes.Node, depth: int, active_macros: frozenset[str]) -> None:
        if isinstance(node, nodes.Macro):
            return
        next_depth = depth + 1 if isinstance(node, nodes.For) else depth
        if next_depth > MAX_TEMPLATE_LOOP_DEPTH:
            raise TemplateResourceLimitError("Cicli template troppo annidati")
        if isinstance(node, nodes.Call) and isinstance(node.node, nodes.Name):
            macro = macro_by_name.get(node.node.name)
            if macro is not None and macro.name not in active_macros:
                next_active = active_macros | {macro.name}
                for statement in macro.body:
                    walk(statement, next_depth, next_active)
        for child in node.iter_child_nodes():
            walk(child, next_depth, active_macros)

    walk(parsed, 0, frozenset())


def _validate_call(
    call: nodes.Call,
    macro_names: set[str],
    assigned_names: set[str],
    iterable_is_bounded: Callable[[nodes.Node], bool],
) -> None:
    if call.dyn_args is not None or call.dyn_kwargs is not None:
        raise TemplateResourceLimitError("Argomenti dinamici non consentiti")
    if len(call.args) + len(call.kwargs) > 8:
        raise TemplateResourceLimitError("Chiamata template troppo complessa")
    target = call.node
    if isinstance(target, nodes.Name):
        _validate_named_call(call, target.name, macro_names, iterable_is_bounded)
        return
    if isinstance(target, nodes.Getattr) and target.attr == "split":
        _validate_split_receiver(target.node, assigned_names)
        _validate_split_call(call)
        return
    raise TemplateResourceLimitError("Chiamata template non consentita")


def _validate_named_call(
    call: nodes.Call,
    name: str,
    macro_names: set[str],
    iterable_is_bounded: Callable[[nodes.Node], bool],
) -> None:
    if name == "namespace":
        if call.args:
            raise TemplateResourceLimitError(
                "namespace accetta soltanto campi nominati"
            )
        return
    if name not in macro_names:
        raise TemplateResourceLimitError("Chiamata template non consentita")
    if any(
        not iterable_is_bounded(argument)
        for argument in (*call.args, *(keyword.value for keyword in call.kwargs))
    ):
        raise TemplateResourceLimitError("Argomento macro non consentito")


def _validate_split_call(call: nodes.Call) -> None:
    if call.kwargs or len(call.args) > 2:
        raise TemplateResourceLimitError("Uso di split non consentito")
    if len(call.args) < 2:
        return
    maxsplit = call.args[1]
    if not isinstance(maxsplit, nodes.Const) or not isinstance(maxsplit.value, int):
        raise TemplateResourceLimitError("Limite split non valido")
    if maxsplit.value < 0 or maxsplit.value >= MAX_TEMPLATE_ITERATION_ITEMS:
        raise TemplateResourceLimitError("Limite split troppo alto")


def _validate_split_receiver(receiver: nodes.Node, assigned_names: set[str]) -> None:
    if isinstance(receiver, nodes.Const) and isinstance(receiver.value, str):
        return
    current = receiver
    while isinstance(current, nodes.Getattr):
        current = current.node
    if not isinstance(current, nodes.Name) or current.name in assigned_names:
        raise TemplateResourceLimitError("Receiver split non consentito")


def _validate_list_append(addition: nodes.Add) -> None:
    """Allow only the namespace-list append idiom used by documented presets."""
    if not isinstance(addition.left, nodes.Getattr) or not isinstance(
        addition.right, nodes.List
    ):
        raise TemplateResourceLimitError("Addizione template non consentita")
    if len(addition.right.items) > 8:
        raise TemplateResourceLimitError("Append template troppo grande")


def _validate_repeated_operations(
    node: nodes.Node,
    *,
    parents: dict[int, nodes.Node],
    repeated: bool = False,
    comparisons: set[int] | None = None,
) -> None:
    """Limit work whose cost is multiplied by loops or macro invocations."""
    if comparisons is None:
        comparisons = set()
    child_repeated = repeated or isinstance(node, (nodes.For, nodes.Macro))
    if isinstance(node, nodes.Concat) and child_repeated:
        raise TemplateResourceLimitError("Concatenazione ripetuta non consentita")
    if (
        isinstance(node, nodes.Add)
        and isinstance(node.right, nodes.List)
        and child_repeated
        and not _is_guarded_repeated_append(node, parents)
    ):
        raise TemplateResourceLimitError("Append ripetuta non consentita")
    if isinstance(node, (nodes.Compare, nodes.Test)) and child_repeated:
        comparisons.add(id(node))
        if len(comparisons) > MAX_TEMPLATE_REPEATED_COMPARISONS:
            raise TemplateResourceLimitError("Troppi confronti ripetuti nel template")
    for child in node.iter_child_nodes():
        _validate_repeated_operations(
            child,
            parents=parents,
            repeated=child_repeated,
            comparisons=comparisons,
        )


def _build_parent_map(parsed: nodes.Template) -> dict[int, nodes.Node]:
    return {
        id(child): parent
        for parent in parsed.find_all(nodes.Node)
        for child in parent.iter_child_nodes()
    }


def _is_guarded_repeated_append(
    addition: nodes.Add,
    parents: dict[int, nodes.Node],
) -> bool:
    """Accept only loop appends dominated by a small monotonic length guard."""
    assignment = parents.get(id(addition))
    if not isinstance(assignment, nodes.Assign) or assignment.node is not addition:
        return False
    condition = parents.get(id(assignment))
    if not isinstance(condition, nodes.If) or assignment not in condition.body:
        return False
    guarded_key = _bounded_length_guard_key(condition.test)
    if guarded_key is None:
        return False
    return _body_advances_collection(condition.body, guarded_key)


def _bounded_length_guard_key(test: nodes.Node) -> tuple[str, ...] | None:
    if isinstance(test, nodes.Or) or next(test.find_all(nodes.Or), None) is not None:
        return None
    comparisons = ([test] if isinstance(test, nodes.Compare) else []) + list(
        test.find_all(nodes.Compare)
    )
    for comparison in comparisons:
        if len(comparison.ops) != 1 or comparison.ops[0].op not in {"lt", "lteq"}:
            continue
        limit = comparison.ops[0].expr
        source = comparison.expr
        if not isinstance(limit, nodes.Const) or not isinstance(limit.value, int):
            continue
        if limit.value < 1 or limit.value > MAX_TEMPLATE_LITERAL_ITEMS:
            continue
        if not isinstance(source, nodes.Filter) or source.name != "length":
            continue
        if source.node is None:
            continue
        key = _assignment_target_key(source.node)
        if key is not None:
            return key
    return None


def _body_advances_collection(
    body: list[nodes.Node],
    guarded_key: tuple[str, ...],
) -> bool:
    for candidate in body:
        if not isinstance(candidate, nodes.Assign):
            continue
        if _assignment_target_key(candidate.target) != guarded_key:
            continue
        value = candidate.node
        if (
            isinstance(value, nodes.Add)
            and _assignment_target_key(value.left) == guarded_key
            and isinstance(value.right, nodes.List)
            and 0 < len(value.right.items) <= 8
        ):
            return True
    return False


def _validate_concat_chains(parsed: nodes.Template) -> None:
    """Prevent exponential growth through aliases of earlier concatenations."""
    assignments = _AssignmentGraph(parsed)
    for concatenation in parsed.find_all(nodes.Concat):
        if any(assignments.derives_from_concat(part) for part in concatenation.nodes):
            raise TemplateResourceLimitError(
                "Catena di concatenazioni template non consentita"
            )


def _validate_literal_size(literal: nodes.List | nodes.Tuple | nodes.Dict) -> None:
    items = literal.items
    if len(items) > MAX_TEMPLATE_LITERAL_ITEMS:
        raise TemplateResourceLimitError("Valore letterale template troppo grande")


def _validate_filter(template_filter: nodes.Filter) -> None:
    if template_filter.name not in ALLOWED_FILTERS:
        raise TemplateResourceLimitError(
            f"Filtro template non consentito: {template_filter.name}"
        )
    if template_filter.dyn_args is not None or template_filter.dyn_kwargs is not None:
        raise TemplateResourceLimitError("Argomenti filtro dinamici non consentiti")
    if len(template_filter.args) + len(template_filter.kwargs) > 8:
        raise TemplateResourceLimitError("Filtro template troppo complesso")
    if template_filter.name == "format":
        _validate_percent_format(template_filter)
    if template_filter.name == "join":
        _validate_join_filter(template_filter)


def _validate_test(template_test: nodes.Test) -> None:
    if template_test.name not in ALLOWED_TESTS:
        raise TemplateResourceLimitError(
            f"Test template non consentito: {template_test.name}"
        )
    if template_test.dyn_args is not None or template_test.dyn_kwargs is not None:
        raise TemplateResourceLimitError("Argomenti test dinamici non consentiti")
    if template_test.args or template_test.kwargs:
        raise TemplateResourceLimitError("Test template con argomenti non consentito")


def _validate_join_filter(template_filter: nodes.Filter) -> None:
    if not template_filter.args:
        return
    separator = template_filter.args[0]
    if not isinstance(separator, nodes.Const) or not isinstance(separator.value, str):
        raise TemplateResourceLimitError("Separatore join dinamico non consentito")
    if len(separator.value) > 128:
        raise TemplateResourceLimitError("Separatore join troppo lungo")


def _validate_percent_format(template_filter: nodes.Filter) -> None:
    source = template_filter.node
    if not isinstance(source, nodes.Const) or not isinstance(source.value, str):
        raise TemplateResourceLimitError("Formato dinamico non consentito")
    value = source.value
    if len(value) > 128 or "*" in value:
        raise TemplateResourceLimitError("Formato template troppo grande")
    position = 0
    while position < len(value):
        marker = value.find("%", position)
        if marker < 0:
            break
        if marker + 1 < len(value) and value[marker + 1] == "%":
            position = marker + 2
            continue
        match = _PERCENT_FORMAT_TOKEN.match(value, marker)
        if match is None:
            raise TemplateResourceLimitError("Formato template non consentito")
        for group in ("width", "precision"):
            raw = match.group(group)
            if raw and int(raw) > MAX_TEMPLATE_FORMAT_WIDTH:
                raise TemplateResourceLimitError("Formato template troppo grande")
        position = match.end()


__all__ = [
    "ALLOWED_FILTERS",
    "ALLOWED_TESTS",
    "MAX_TEMPLATE_ITERATION_ITEMS",
    "MAX_TEMPLATE_MACRO_OUTPUT_PARTS",
    "MAX_TEMPLATE_WORK_UNITS",
    "TemplateResourceLimitError",
    "bounded_template_filter",
    "bound_template_context",
    "consume_template_work",
    "template_work_units",
    "template_iteration_budget",
    "validate_template_ast",
]
