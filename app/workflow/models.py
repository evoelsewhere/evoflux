"""Workflow definition models — the YAML schema (plan §4.2/§4.4).

Pure pydantic: no registry/roster/filesystem access here. Checks that need
the live environment (tool names, blueprint roster) take the known sets as
arguments (:func:`validate_environment`), so the definition layer stays
unit-testable and the API layer supplies reality.
"""

from __future__ import annotations

from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.chat import normalize_mode

#: v1 engine kinds. Phase 2 kinds (`workflow`, `wait`) validate from v1 so
#: files don't churn, but the runner refuses to execute them (plan §4.4).
ENGINE_KINDS_V1 = frozenset(
    {"agent", "tool", "gate", "switch", "input", "notify", "transform", "foreach"}
)
PHASE2_KINDS = frozenset({"workflow", "wait"})
ALL_KINDS = ENGINE_KINDS_V1 | PHASE2_KINDS

#: Foreach bodies allow a strict subset in v1 (plan §4.4).
FOREACH_BODY_KINDS = frozenset({"tool", "transform", "notify", "agent"})

#: Tools whose presence on an ungated path triggers the advisory lint.
DESTRUCTIVE_TOOLS = frozenset({"edit", "write", "patch", "rm", "shell", "python", "bg"})

WorkflowScope = Literal["work", "coding", "aim"]


class DefinitionError(ValueError):
    """A definition failed validation; ``errors`` lists every problem."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


class WorkflowInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    type: Literal["string", "number", "boolean", "enum"] = "string"
    required: bool = False
    default: Any | None = None
    options: list[str] | None = None
    description: str = ""

    @model_validator(mode="after")
    def _validate(self) -> "WorkflowInput":
        if self.type == "enum" and not self.options:
            raise ValueError(f"input '{self.name}': enum requires options.")
        return self


class ForeachBody(BaseModel):
    """The single inline node spec inside a foreach (no id, no edges)."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    # tool body
    tool: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    # transform body
    set: dict[str, str] | None = None
    # notify body
    title: str | None = None
    message: str | None = None
    # agent body
    subagents: list[str] | None = None
    prompt: str | None = None
    timeout_s: int | None = None

    @model_validator(mode="after")
    def _validate(self) -> "ForeachBody":
        if self.kind not in FOREACH_BODY_KINDS:
            raise ValueError(
                f"foreach body kind '{self.kind}' not allowed in v1 "
                f"(allowed: {sorted(FOREACH_BODY_KINDS)})."
            )
        _check_kind_payload(self, f"foreach body ({self.kind})")
        return self


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(min_length=1)
    kind: str

    # agent
    subagents: list[str] | None = None
    prompt: str | None = None
    timeout_s: int | None = None
    # tool
    tool: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    # gate
    title: str | None = None
    body: str | None = None
    choices: list[str] | None = None
    # switch
    value: str | None = None
    # input
    question: str | None = None
    # notify (shares `title`)
    message: str | None = None
    # transform
    set: dict[str, str] | None = None
    # foreach
    items: str | None = None
    foreach_body: ForeachBody | None = Field(default=None, alias="body_spec")
    # Phase 2
    workflow: str | None = None
    inputs: dict[str, Any] | None = None
    seconds: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _foreach_body_alias(cls, data: Any) -> Any:
        # In YAML the foreach body key is `body:` (plan §4.2) — but `body`
        # is also the gate's text field. Route by kind before field parsing.
        if isinstance(data, dict) and data.get("kind") == "foreach" and "body" in data:
            data = dict(data)
            data["body_spec"] = data.pop("body")
        return data

    @model_validator(mode="after")
    def _validate(self) -> "Node":
        if self.kind not in ALL_KINDS:
            raise ValueError(
                f"node '{self.id}': unknown kind '{self.kind}' "
                f"(known: {sorted(ALL_KINDS)})."
            )
        _check_kind_payload(self, f"node '{self.id}'")
        return self


