"""EvoFlux Workflows — inline node-graph pipelines.

Design: docs/plans/workflows-feature-plan.md (v5). A workflow is a
YAML file (canvas-editable) executed **inline in an existing chat
session** — ordinary turns, no durable run entity. This package is the
engine: definition models, graph semantics, templating, policy
(hash/manifest/lint), and (from M3) the runner.
"""
