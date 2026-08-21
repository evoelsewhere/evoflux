"""Tool decorator and Tool class for LLM function-calling.

Parameter descriptions are defined via ``Annotated[type, Field(description=...)]``
directly on the function signature. The docstring describes the tool's use case
for the LLM — no ``Args:`` section required.

Usage::

    from typing import Annotated
    from pydantic import Field
    from app.agent.tools import tool

    @tool
    def search(
        query: Annotated[str, Field(description="The search query string.")],
        max_results: Annotated[int, Field(description="Max results to return.")] = 5,
    ) -> list:
        \"\"\"Search the web for current information and news.\"\"\"
        ...

    @tool(name="custom_name")
    def another_func(
        url: Annotated[str, Field(description="The URL to fetch.")],
    ) -> str:
        \"\"\"Fetch and convert a web page to Markdown.\"\"\"
        ...

Tools are callable (original function behaviour is preserved) and carry
LLM-compatible metadata via ``.name``, ``.description``, and ``.definition``.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import (
    Annotated,
    Any,
    Callable,
    cast,
    get_args,
    get_origin,
    get_type_hints,
    overload,
)

from pydantic import BaseModel, ValidationError, create_model

from loguru import logger

from app.agent.errors import ToolArgumentError, ToolExecutionError


# ``resource_revision, start, end`` for a finite, revision-bound observation.
# The agent loop uses this contract to recognize a later request that is fully
# covered by an earlier source range without knowing anything about tool names.
ObservationRange = tuple[str, int, int]


class InjectedArg:
    """Marker: annotate a tool parameter with this to hide it from the LLM schema
    and have it injected automatically at call time by the agent.

    The agent passes a ``_injected`` dict to :meth:`Tool.arun`; any parameter
    annotated ``Annotated[T, InjectedArg()]`` receives its value from that dict
    (keyed by the parameter name) and is excluded from the OpenAI tool schema so
    the LLM never sees or fills it.

    Usage::

        async def my_tool(
            query: Annotated[str, Field(description="Search query")],
            _state: Annotated["AgentState | None", InjectedArg()] = None,
        ) -> str:
            # _state is injected by the agent; use it to read messages,
            # session_id, context, etc.
            ...

    The agent calls::

        result = await tool.arun(_injected={"_state": state}, query="...")
    """


def _is_injected(annotation: Any) -> bool:
    """Return True if the annotation contains an InjectedArg marker."""
    if get_origin(annotation) is Annotated:
        for meta in get_args(annotation)[1:]:
            if isinstance(meta, InjectedArg):
                return True
    return False


def _resolve_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline ``$ref`` pointers and drop ``$defs`` from a JSON Schema.

    Pydantic v2's ``model_json_schema()`` emits ``$defs`` + ``$ref`` when a
    parameter uses a nested Pydantic model (e.g. ``list[RememberItem]``).
    Some LLM providers (Gemini, Vertex) reject ``$ref`` outright, so we
    resolve every reference in-place and strip the ``$defs`` block.

    Also strips ``title`` from inlined definitions since providers don't need it.
    """
    defs = schema.get("$defs", {})
    if not defs:
        return schema

    def _inline(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                ref_path = node["$ref"]  # e.g. "#/$defs/RememberItem"
                ref_name = ref_path.rsplit("/", 1)[-1]
                resolved = defs.get(ref_name, node)
                # Deep-copy and recurse (defs can themselves contain $ref)
                resolved = _inline({k: v for k, v in resolved.items()})
                resolved.pop("title", None)
                return resolved
            return {k: _inline(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_inline(item) for item in node]
        return node

    result = _inline({k: v for k, v in schema.items() if k != "$defs"})
    return result


class Tool:
    """A callable function decorated with LLM function-calling metadata.

    Wraps a plain Python function (sync or async) and exposes:

    * ``.name`` — tool name used in function-calling payloads
    * ``.description`` — use-case description sent to the LLM (from docstring)
    * ``.definition`` — OpenAI-compatible tool definition dict
    * Direct call — ``tool_obj(...)`` delegates to the original function
    * ``await tool_obj.arun(...)`` — validates args with Pydantic, then calls
      the function (supports both sync and async underlying functions)

    Parameter descriptions are sourced from ``Field(description=...)`` inside
    ``Annotated`` type hints on the function signature.
    """

    def __init__(
        self,
        func: Callable,
        *,
        name: str | None = None,
        description: str | Callable[[], str] | None = None,
        concurrency_safe: bool = False,
        read_only: bool = False,
        tiers: tuple[str, ...] | None = None,
        lead_only: bool = False,
        deferred: bool = False,
        deferred_summary: str | None = None,
        search_aliases: tuple[str, ...] = (),
        capabilities: tuple[str, ...] = (),
        max_calls_per_batch: int | None = None,
        deduplicate_in_batch: bool = False,
        observation_kind: str | None = None,
        observation_key: Callable[[dict[str, Any]], str | None] | None = None,
        observation_range: Callable[[dict[str, Any]], ObservationRange | None]
        | None = None,
    ) -> None:
        self._func = func
        # ``Callable`` is the abstract type; only function objects guarantee
        # ``__name__``. Fall back to ``repr`` for callables that don't (e.g.
        # ``functools.partial``) — the explicit *name* kwarg should be used
        # in that case.
        self.name = name or getattr(func, "__name__", repr(func))
        self._custom_description = description
        # Whether this tool can safely run in parallel with other tools in the
        # same LLM turn.  Read-only tools (grep, read, web_search, etc.) are
        # safe; write tools (edit, shell, python, etc.) must run serially to
        # prevent races on shared resources.
        self.concurrency_safe = concurrency_safe
        # Whether this tool only reads state and never modifies it.  Used by
        # future permission-system shortcuts (read-only tools can skip the
        # ``ask`` prompt in default mode).
        self.read_only = read_only
        # Team-tier membership. ``None`` means the tool belongs to every tier
        # ("work", "coding", ...) — the default, so newly registered tools are
        # available everywhere without extra wiring. Set an explicit tuple to
        # restrict, e.g. ``tiers=("work",)``.
        self.tiers = frozenset(tiers) if tiers is not None else None
        # Tools that talk to the user or restructure the session (ask_user,
        # plan mode, worktree, ...) are lead-only: team members never get them.
        self.lead_only = lead_only
        # Deferred tools remain executable by this agent but omit their full
        # schema until the model explicitly activates them via load_tool.
        self.deferred = deferred
        self.deferred_summary = deferred_summary
        # Extra vocabulary for load_tool's keyword search only — never shown to
        # the model. ``deferred_summary`` doubles as the search haystack, and it
        # is written for a human reader, so the words a model actually queries
        # with ("lint", "chart", "screenshot") are often absent from it. List
        # those synonyms, file formats, and underlying technologies here rather
        # than distorting the summary into keyword soup.
        self.search_aliases = tuple(
            alias.casefold() for alias in search_aliases if alias.strip()
        )
        # Runtime policies consume explicit capabilities, never inferred names.
        self.capabilities = frozenset(
            capability.casefold() for capability in capabilities
        )
        self.origin = "builtin"
        self.max_calls_per_batch = max_calls_per_batch
        self.deduplicate_in_batch = deduplicate_in_batch
        self.observation_kind = observation_kind
        self.observation_key = observation_key
        self.observation_range = observation_range

        self._model, self._definition, self._injected_params = self._build()
        self._description_factory: Callable[[], str] | None = (
            cast(Callable[[], str], description) if callable(description) else None
        )

        # Preserve function metadata so the Tool looks like the original function
        self.__name__ = self.name
        self.__doc__ = func.__doc__
        self.__wrapped__ = func

    # ------------------------------------------------------------------
    # Callable interface — keeps the original function behaviour
    # ------------------------------------------------------------------

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._func(*args, **kwargs)

    def __repr__(self) -> str:
        return f"Tool(name={self.name!r})"

    # ------------------------------------------------------------------
    # LLM-facing metadata
    # ------------------------------------------------------------------

    @property
    def description(self) -> str:
        if self._description_factory is not None:
            return self._description_factory()
        return self._definition["function"]["description"]

    @property
    def definition(self) -> dict[str, Any]:
        """OpenAI-compatible tool definition dict."""
        if self._description_factory is None:
            return self._definition
        definition = {
            **self._definition,
            "function": {**self._definition["function"]},
        }
        definition["function"]["description"] = self._description_factory()
        return definition

    # ------------------------------------------------------------------
    # Validated execution (used by Agent)
    # ------------------------------------------------------------------

    async def arun(self, _injected: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        """Execute the tool with Pydantic validation.

        Args:
            _injected: Optional dict of runtime-injected values for parameters
                annotated with :class:`InjectedArg`.  These are merged into the
                call after validation and are never exposed to the LLM.  The
                standard key is ``"_state"`` (an :class:`~app.core.state.AgentState`
                instance).
            **kwargs: LLM-provided arguments (validated against the schema).

        Raises:
            :exc:`~app.core.errors.ToolArgumentError`: When Pydantic validation
                of LLM-provided arguments fails.
            :exc:`~app.core.errors.ToolExecutionError`: When the underlying tool
                function raises any other exception.

        Supports both synchronous and asynchronous underlying functions.
        """
        logger.debug("tool_arun tool={} kwargs={}", self.name, list(kwargs.keys()))
        # Strip injected param names that might accidentally appear in kwargs
        llm_kwargs = {k: v for k, v in kwargs.items() if k not in self._injected_params}
        try:
            validated_model = self._model(**llm_kwargs)
        except ValidationError as exc:
            raise ToolArgumentError(
                f"Invalid arguments for tool '{self.name}': {exc}"
            ) from exc
        # Build kwargs from model attributes — preserves nested Pydantic model
        # instances (e.g. list[RememberItem]) instead of collapsing them to dicts
        # as model_dump() would do.
        validated: dict[str, Any] = {
            field: getattr(validated_model, field)
            for field in validated_model.model_fields
        }
        # Merge injected values (not validated — they come from trusted internal code)
        if _injected and self._injected_params:
            for pname in self._injected_params:
                if pname in _injected:
                    validated[pname] = _injected[pname]
        try:
            if inspect.iscoroutinefunction(self._func):
                return await self._func(**validated)
            return self._func(**validated)
        except (ToolArgumentError, ToolExecutionError):
            raise  # already domain errors — let them propagate unchanged
        except (
            FileNotFoundError,
            FileExistsError,
            IsADirectoryError,
            NotADirectoryError,
            OSError,
            ValueError,
        ) as exc:
            # Me message already clear — no need add noise
            raise ToolExecutionError(str(exc)) from exc
        except Exception as exc:
            raise ToolExecutionError(
                f"Tool '{self.name}' raised {type(exc).__name__}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Schema / definition builder
    # ------------------------------------------------------------------

    def _build(self) -> tuple[type[BaseModel], dict[str, Any], set[str]]:
        func = self._func
        sig = inspect.signature(func)

        # Description: custom override or the full docstring (use-case focused)
        raw_doc = inspect.getdoc(func) or ""
        description = (
            raw_doc.strip()
            if self._custom_description is None or callable(self._custom_description)
            else self._custom_description
        )

        # include_extras=True preserves Annotated[..., Field(...)] wrappers so
        # Pydantic picks up Field metadata (description, constraints) when
        # generating the JSON Schema.
        type_hints = get_type_hints(func, include_extras=True)

        fields: dict[str, Any] = {}
        injected_params: set[str] = set()

        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue
            annotation = type_hints.get(param_name, Any)
            # Skip InjectedArg params — they are not part of the LLM schema
            if _is_injected(annotation):
                injected_params.add(param_name)
                continue
            default = (
                param.default if param.default is not inspect.Parameter.empty else ...
            )
            fields[param_name] = (annotation, default)

        ParameterModel = create_model(f"{self.name}_parameters", **fields)
        schema = ParameterModel.model_json_schema()

        # Resolve $ref pointers — Pydantic emits $defs + $ref for nested
        # models (e.g. list[SomeModel]).  Gemini and other providers reject
        # $ref, so we inline every reference and drop the $defs block.
        schema = _resolve_refs(schema)

        properties: dict[str, Any] = schema.get("properties", {})
        required: list[str] = schema.get("required", [])

        # Strip Pydantic-generated noise (title on each property)
        for prop in properties.values():
            prop.pop("title", None)

        definition: dict[str, Any] = {
            "type": "function",
            "function": {
                "name": self.name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

        return ParameterModel, definition, injected_params


# ---------------------------------------------------------------------------
# Deferred-tool catalog
# ---------------------------------------------------------------------------

#: Longest ``deferred_summary`` derived from a description before truncation.
_MAX_DERIVED_SUMMARY_CHARS = 200


@dataclass(frozen=True, slots=True)
class DeferredToolEntry:
    """One deferred tool as ``load_tool`` offers it to the model.

    ``summary`` is the only field the model ever sees. ``aliases`` widens what
    a search matches without turning the summary into keyword soup, so the two
    are kept apart rather than concatenated.
    """

    summary: str
    aliases: tuple[str, ...] = ()


def deferred_catalog_entry(tool: Tool) -> DeferredToolEntry:
    """Describe *tool* for the run-local deferred catalog.

    Tools that declare no ``deferred_summary`` fall back to a compacted,
    truncated description so every deferred tool stays discoverable.
    """
    summary = tool.deferred_summary
    if not summary:
        compact = " ".join(tool.description.split())
        summary = (
            compact[: _MAX_DERIVED_SUMMARY_CHARS - 3] + "..."
            if len(compact) > _MAX_DERIVED_SUMMARY_CHARS
            else compact
        )
    return DeferredToolEntry(summary=summary, aliases=tool.search_aliases)


# ---------------------------------------------------------------------------
# @tool decorator
# ---------------------------------------------------------------------------


@overload
def tool(func: Callable) -> Tool: ...


@overload
def tool(
    func: None = None,
    *,
    name: str | None = None,
    description: str | Callable[[], str] | None = None,
    concurrency_safe: bool = False,
    read_only: bool = False,
    tiers: tuple[str, ...] | None = None,
    lead_only: bool = False,
    deferred: bool = False,
    deferred_summary: str | None = None,
    search_aliases: tuple[str, ...] = (),
    capabilities: tuple[str, ...] = (),
    max_calls_per_batch: int | None = None,
    deduplicate_in_batch: bool = False,
    observation_kind: str | None = None,
    observation_key: Callable[[dict[str, Any]], str | None] | None = None,
    observation_range: Callable[[dict[str, Any]], ObservationRange | None]
    | None = None,
) -> Callable[[Callable], Tool]: ...


def tool(
    func: Callable | None = None,
    *,
    name: str | None = None,
    description: str | Callable[[], str] | None = None,
    concurrency_safe: bool = False,
    read_only: bool = False,
    tiers: tuple[str, ...] | None = None,
    lead_only: bool = False,
    deferred: bool = False,
    deferred_summary: str | None = None,
    search_aliases: tuple[str, ...] = (),
    capabilities: tuple[str, ...] = (),
    max_calls_per_batch: int | None = None,
    deduplicate_in_batch: bool = False,
    observation_kind: str | None = None,
    observation_key: Callable[[dict[str, Any]], str | None] | None = None,
    observation_range: Callable[[dict[str, Any]], ObservationRange | None]
    | None = None,
) -> Tool | Callable[[Callable], Tool]:
    """Decorator that converts a function into a :class:`Tool`.

    Parameter descriptions belong on the signature via
    ``Annotated[type, Field(description=...)]``.
    The docstring should describe the tool's use case for the LLM.

    Can be used with or without arguments::

        @tool
        def my_func(
            x: Annotated[int, Field(description="The input value.")],
        ) -> str:
            \"\"\"Convert a number to its string representation.\"\"\"
            ...

        @tool(name="custom")
        def my_func(...): ...

    Args:
        func: The function to wrap (only when used as a bare ``@tool``).
        name: Override the tool name (defaults to the function name).
        description: Override the tool description (defaults to the docstring).

    Returns:
        A :class:`Tool` instance, or a decorator that returns one.
    """
    if func is not None:
        # Used as bare @tool (no parentheses)
        return Tool(func)

    # Used as @tool(...) with keyword arguments
    def decorator(f: Callable) -> Tool:
        return Tool(
            f,
            name=name,
            description=description,
            concurrency_safe=concurrency_safe,
            read_only=read_only,
            tiers=tiers,
            lead_only=lead_only,
            deferred=deferred,
            deferred_summary=deferred_summary,
            search_aliases=search_aliases,
            capabilities=capabilities,
            max_calls_per_batch=max_calls_per_batch,
            deduplicate_in_batch=deduplicate_in_batch,
            observation_kind=observation_kind,
            observation_key=observation_key,
            observation_range=observation_range,
        )

    return decorator