def _check_kind_payload(node: Any, label: str) -> None:
    """Kind-specific required/forbidden fields (plan §4.4), shared between
    top-level nodes and foreach bodies."""
    kind = node.kind
    if kind == "agent":
        if node.prompt is None or not node.prompt.strip():
            raise ValueError(f"{label}: agent requires a prompt.")
        if node.subagents is None:
            raise ValueError(
                f"{label}: agent requires subagents (use [] for the lead solo)."
            )
        if getattr(node, "tool", None):
            raise ValueError(
                f"{label}: agents have no tool field — tools are configured "
                f"on the agent blueprint, not the node."
            )
    elif kind == "tool":
        if not node.tool:
            raise ValueError(f"{label}: tool nodes require a tool name.")
        if node.tool == "python" and "code" not in node.args:
            raise ValueError(f"{label}: python tool requires args.code.")
        if node.tool == "shell":
            if "command" not in node.args:
                raise ValueError(f"{label}: shell tool requires args.command.")
            if node.args.get("background"):
                raise ValueError(
                    f"{label}: background shell is not allowed in a workflow "
                    f"(a node must end when it ends)."
                )
    elif kind == "gate":
        if not node.choices:
            raise ValueError(f"{label}: gate requires non-empty choices.")
        if not node.title:
            raise ValueError(f"{label}: gate requires a title.")
    elif kind == "switch":
        if not node.value:
            raise ValueError(f"{label}: switch requires a value template.")
    elif kind == "input":
        if not node.question or not node.question.strip():
            raise ValueError(f"{label}: input requires a question.")
    elif kind == "notify":
        if not node.message or not node.message.strip():
            raise ValueError(f"{label}: notify requires a message.")
    elif kind == "transform":
        if not node.set:
            raise ValueError(f"{label}: transform requires a non-empty set map.")
    elif kind == "foreach":
        if not node.items:
            raise ValueError(f"{label}: foreach requires an items template.")
        if node.foreach_body is None:
            raise ValueError(f"{label}: foreach requires exactly one body node spec.")
    elif kind == "workflow":
        if not node.workflow:
            raise ValueError(f"{label}: workflow nodes require a target name.")
    elif kind == "wait":
        if node.seconds is None or not (1 <= int(node.seconds) <= 600):
            raise ValueError(f"{label}: wait requires seconds in 1..600.")


