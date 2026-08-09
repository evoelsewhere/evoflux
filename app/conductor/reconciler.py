from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

import yaml

from app.agent.config import AgentConfig
from app.agent.mcp.config import (
    HttpServerConfig,
    OAuthConfig,
    StdioServerConfig,
    load_config,
    save_config,
)
from app.conductor.models import (
    DriftCategory,
    DriftRecord,
    Manifest,
    ManifestResource,
    ReconcileResult,
    ResourceResult,
    ResourceKind,
    canonical_hash,
)
from app.core.config import settings
from app.core.skill_settings import (
    skill_settings_id,
    write_skill_runtime_settings,
)
from app.services import agent_fs, team_manager


@dataclass(frozen=True)
class StagedResource:
    resource: ManifestResource
    artifact_hash: str
    content: Any


def _atomic_json(path: Path, value: Any, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class ResourceReconciler:
    def __init__(self, state_dir: Path | None = None) -> None:
        self.state_dir = state_dir or Path(settings.EVOFLUX_STATE_DIR) / "conductor"
        self.metadata_path = self.state_dir / "managed-state.json"
        self.last_good_path = self.state_dir / "last-known-good-manifest.json"

    def load_last_good_manifest(self) -> Manifest | None:
        try:
            return Manifest.model_validate_json(
                self.last_good_path.read_text(encoding="utf-8")
            )
        except FileNotFoundError:
            return None

    def save_last_good_manifest(self, manifest: Manifest) -> None:
        _atomic_json(self.last_good_path, manifest.model_dump(mode="json"))

    def _load_metadata(self) -> dict[str, dict[str, str]]:
        try:
            raw = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        resources = raw.get("resources", {}) if isinstance(raw, dict) else {}
        return resources if isinstance(resources, dict) else {}

    def stage(self, manifest: Manifest) -> list[StagedResource]:
        staged: list[StagedResource] = []
        for resource in manifest.resources:
            if resource.kind == "agent":
                content = self._render_agent(resource)
                staged.append(
                    StagedResource(resource, canonical_hash(content), content)
                )
            elif resource.kind == "skill":
                content = self._render_skill(resource)
                staged.append(
                    StagedResource(resource, canonical_hash(content), content)
                )
            else:
                content = self._render_mcp(resource)
                staged.append(
                    StagedResource(
                        resource,
                        canonical_hash(content.model_dump(mode="json")),
                        content,
                    )
                )
        return staged

    def _render_agent(self, resource: ManifestResource) -> str:
        payload = resource.payload
        frontmatter = payload.get("frontmatter")
        prompt = payload.get("system_prompt")
        if not isinstance(frontmatter, dict) or not isinstance(prompt, str):
            raise ValueError(f"Invalid agent payload for {resource.slug}.")
        meta = dict(frontmatter)
        meta.setdefault("name", Path(resource.slug).name)
        AgentConfig.model_validate({**meta, "system_prompt": prompt or " "})
        serialized = yaml.safe_dump(meta, sort_keys=False).strip()
        return f"---\n{serialized}\n---\n{prompt.rstrip()}\n"

    def _render_skill(self, resource: ManifestResource) -> dict[str, Any]:
        payload = resource.payload
        skill_md = payload.get("skill_md")
        if not isinstance(skill_md, str) or not skill_md.strip():
            raise ValueError(f"Invalid skill payload for {resource.slug}.")
        files: dict[str, str] = {}
        for item in payload.get("files", []):
            if not isinstance(item, dict):
                raise ValueError(f"Invalid skill file in {resource.slug}.")
            path = item.get("path")
            content = item.get("content")
            if not isinstance(path, str) or not isinstance(content, str):
                raise ValueError(f"Invalid skill file in {resource.slug}.")
            rel = PurePosixPath(path)
            if (
                not path
                or "\\" in path
                or rel.is_absolute()
                or any(part in {"", ".", ".."} for part in rel.parts)
                or rel.name in {"SKILL.md", ".evoflux.json"}
            ):
                raise ValueError(f"Unsafe skill file path: {path!r}.")
            if path in files:
                raise ValueError(f"Duplicate skill file path: {path!r}.")
            files[path] = content
        modes = payload.get("modes", ["work", "coding"])
        if not isinstance(modes, list) or any(
            mode not in {"work", "coding"} for mode in modes
        ):
            raise ValueError(f"Invalid skill modes for {resource.slug}.")
        return {
            "skill_md": skill_md,
            "files": files,
            "modes": modes,
            "allow_implicit_invocation": bool(
                payload.get("allow_implicit_invocation", True)
            ),
            "user_invocable": bool(payload.get("user_invocable", True)),
        }

    def _render_mcp(
        self, resource: ManifestResource
    ) -> StdioServerConfig | HttpServerConfig:
        payload = dict(resource.payload)
        payload.pop("oauth_tokens", None)
        transport = payload.get("transport", "stdio")
        if transport == "stdio":
            return StdioServerConfig.model_validate(payload)
        if transport == "http":
            return HttpServerConfig.model_validate(payload)
        raise ValueError(f"Unsupported MCP transport for {resource.slug}.")

    def classify_drift(
        self, manifest: Manifest, staged: list[StagedResource] | None = None
    ) -> list[DriftRecord]:
        staged = staged or self.stage(manifest)
        metadata = self._load_metadata()
        desired = {(item.resource.kind, item.resource.slug): item for item in staged}
        drift: list[DriftRecord] = []
        for key, item in desired.items():
            state_key = f"{key[0]}/{key[1]}"
            recorded = metadata.get(state_key, {})
            actual = self._actual_hash(item)
            if actual is None:
                drift.append(
                    DriftRecord(
                        kind=key[0],
                        slug=key[1],
                        category="missing",
                        expected_revision=item.resource.revision,
                    )
                )
            elif recorded.get("revision") not in {None, item.resource.revision}:
                drift.append(
                    DriftRecord(
                        kind=key[0],
                        slug=key[1],
                        category="wrong_revision",
                        expected_revision=item.resource.revision,
                        actual_hash=actual,
                    )
                )
            if actual is not None and actual != item.artifact_hash:
                drift.append(
                    DriftRecord(
                        kind=key[0],
                        slug=key[1],
                        category="modified",
                        expected_revision=item.resource.revision,
                        actual_hash=actual,
                    )
                )
            for dependency in item.resource.dependencies:
                dependency_item = desired[(dependency.kind, dependency.slug)]
                dependency_key = f"{dependency.kind}/{dependency.slug}"
                dependency_state = metadata.get(dependency_key, {})
                dependency_missing = self._actual_hash(dependency_item) is None
                dependency_revision_wrong = (
                    dependency.revision is not None
                    and dependency_state.get("revision") != dependency.revision
                )
                if dependency_missing or dependency_revision_wrong:
                    drift.append(
                        DriftRecord(
                            kind=item.resource.kind,
                            slug=item.resource.slug,
                            category="dependency",
                            expected_revision=item.resource.revision,
                            message=(
                                f"Dependency {dependency.kind}/{dependency.slug} "
                                "is not at its required local state."
                            ),
                        )
                    )
        for state_key, recorded in metadata.items():
            try:
                kind, slug = state_key.split("/", 1)
            except ValueError:
                continue
            if (kind, slug) not in desired and kind in {"agent", "skill", "mcp"}:
                typed_kind = cast(ResourceKind, kind)
                drift.append(
                    DriftRecord(
                        kind=typed_kind,
                        slug=slug,
                        category="unexpected",
                        expected_revision=recorded.get("revision"),
                    )
                )
        if not manifest.policy.allow_local_resources:
            for kind, slug in self._local_resources() - set(desired):
                drift.append(
                    DriftRecord(
                        kind=kind,
                        slug=slug,
                        category="policy",
                        message="Local resources are disabled by Conductor policy.",
                    )
                )
        return drift

    async def reconcile(
        self, manifest: Manifest, *, enforcement_mode: str
    ) -> ReconcileResult:
        staged = self.stage(manifest)
        drift = self.classify_drift(manifest, staged)
        if not drift:
            return self._result(manifest, staged, drift, "in_sync")
        if enforcement_mode != "enforce":
            return self._result(manifest, staged, drift, "drifted")
        if self._requires_maintenance(staged, drift):
            return self._result(
                manifest,
                staged,
                drift,
                "blocked",
                maintenance_required=True,
            )

        backup_root = Path(tempfile.mkdtemp(prefix="evoflux-conductor-rollback-"))
        self._backup(backup_root)
        try:
            await self._apply(staged, manifest)
            metadata = {
                f"{item.resource.kind}/{item.resource.slug}": {
                    "revision": item.resource.revision,
                    "payload_hash": item.resource.hash
                    or canonical_hash(item.resource.payload),
                    "artifact_hash": item.artifact_hash,
                }
                for item in staged
            }
            _atomic_json(
                self.metadata_path,
                {
                    "version": 1,
                    "manifest_revision": manifest.revision,
                    "resources": metadata,
                },
            )
            self.save_last_good_manifest(manifest)
        except Exception:
            self._restore(backup_root)
            raise
        finally:
            shutil.rmtree(backup_root, ignore_errors=True)
        return self._result(manifest, staged, [], "applied")

    def _requires_maintenance(
        self, staged: list[StagedResource], drift: list[DriftRecord]
    ) -> bool:
        if not team_manager.has_active_team_turn():
            return False
        changed = {(item.kind, item.slug) for item in drift}
        if any(kind == "mcp" for kind, _ in changed):
            return True
        for item in staged:
            if (item.resource.kind, item.resource.slug) not in changed:
                continue
            if item.resource.kind == "agent":
                role = item.resource.payload.get("frontmatter", {}).get("role")
                if role == "lead":
                    return True
        return any(
            item.kind == "agent" and item.category == "unexpected" for item in drift
        )

    async def _apply(self, staged: list[StagedResource], manifest: Manifest) -> None:
        metadata = self._load_metadata()
        desired = {(item.resource.kind, item.resource.slug) for item in staged}
        for state_key in metadata:
            kind, slug = state_key.split("/", 1)
            if (kind, slug) not in desired:
                self._delete(kind, slug)
        if not manifest.policy.allow_local_resources:
            for kind, slug in self._local_resources() - desired:
                self._delete(kind, slug)

        mcp_cfg = load_config()
        mcp_changed = False
        for item in staged:
            resource = item.resource
            if resource.kind == "agent":
                agent_fs.write_agent(
                    resource.slug,
                    item.content,
                    create=resource.slug not in agent_fs.list_agents(),
                )
            elif resource.kind == "skill":
                self._write_skill(resource.slug, item.content)
            else:
                existing = mcp_cfg.servers.get(resource.slug)
                mcp_cfg.servers[resource.slug] = self._preserve_mcp_secrets(
                    item.content, existing
                )
                mcp_changed = True
        if mcp_changed:
            save_config(mcp_cfg)
            from app.agent.mcp import mcp_manager

            await mcp_manager.reload_from_config()

    def _write_skill(self, slug: str, payload: dict[str, Any]) -> None:
        root = agent_fs.skills_dir()
        target = (root / slug).resolve()
        if not target.is_relative_to(root):
            raise ValueError(f"Unsafe skill path: {slug}.")
        staging = Path(tempfile.mkdtemp(prefix=f".{slug}.", dir=root))
        try:
            (staging / "SKILL.md").write_text(payload["skill_md"], encoding="utf-8")
            for rel, content in payload["files"].items():
                path = staging / Path(*PurePosixPath(rel).parts)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            (staging / ".evoflux.json").write_text(
                json.dumps(
                    {
                        "modes": payload["modes"],
                        "allow_implicit_invocation": payload[
                            "allow_implicit_invocation"
                        ],
                        "user_invocable": payload["user_invocable"],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            old = target.with_name(f".{target.name}.old")
            shutil.rmtree(old, ignore_errors=True)
            if target.exists():
                os.replace(target, old)
            try:
                os.replace(staging, target)
            except Exception:
                if old.exists():
                    os.replace(old, target)
                raise
            shutil.rmtree(old, ignore_errors=True)
            settings_id = skill_settings_id(
                source="global-EvoFlux", root=root, stem=slug
            )
            write_skill_runtime_settings(
                settings_id,
                name=slug,
                source="global-EvoFlux",
                modes=payload["modes"],
                allow_implicit_invocation=payload["allow_implicit_invocation"],
                user_invocable=payload["user_invocable"],
            )
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _preserve_mcp_secrets(
        self,
        desired: StdioServerConfig | HttpServerConfig,
        existing: StdioServerConfig | HttpServerConfig | None,
    ) -> StdioServerConfig | HttpServerConfig:
        if isinstance(desired, StdioServerConfig) and isinstance(
            existing, StdioServerConfig
        ):
            return desired.model_copy(update={"env": {**existing.env, **desired.env}})
        if isinstance(desired, HttpServerConfig) and isinstance(
            existing, HttpServerConfig
        ):
            oauth = desired.oauth
            if existing.oauth:
                oauth = OAuthConfig(
                    client_id=(
                        oauth.client_id
                        if oauth and oauth.client_id
                        else existing.oauth.client_id
                    ),
                    client_secret=(
                        oauth.client_secret
                        if oauth and oauth.client_secret
                        else existing.oauth.client_secret
                    ),
                )
            return desired.model_copy(
                update={
                    "headers": {**existing.headers, **desired.headers},
                    "oauth": oauth,
                }
            )
        return desired

    def _actual_hash(self, item: StagedResource) -> str | None:
        resource = item.resource
        try:
            if resource.kind == "agent":
                return canonical_hash(agent_fs.read_agent(resource.slug).content)
            if resource.kind == "skill":
                root = agent_fs.skills_dir() / resource.slug
                files: dict[str, str] = {}
                for path in sorted(root.rglob("*")):
                    if path.is_file() and path.name not in {
                        "SKILL.md",
                        ".evoflux.json",
                    }:
                        files[path.relative_to(root).as_posix()] = path.read_text(
                            encoding="utf-8"
                        )
                sidecar = root / ".evoflux.json"
                runtime = (
                    json.loads(sidecar.read_text(encoding="utf-8"))
                    if sidecar.exists()
                    else {}
                )
                return canonical_hash(
                    {
                        "skill_md": (root / "SKILL.md").read_text(encoding="utf-8"),
                        "files": files,
                        "modes": runtime.get("modes", ["work", "coding"]),
                        "allow_implicit_invocation": runtime.get(
                            "allow_implicit_invocation", True
                        ),
                        "user_invocable": runtime.get("user_invocable", True),
                    }
                )
            cfg = load_config().servers.get(resource.slug)
            return (
                canonical_hash(cfg.model_dump(mode="json")) if cfg is not None else None
            )
        except (FileNotFoundError, UnicodeError, ValueError):
            return None

    def _local_resources(self) -> set[tuple[ResourceKind, str]]:
        resources: set[tuple[ResourceKind, str]] = {
            ("agent", name) for name in agent_fs.list_agents()
        }
        resources.update(("skill", name) for name in agent_fs.list_skills())
        resources.update(("mcp", name) for name in load_config().servers)
        return resources

    def _delete(self, kind: str, slug: str) -> None:
        if kind == "agent":
            try:
                agent_fs.delete_agent(slug)
            except agent_fs.AgentFsNotFoundError:
                pass
        elif kind == "skill":
            target = (agent_fs.skills_dir() / slug).resolve()
            if target.is_relative_to(agent_fs.skills_dir()) and target.is_dir():
                shutil.rmtree(target)
        elif kind == "mcp":
            cfg = load_config()
            if cfg.servers.pop(slug, None) is not None:
                save_config(cfg)

    def _backup(self, target: Path) -> None:
        for name, source in (
            ("agents", agent_fs.agents_dir()),
            ("skills", agent_fs.skills_dir()),
        ):
            if source.exists():
                shutil.copytree(source, target / name, symlinks=True)
        mcp_path = Path(settings.EVOFLUX_CONFIG_DIR) / "mcp.json"
        if mcp_path.exists():
            shutil.copy2(mcp_path, target / "mcp.json")
        skill_settings = Path(settings.EVOFLUX_CONFIG_DIR) / "skill-settings.json"
        if skill_settings.exists():
            shutil.copy2(skill_settings, target / "skill-settings.json")
        for name, source in (
            ("managed-state.json", self.metadata_path),
            ("last-known-good-manifest.json", self.last_good_path),
        ):
            if source.exists():
                shutil.copy2(source, target / name)

    def _restore(self, source: Path) -> None:
        for name, target in (
            ("agents", agent_fs.agents_dir()),
            ("skills", agent_fs.skills_dir()),
        ):
            shutil.rmtree(target, ignore_errors=True)
            if (source / name).exists():
                shutil.copytree(source / name, target, symlinks=True)
        mcp_path = Path(settings.EVOFLUX_CONFIG_DIR) / "mcp.json"
        mcp_path.unlink(missing_ok=True)
        if (source / "mcp.json").exists():
            shutil.copy2(source / "mcp.json", mcp_path)
        skill_settings = Path(settings.EVOFLUX_CONFIG_DIR) / "skill-settings.json"
        skill_settings.unlink(missing_ok=True)
        if (source / "skill-settings.json").exists():
            shutil.copy2(source / "skill-settings.json", skill_settings)
        for name, target in (
            ("managed-state.json", self.metadata_path),
            ("last-known-good-manifest.json", self.last_good_path),
        ):
            target.unlink(missing_ok=True)
            if (source / name).exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / name, target)

    def _result(
        self,
        manifest: Manifest,
        staged: list[StagedResource],
        drift: list[DriftRecord],
        state: Literal["in_sync", "applied", "drifted", "blocked", "error"],
        *,
        maintenance_required: bool = False,
    ) -> ReconcileResult:
        by_key: dict[tuple[ResourceKind, str], list[DriftCategory]] = {}
        for item in drift:
            by_key.setdefault((item.kind, item.slug), []).append(item.category)
        results = [
            ResourceResult(
                kind=item.resource.kind,
                slug=item.resource.slug,
                revision=item.resource.revision,
                state=(
                    "blocked"
                    if state == "blocked"
                    else "drifted"
                    if by_key.get((item.resource.kind, item.resource.slug))
                    else "applied"
                    if state == "applied"
                    else "in_sync"
                ),
                drift=by_key.get((item.resource.kind, item.resource.slug), []),
                message=(
                    "Active agent turn requires a safe maintenance boundary."
                    if state == "blocked"
                    else None
                ),
            )
            for item in staged
        ]
        desired = {(item.resource.kind, item.resource.slug) for item in staged}
        for key, categories in by_key.items():
            if key not in desired:
                results.append(
                    ResourceResult(
                        kind=key[0],
                        slug=key[1],
                        state="drifted" if state != "applied" else "removed",
                        drift=categories,
                    )
                )
        return ReconcileResult(
            manifest_revision=manifest.revision,
            state=state,
            resources=results,
            maintenance_required=maintenance_required,
        )