class Edge(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: str = Field(alias="from")
    to: str
    when: str | None = None


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    name: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
    description: str = ""
    scope: WorkflowScope = "work"
    inputs: list[WorkflowInput] = Field(default_factory=list)
    nodes: list[Node] = Field(min_length=1)
    edges: list[Edge] = Field(default_factory=list)
    outputs: dict[str, str] = Field(default_factory=dict)
    # Canvas layout only — engine ignores it, round-trips verbatim.
    ui: dict[str, Any] = Field(default_factory=dict)

    @field_validator("scope", mode="before")
    @classmethod
    def _normalize_scope(cls, value: object) -> object:
        return normalize_mode(value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def _validate(self) -> "WorkflowDefinition":
        errors: list[str] = []
        node_ids = [node.id for node in self.nodes]
        seen: set[str] = set()
        for node_id in node_ids:
            if node_id in seen:
                errors.append(f"duplicate node id '{node_id}'.")
            seen.add(node_id)
        for edge in self.edges:
            if edge.from_ not in seen:
                errors.append(f"edge references unknown node '{edge.from_}'.")
            if edge.to not in seen:
                errors.append(f"edge references unknown node '{edge.to}'.")

        by_id = {node.id: node for node in self.nodes}
        for node in self.nodes:
            outgoing = [edge for edge in self.edges if edge.from_ == node.id]
            if node.kind == "gate":
                choices = set(node.choices or [])
                for edge in outgoing:
                    if edge.when is None:
                        errors.append(
                            f"gate '{node.id}': outgoing edges must carry when."
                        )
                    elif edge.when not in choices:
                        errors.append(
                            f"gate '{node.id}': when '{edge.when}' is not a choice."
                        )
            elif node.kind == "switch":
                defaults = 0
                for edge in outgoing:
                    if edge.when is None:
                        errors.append(
                            f"switch '{node.id}': outgoing edges must carry when."
                        )
                    elif edge.when == "*":
                        defaults += 1
                if defaults > 1:
                    errors.append(f"switch '{node.id}': at most one default (*) edge.")
            else:
                for edge in outgoing:
                    if edge.when is not None:
                        errors.append(
                            f"node '{node.id}' ({node.kind}): only gate/switch "
                            f"edges may carry when."
                        )

        input_names = [inp.name for inp in self.inputs]
        if len(input_names) != len(set(input_names)):
            errors.append("input names must be unique.")

        del by_id
        if errors:
            raise DefinitionError(errors)
        return self

    def entry_nodes(self) -> list[str]:
        targets = {edge.to for edge in self.edges}
        return [node.id for node in self.nodes if node.id not in targets]

    def has_phase2_nodes(self) -> bool:
        return any(node.kind in PHASE2_KINDS for node in self.nodes)


def parse_definition(raw_yaml: str) -> WorkflowDefinition:
    """Parse + validate one YAML document into a definition.

    Raises :class:`DefinitionError` with every collected problem (schema
    errors from pydantic are flattened into the same list) — the API layer
    returns these as 422 field errors.
    """
    try:
        data = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as exc:
        raise DefinitionError([f"YAML parse error: {exc}"])
    if not isinstance(data, dict):
        raise DefinitionError(["a workflow file must be a YAML mapping."])
    try:
        return WorkflowDefinition.model_validate(data)
    except DefinitionError:
        raise
    except Exception as exc:  # pydantic ValidationError → flat message list
        from pydantic import ValidationError

        if isinstance(exc, ValidationError):
            errors = []
            for err in exc.errors():
                loc = ".".join(str(piece) for piece in err["loc"])
                errors.append(f"{loc}: {err['msg']}" if loc else err["msg"])
            raise DefinitionError(errors)
        raise DefinitionError([str(exc)])


def validate_environment(
    definition: WorkflowDefinition,
    *,
    known_tools: set[str],
    known_blueprints: set[str],
) -> list[str]:
    """Environment-dependent checks (plan §4.4): tool names must exist in
    the registry (or be ``mcp_<server>_<tool>``), agent rosters must name
    known ``role: member`` blueprints. Returns errors, empty = fine."""
    errors: list[str] = []

    def _check(node_like: Any, label: str) -> None:
        if node_like.kind == "tool" and node_like.tool:
            if node_like.tool not in known_tools and not node_like.tool.startswith(
                "mcp_"
            ):
                errors.append(
                    f"{label}: unknown tool '{node_like.tool}' "
                    f"(not in the registry, not an mcp_<server>_<tool> name)."
                )
        if node_like.kind == "agent":
            for name in node_like.subagents or []:
                if name not in known_blueprints:
                    errors.append(
                        f"{label}: unknown subagent '{name}' "
                        f"(available: {sorted(known_blueprints) or 'none'})."
                    )

    for node in definition.nodes:
        _check(node, f"node '{node.id}'")
        if node.kind == "foreach" and node.foreach_body is not None:
            _check(node.foreach_body, f"node '{node.id}' body")
    return errors


def dump_definition_yaml(definition: WorkflowDefinition) -> str:
    """Canonical YAML for a definition (canvas save path)."""
    data = definition.model_dump(
        by_alias=True, exclude_none=True, exclude_defaults=False
    )
    # Re-alias the foreach body back to its YAML spelling and drop empty
    # args maps so canonical files stay tidy.
    for node in data.get("nodes", []):
        if node.get("kind") == "foreach" and "body_spec" in node:
            node["body"] = node.pop("body_spec")
        if node.get("args") == {}:
            node.pop("args")
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
