"""The ASDD catalogue on disk: changes, capability specs, and the archive.

This is the whole persistence layer. A change is a directory whose name is its
identity, its state is the `status` field in `proposal.md`, and its history is
the repository's own. Nothing here allocates a UUID, computes a content hash or
consults a chat session, because every one of those was a second identity that
could disagree with the folder and take the run down when it did.

Reads are forgiving and writes are deterministic. A malformed page makes one
change unreadable and says why; a write re-renders the whole page from parsed
values so repeated saves of the same state produce no diff.
"""

from __future__ import annotations

import re
import shutil
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from app.asdd_skills import read_asdd_template
from app.services.asdd_document import (
    AsddDocumentError,
    MarkdownDocument,
    optional_str,
    parse_document,
    render_document,
    scalar_text,
    string_list,
)
from app.services.asdd_lifecycle import (
    APPROVAL_ARTIFACTS,
    ChangeArtifacts,
    status_after_approval,
)
from app.services.asdd_runtime import asdd_catalogue_lock
from app.services.asdd_spec_format import (
    AsddSpecFormatError,
    Spec,
    SpecDelta,
    apply_delta,
    parse_delta,
    parse_spec,
    render_delta,
    render_spec,
    validate_delta,
)

SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
PROPOSAL_FILE = "proposal.md"
DESIGN_FILE = "design.md"
TASKS_FILE = "tasks.md"
SPEC_FILE = "spec.md"
PROJECT_FILE = "project.md"
CHANGES_DIRECTORY = "changes"
SPECS_DIRECTORY = "specs"
ARCHIVE_DIRECTORY = "archive"
EVIDENCE_DIRECTORY = "evidence"

_MAX_ARTIFACT_BYTES = 512 * 1024
_TASK = re.compile(r"^\s*[-*]\s+\[(?P<mark>[ xX])\]\s+(?P<text>.*)$")
_ARCHIVE_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}-(?P<slug>.+)$")

_PROPOSAL_KEYS = ("change", "title", "status", "risk", "capabilities", "created")


class AsddStoreError(ValueError):
    """The catalogue cannot serve a request against what is on disk."""


class AsddChangeNotFound(AsddStoreError):
    """No change directory carries the requested identity."""


class AsddChangeExists(AsddStoreError):
    """A change directory already carries the requested identity."""


def normalize_slug(value: str, *, label: str) -> str:
    """Return a slug usable as a directory name, a URL fragment and a link.

    Constrained here rather than sanitized at write time: a slug the author
    cannot predict is a slug nobody can link to, and the identity of a change is
    the one thing in ASDD that must never be surprising.
    """

    candidate = str(value or "").strip().lower().replace("_", "-").replace(" ", "-")
    candidate = re.sub(r"-{2,}", "-", candidate).strip("-")
    if not candidate or not SLUG.fullmatch(candidate):
        raise AsddStoreError(
            f"{label} must be a lowercase slug of letters, digits and single hyphens"
        )
    if len(candidate) > 80:
        raise AsddStoreError(f"{label} must be 80 characters or fewer")
    return candidate


#: Letters that carry meaning rather than an accent, so stripping combining
#: marks leaves nothing behind. Vietnamese `đ` is the case that matters here.
_TRANSLITERATIONS = str.maketrans({"đ": "d", "Đ": "D", "ß": "ss", "æ": "ae", "ø": "o"})


def slugify(value: str, *, label: str) -> str:
    """Derive a slug from free-form prose.

    The sibling of `normalize_slug`, and deliberately not the same function.
    That one validates a slug the author typed and refuses to guess at anything
    else, which is right for `change_id`. This one is given a *title* — prose,
    in whatever language the author writes — and has to produce a directory
    name from it. Calling the validator instead turned every ordinary title
    into an error: `Add PDF export!!` was rejected for punctuation, and a
    Vietnamese title was rejected outright, which left no way to open a change
    at all for anyone not naming their work in ASCII.
    """

    folded = unicodedata.normalize("NFKD", str(value or "").translate(_TRANSLITERATIONS))
    ascii_only = "".join(
        character
        for character in folded
        if not unicodedata.combining(character) and ord(character) < 128
    )
    candidate = re.sub(r"[^a-z0-9]+", "-", ascii_only.lower()).strip("-")
    if not candidate:
        raise AsddStoreError(
            f"{label} has no letters or digits to build a change id from — "
            "give the change an id of its own"
        )
    return candidate[:80].strip("-")


def normalize_data_directory(value: str | Path) -> Path:
    raw = str(value).strip().replace("\\", "/")
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or ".." in path.parts or str(path) in {"", "."}:
        raise AsddStoreError("ASDD data_directory must be a repository-relative path")
    if path.parts[0] in {".git", ".evoflux"}:
        raise AsddStoreError(
            "ASDD data_directory cannot live inside Git internals or .evoflux"
        )
    return Path(*path.parts)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp() -> str:
    return _utcnow().isoformat(timespec="seconds").replace("+00:00", "Z")


def _read(path: Path) -> str | None:
    try:
        if path.is_symlink() or not path.is_file():
            return None
        if path.stat().st_size > _MAX_ARTIFACT_BYTES:
            raise AsddStoreError(f"{path.name} is larger than 512 KiB")
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise AsddStoreError(f"Cannot read {path.name}: {exc}") from exc


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = text.replace("\r\n", "\n")
    # A no-op write would still touch mtime and, on some editors, re-trigger a
    # watcher; comparing first keeps an idempotent approve genuinely idempotent.
    if path.is_file() and path.read_text(encoding="utf-8") == normalized:
        return
    path.write_text(normalized, encoding="utf-8", newline="\n")


_OPEN_QUESTIONS = re.compile(r"^##\s+Open questions\s*$", re.IGNORECASE)
_SECTION = re.compile(r"^##\s+")
_BULLET = re.compile(r"^\s*[-*]\s+(?P<text>.*\S)\s*$")
#: A bullet that is still the template's own italic prompt, not an answer.
_PLACEHOLDER = re.compile(r"^_.*_$")


def parse_open_questions(body: str) -> list[str]:
    """Return the unanswered questions a design still carries.

    The design template invites an `## Open questions` section, and an agent
    that fills it in has said, in writing, that it does not yet know how to
    build the thing it is asking to have approved. Reading them back is what
    lets the gate refuse — otherwise the section is a place to park doubt on
    the way past the one review the risk tier exists to force.

    The template's own italic prompts are skipped, so an untouched section is
    not mistaken for four unanswered questions.
    """

    bullets: list[str] = []
    inside = False
    for line in body.replace("\r\n", "\n").split("\n"):
        if _OPEN_QUESTIONS.match(line):
            inside = True
            continue
        if inside and _SECTION.match(line):
            break
        if not inside:
            continue
        match = _BULLET.match(line)
        if match is not None:
            bullets.append(match.group("text").strip())
            continue
        # A wrapped bullet. Joining it matters for the placeholder test: the
        # template's own prompt is one italic sentence spread over two lines,
        # and judged a line at a time the first half looks like a real question.
        if bullets and line.strip() and line.startswith((" ", "\t")):
            bullets[-1] = f"{bullets[-1]} {line.strip()}"
    return [text for text in bullets if not _PLACEHOLDER.match(text)]


def _replace_section(body: str, heading: str, text: str) -> str:
    """Replace one `## <heading>` section's contents, leaving the rest alone."""

    lines = body.replace("\r\n", "\n").split("\n")
    opening = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.IGNORECASE)
    start: int | None = None
    for index, line in enumerate(lines):
        if opening.match(line):
            start = index
            break
    if start is None:
        return body
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if _SECTION.match(lines[index]):
            end = index
            break
    return "\n".join(lines[: start + 1] + ["", text, ""] + lines[end:])


def parse_tasks(body: str) -> tuple[int, int]:
    """Return `(total, done)` checklist items in a `tasks.md` body."""

    total = 0
    done = 0
    for line in body.replace("\r\n", "\n").split("\n"):
        match = _TASK.match(line)
        if match is None:
            continue
        total += 1
        if match.group("mark") in {"x", "X"}:
            done += 1
    return total, done


@dataclass(frozen=True, slots=True)
class CapabilityDelta:
    capability: str
    delta: SpecDelta
    body: str
    problems: list[str]


@dataclass(frozen=True, slots=True)
class ChangeRecord:
    """Everything one change folder says about itself."""

    change_id: str
    artifacts: ChangeArtifacts
    proposal_body: str
    design_body: str | None
    tasks_body: str | None
    deltas: list[CapabilityDelta]
    evidence: list[MarkdownDocument]
    created: str | None
    path: Path


@dataclass(frozen=True, slots=True)
class AsddCatalogue:
    """One repository's ASDD tree, rooted at its checkout."""

    root: Path
    data_directory: Path

    @classmethod
    def create(cls, root: str | Path, data_directory: str | Path) -> AsddCatalogue:
        return cls(
            root=Path(root).expanduser().resolve(),
            data_directory=normalize_data_directory(data_directory),
        )

    # --- paths -----------------------------------------------------------

    @property
    def base_path(self) -> Path:
        return self.root / self.data_directory

    @property
    def specs_path(self) -> Path:
        return self.base_path / SPECS_DIRECTORY

    @property
    def changes_path(self) -> Path:
        return self.base_path / CHANGES_DIRECTORY

    @property
    def archive_path(self) -> Path:
        return self.changes_path / ARCHIVE_DIRECTORY

    @property
    def project_path(self) -> Path:
        return self.base_path / PROJECT_FILE

    def change_path(self, change_id: str) -> Path:
        return self.changes_path / normalize_slug(change_id, label="change id")

    def spec_path(self, capability: str) -> Path:
        return (
            self.specs_path / normalize_slug(capability, label="capability") / SPEC_FILE
        )

    def relative(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()

    # --- capability specs ------------------------------------------------

    def list_capabilities(self) -> list[str]:
        if not self.specs_path.is_dir():
            return []
        return sorted(
            entry.name
            for entry in self.specs_path.iterdir()
            if entry.is_dir() and (entry / SPEC_FILE).is_file()
        )

    def read_spec(self, capability: str) -> tuple[MarkdownDocument, Spec] | None:
        path = self.spec_path(capability)
        text = _read(path)
        if text is None:
            return None
        document = parse_document(text)
        return document, parse_spec(document.body, source=self.relative(path))

    def write_spec(
        self, capability: str, spec: Spec, *, front_matter: dict[str, Any] | None = None
    ) -> Path:
        slug = normalize_slug(capability, label="capability")
        path = self.spec_path(slug)
        header = dict(front_matter or {})
        header.setdefault("capability", slug)
        header["updated"] = _timestamp()
        with asdd_catalogue_lock(self.root):
            _write(path, render_document(header, render_spec(spec)))
        return path

    # --- changes ---------------------------------------------------------

    def list_change_ids(self) -> list[str]:
        if not self.changes_path.is_dir():
            return []
        return sorted(
            entry.name
            for entry in self.changes_path.iterdir()
            if entry.is_dir()
            and entry.name != ARCHIVE_DIRECTORY
            and (entry / PROPOSAL_FILE).is_file()
        )

    def list_archived(self) -> list[str]:
        if not self.archive_path.is_dir():
            return []
        return sorted(
            (entry.name for entry in self.archive_path.iterdir() if entry.is_dir()),
            reverse=True,
        )

    def archived_change_ids(self) -> set[str]:
        """Return the slugs behind the dated archive names.

        Matched by stripping the exact `YYYY-MM-DD-` prefix rather than by
        suffix: `endswith("-auth")` would refuse a new change called `auth`
        because `user-auth` was archived once.
        """

        return {
            match.group("slug")
            for match in (_ARCHIVE_NAME.match(name) for name in self.list_archived())
            if match is not None
        }

    def create_change(
        self,
        *,
        change_id: str,
        title: str,
        risk: str | None = None,
        capabilities: list[str] | None = None,
        body: str | None = None,
    ) -> ChangeRecord:
        slug = normalize_slug(change_id, label="change id")
        path = self.change_path(slug)
        with asdd_catalogue_lock(self.root):
            if path.exists():
                raise AsddChangeExists(f"Change '{slug}' already exists")
            if slug in self.archived_change_ids():
                raise AsddChangeExists(f"Change '{slug}' is already archived")
            header: dict[str, Any] = {
                "change": slug,
                "title": title.strip() or slug,
                "status": "drafting",
            }
            # Omitted rather than defaulted when nobody has chosen. The tier
            # decides whether this change owes a design and an independent
            # review, and writing `standard` on the way in would answer that
            # question silently, before anyone had looked at the work.
            if risk is not None:
                header["risk"] = risk
            header.update(
                {
                    "capabilities": [
                        normalize_slug(item, label="capability")
                        for item in (capabilities or [])
                    ],
                    "created": _timestamp(),
                    "approvals": {
                        artifact: None for artifact in APPROVAL_ARTIFACTS
                    },
                }
            )
            _write(
                path / PROPOSAL_FILE,
                render_document(header, body or read_asdd_template(PROPOSAL_FILE)),
            )
        return self.read_change(slug)

    def seed_request(self, change_id: str, *, problem: str, outcome: str) -> None:
        """Put the requester's own words into the proposal's first two sections.

        They go in the file rather than into a request field on the API, because
        the file is what the propose phase reads. An `intent` column the server
        accepted and stored beside the folder would be a second place the change
        is described, and the first one to go stale.

        Written as prose under `## Why` and `## What Changes`, replacing the
        template's italic prompts — so the phase that runs next is editing the
        user's sentences rather than starting from nothing.
        """

        if not problem.strip() and not outcome.strip():
            return
        slug = normalize_slug(change_id, label="change id")
        path = self.change_path(slug) / PROPOSAL_FILE
        with asdd_catalogue_lock(self.root):
            text = _read(path)
            if text is None:
                raise AsddChangeNotFound(f"No change '{slug}' in the catalogue")
            document = parse_document(text)
            body = document.body
            if problem.strip():
                body = _replace_section(body, "Why", problem.strip())
            if outcome.strip():
                body = _replace_section(body, "What Changes", outcome.strip())
            _write(path, render_document(document.front_matter, body))

    def read_change(self, change_id: str) -> ChangeRecord:
        slug = normalize_slug(change_id, label="change id")
        path = self.change_path(slug)
        proposal_text = _read(path / PROPOSAL_FILE)
        if proposal_text is None:
            raise AsddChangeNotFound(f"No change '{slug}' in the catalogue")
        source = self.relative(path / PROPOSAL_FILE)
        try:
            proposal = parse_document(proposal_text)
        except AsddDocumentError as exc:
            raise AsddStoreError(f"{source}: {exc}") from exc

        declared = optional_str(proposal, "change")
        if declared and declared != slug:
            raise AsddStoreError(
                f"{source}: declares `change: {declared}` but lives in '{slug}/'"
            )

        design_text = _read(path / DESIGN_FILE)
        design_body = (
            parse_document(design_text).body if design_text is not None else None
        )
        tasks_text = _read(path / TASKS_FILE)
        tasks_body = parse_document(tasks_text).body if tasks_text is not None else None
        total, done = parse_tasks(tasks_body or "")

        deltas = self._read_deltas(path)
        evidence = self._read_evidence(path)

        artifacts = ChangeArtifacts(
            change_id=slug,
            title=optional_str(proposal, "title") or slug,
            status=optional_str(proposal, "status") or "drafting",
            risk=optional_str(proposal, "risk") or "standard",
            risk_declared=optional_str(proposal, "risk") is not None,
            capabilities=string_list(proposal, "capabilities"),
            approvals=_approvals(proposal, "approvals"),
            auto_approvals=_approvals(proposal, "auto_approvals"),
            autopilot=_flag(proposal, "autopilot"),
            hold=_hold(proposal),
            has_proposal=True,
            has_design=design_text is not None,
            design_open_questions=parse_open_questions(design_body or ""),
            has_tasks=tasks_text is not None,
            delta_capabilities=[item.capability for item in deltas],
            delta_requirements=_delta_requirements(deltas),
            evidence_results=_evidence_results(evidence),
            spec_problems=[problem for item in deltas for problem in item.problems],
            tasks_total=total,
            tasks_done=done,
            evidence_ids=[
                scalar_text(document.get("id")) or "" for document in evidence
            ],
            review_recorded=any(
                (scalar_text(document.get("kind")) or "").lower() == "review"
                and (scalar_text(document.get("result")) or "").lower() == "passed"
                for document in evidence
            ),
        )
        return ChangeRecord(
            change_id=slug,
            artifacts=artifacts,
            proposal_body=proposal.body,
            design_body=parse_document(design_text).body
            if design_text is not None
            else None,
            tasks_body=tasks_body,
            deltas=deltas,
            evidence=evidence,
            created=optional_str(proposal, "created"),
            path=path,
        )

    def _read_deltas(self, change_path: Path) -> list[CapabilityDelta]:
        specs_root = change_path / SPECS_DIRECTORY
        if not specs_root.is_dir():
            return []
        deltas: list[CapabilityDelta] = []
        for entry in sorted(specs_root.iterdir(), key=lambda item: item.name):
            if not entry.is_dir():
                continue
            text = _read(entry / SPEC_FILE)
            if text is None:
                continue
            source = self.relative(entry / SPEC_FILE)
            # One unreadable delta reports itself as a problem on that
            # capability rather than making the whole change unreadable: the
            # user needs to see the change in order to go and fix the page.
            try:
                document = parse_document(text)
                delta = parse_delta(document.body, source=source)
                problems = validate_delta(delta, source=source)
            except (AsddDocumentError, AsddSpecFormatError) as exc:
                document = MarkdownDocument(front_matter={}, body=text)
                delta = SpecDelta()
                problems = [f"{source}: {exc}"]
            deltas.append(
                CapabilityDelta(
                    capability=entry.name,
                    delta=delta,
                    body=document.body,
                    problems=problems,
                )
            )
        return deltas

    def _read_evidence(self, change_path: Path) -> list[MarkdownDocument]:
        evidence_root = change_path / EVIDENCE_DIRECTORY
        if not evidence_root.is_dir():
            return []
        documents: list[MarkdownDocument] = []
        for entry in sorted(evidence_root.glob("*.md"), key=lambda item: item.name):
            text = _read(entry)
            if text is None:
                continue
            try:
                document = parse_document(text)
            except AsddDocumentError:
                # Evidence is an append-only log. A page nobody can parse is
                # skipped rather than allowed to hide every other result.
                continue
            if not document.get("id"):
                document = MarkdownDocument(
                    front_matter={**document.front_matter, "id": entry.stem},
                    body=document.body,
                )
            documents.append(document)
        return documents

    # --- writes ----------------------------------------------------------

    def write_proposal(
        self,
        change_id: str,
        *,
        body: str | None = None,
        title: str | None = None,
        risk: str | None = None,
        capabilities: list[str] | None = None,
        status: str | None = None,
    ) -> ChangeRecord:
        """Rewrite `proposal.md`, preserving fields the caller did not supply."""

        slug = normalize_slug(change_id, label="change id")
        path = self.change_path(slug) / PROPOSAL_FILE
        with asdd_catalogue_lock(self.root):
            text = _read(path)
            if text is None:
                raise AsddChangeNotFound(f"No change '{slug}' in the catalogue")
            document = parse_document(text)
            header = dict(document.front_matter)
            header["change"] = slug
            if title is not None:
                header["title"] = title.strip()
            if risk is not None:
                header["risk"] = risk
            if capabilities is not None:
                header["capabilities"] = [
                    normalize_slug(item, label="capability") for item in capabilities
                ]
            if status is not None:
                header["status"] = status
            header.setdefault("approvals", {})
            _write(
                path,
                render_document(
                    _ordered_proposal_header(header),
                    body if body is not None else document.body,
                ),
            )
        return self.read_change(slug)

    def write_artifact(self, change_id: str, artifact: str, body: str) -> ChangeRecord:
        """Write `design.md` or `tasks.md`."""

        filename = {"design": DESIGN_FILE, "tasks": TASKS_FILE}.get(artifact)
        if filename is None:
            raise AsddStoreError(f"Unknown ASDD artifact: {artifact}")
        slug = normalize_slug(change_id, label="change id")
        change_path = self.change_path(slug)
        with asdd_catalogue_lock(self.root):
            if not (change_path / PROPOSAL_FILE).is_file():
                raise AsddChangeNotFound(f"No change '{slug}' in the catalogue")
            _write(change_path / filename, render_document({}, body))
        return self.read_change(slug)

    def write_delta(
        self, change_id: str, capability: str, delta: SpecDelta
    ) -> ChangeRecord:
        slug = normalize_slug(change_id, label="change id")
        capability_slug = normalize_slug(capability, label="capability")
        change_path = self.change_path(slug)
        with asdd_catalogue_lock(self.root):
            if not (change_path / PROPOSAL_FILE).is_file():
                raise AsddChangeNotFound(f"No change '{slug}' in the catalogue")
            _write(
                change_path / SPECS_DIRECTORY / capability_slug / SPEC_FILE,
                render_document({"capability": capability_slug}, render_delta(delta)),
            )
        return self.read_change(slug)

    def record_evidence(
        self,
        change_id: str,
        *,
        evidence_id: str,
        kind: str,
        result: str,
        summary: str,
        requirement: str | None = None,
        body: str = "",
    ) -> ChangeRecord:
        """Append one execution-log page — the ADD half of the method.

        Evidence is a file rather than a table row so a reviewer reads it in the
        same pull request as the code it justifies, and so a change that is
        copied or branched carries its proof with it.
        """

        slug = normalize_slug(change_id, label="change id")
        evidence_slug = normalize_slug(evidence_id, label="evidence id")
        change_path = self.change_path(slug)
        with asdd_catalogue_lock(self.root):
            if not (change_path / PROPOSAL_FILE).is_file():
                raise AsddChangeNotFound(f"No change '{slug}' in the catalogue")
            header = {
                "id": evidence_slug,
                "kind": kind,
                "result": result,
                "requirement": requirement,
                "recorded": _timestamp(),
            }
            _write(
                change_path / EVIDENCE_DIRECTORY / f"{evidence_slug}.md",
                render_document(header, f"{summary.strip()}\n\n{body.strip()}".strip()),
            )
        return self.read_change(slug)

    def set_status(self, change_id: str, status: str) -> ChangeRecord:
        return self.write_proposal(change_id, status=status)

    def approve(
        self, change_id: str, artifact: str, *, note: str | None = None
    ) -> ChangeRecord:
        """Record a human approval and advance the change to the next phase."""

        if artifact not in APPROVAL_ARTIFACTS:
            raise AsddStoreError(f"Unknown ASDD approval artifact: {artifact}")
        slug = normalize_slug(change_id, label="change id")
        path = self.change_path(slug) / PROPOSAL_FILE
        with asdd_catalogue_lock(self.root):
            record = self.read_change(slug)
            text = _read(path)
            if text is None:
                raise AsddChangeNotFound(f"No change '{slug}' in the catalogue")
            document = parse_document(text)
            header = dict(document.front_matter)
            approvals = dict(_approvals(document, "approvals"))
            approvals[artifact] = _timestamp()
            header["approvals"] = approvals
            # A person looked: whatever the agent was waiting on is settled.
            header.pop("hold", None)
            if note:
                notes = dict(header.get("approval_notes") or {})
                notes[artifact] = note.strip()
                header["approval_notes"] = notes
            header["status"] = status_after_approval(record.artifacts, artifact)
            _write(
                path, render_document(_ordered_proposal_header(header), document.body)
            )
        return self.read_change(slug)

    def set_autopilot(self, change_id: str, *, enabled: bool) -> ChangeRecord:
        """Turn autopilot on or off for one change.

        Written into `proposal.md` like everything else, so the setting travels
        with the change in `git diff` and a reader can see it without the panel.
        Turning it off also clears any hold, because a hold only means "waiting
        for a person before autopilot continues" and there is nothing left to
        continue.
        """

        slug = normalize_slug(change_id, label="change id")
        path = self.change_path(slug) / PROPOSAL_FILE
        with asdd_catalogue_lock(self.root):
            text = _read(path)
            if text is None:
                raise AsddChangeNotFound(f"No change '{slug}' in the catalogue")
            document = parse_document(text)
            header = dict(document.front_matter)
            header["autopilot"] = enabled
            if not enabled:
                header.pop("hold", None)
            _write(
                path, render_document(_ordered_proposal_header(header), document.body)
            )
        return self.read_change(slug)

    # --- archive ---------------------------------------------------------

    def archive_entry_name(self, change_id: str, *, today: date | None = None) -> str:
        """Return the dated folder name an archive would produce.

        Shared with the caller that reports the name back, so the two cannot
        pick different clocks. `date.today()` is local and `_utcnow().date()` is
        not: east of UTC they disagree for the first hours of every day, and the
        reported path would name a folder that does not exist.
        """

        stamp = (today or _utcnow().date()).isoformat()
        return f"{stamp}-{normalize_slug(change_id, label='change id')}"

    def archive_change(self, change_id: str, *, today: date | None = None) -> list[str]:
        """Fold a change's deltas into the catalogue and retire its folder.

        Returns the capabilities whose canonical spec changed. A delta for a
        capability that has no spec yet creates one — that case is the common
        one for a new capability, and treating it as "nothing to sync" is how a
        catalogue silently loses the first spec it was ever given.
        """

        slug = normalize_slug(change_id, label="change id")
        with asdd_catalogue_lock(self.root):
            record = self.read_change(slug)
            if not record.deltas:
                raise AsddStoreError(
                    f"Change '{slug}' has no capability delta to archive"
                )
            destination = self.archive_path / self.archive_entry_name(slug, today=today)
            # Everything that can refuse the archive is checked before the first
            # spec is written. A fold that succeeds and then cannot retire the
            # folder would leave the change open with its deltas already merged,
            # and the next attempt would fail on requirements the catalogue now
            # contains.
            if destination.exists():
                raise AsddStoreError(
                    f"Archive entry '{destination.name}' already exists"
                )
            for item in record.deltas:
                if item.problems:
                    raise AsddStoreError(
                        f"Change '{slug}' cannot be archived: "
                        + "; ".join(item.problems)
                    )
            updated: list[str] = []
            for item in record.deltas:
                existing = self.read_spec(item.capability)
                if existing is None:
                    header: dict[str, Any] = {}
                    current = Spec(purpose="", requirements=[])
                else:
                    header = dict(existing[0].front_matter)
                    current = existing[1]
                merged = apply_delta(
                    current,
                    item.delta,
                    source=f"{slug}/specs/{item.capability}/spec.md",
                )
                if not merged.purpose:
                    merged = Spec(
                        purpose=(f"Behavior contracted for `{item.capability}`."),
                        requirements=merged.requirements,
                    )
                self.write_spec(item.capability, merged, front_matter=header)
                updated.append(item.capability)

            destination.parent.mkdir(parents=True, exist_ok=True)
            self.set_status(slug, "archived")
            shutil.move(str(record.path), str(destination))
        return updated

    def delete_change(self, change_id: str) -> None:
        slug = normalize_slug(change_id, label="change id")
        path = self.change_path(slug)
        with asdd_catalogue_lock(self.root):
            if not path.is_dir():
                raise AsddChangeNotFound(f"No change '{slug}' in the catalogue")
            shutil.rmtree(path)


def _delta_requirements(deltas: list[CapabilityDelta]) -> list[str]:
    """Every requirement the change adds or modifies, deduplicated in order.

    Removed requirements are left out: there is nothing left to exercise once
    the fold takes them out of the capability spec.
    """

    names: list[str] = []
    for item in deltas:
        for requirement in (*item.delta.added, *item.delta.modified):
            if requirement.name not in names:
                names.append(requirement.name)
    return names


def _evidence_results(evidence: list[MarkdownDocument]) -> dict[str, list[str]]:
    """Requirement name -> the results of the pages citing it.

    A page with no `requirement` covers the change as a whole and is left out
    here, because it cannot tell you whether any one requirement was exercised.
    """

    results: dict[str, list[str]] = {}
    for document in evidence:
        requirement = scalar_text(document.get("requirement"))
        if not requirement:
            continue
        outcome = (scalar_text(document.get("result")) or "inconclusive").lower()
        results.setdefault(requirement, []).append(outcome)
    return results


def _approvals(document: MarkdownDocument, key: str) -> dict[str, str | None]:
    raw = document.front_matter.get(key)
    values: dict[str, str | None] = {artifact: None for artifact in APPROVAL_ARTIFACTS}
    if isinstance(raw, dict):
        for artifact in APPROVAL_ARTIFACTS:
            values[artifact] = scalar_text(raw.get(artifact))
    return values


def _flag(document: MarkdownDocument, key: str) -> bool:
    """Read a boolean the author may have written as a word or a flag."""

    value = document.front_matter.get(key)
    if isinstance(value, bool):
        return value
    return (scalar_text(value) or "").lower() in {"true", "yes", "on", "1"}


def _hold(document: MarkdownDocument) -> dict[str, str] | None:
    """Read the gate an agent decided a person has to look at.

    Tolerant of a bare string, because someone stopping a run by hand is more
    likely to write `hold: needs security review` than to nest a mapping.
    """

    raw = document.front_matter.get("hold")
    if isinstance(raw, dict):
        fields = {
            name: text
            for name in ("gate", "reason", "raised")
            if (text := scalar_text(raw.get(name)))
        }
        return fields or None
    text = scalar_text(raw)
    return {"reason": text} if text else None


def _ordered_proposal_header(header: dict[str, Any]) -> dict[str, Any]:
    """Return proposal front matter in its declared order.

    Key order is part of the artifact contract: a save that reshuffles it turns
    every write into a diff and buries the state change a reviewer came to see.
    """

    ordered: dict[str, Any] = {}
    for key in _PROPOSAL_KEYS:
        if key in header:
            ordered[key] = header[key]
    # Written only once someone has an opinion about it. Emitting
    # `autopilot: false` into every proposal would put a line in the diff of
    # every change that has never heard of the feature.
    if "autopilot" in header:
        ordered["autopilot"] = bool(header["autopilot"])
    ordered["approvals"] = {
        artifact: (header.get("approvals") or {}).get(artifact)
        for artifact in APPROVAL_ARTIFACTS
    }
    # Only written once autopilot has cleared something, so an ordinary change
    # keeps the front matter it has always had.
    if header.get("auto_approvals"):
        ordered["auto_approvals"] = {
            artifact: (header.get("auto_approvals") or {}).get(artifact)
            for artifact in APPROVAL_ARTIFACTS
        }
    if header.get("hold"):
        ordered["hold"] = header["hold"]
    for key, value in header.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


__all__ = [
    "ARCHIVE_DIRECTORY",
    "AsddCatalogue",
    "AsddChangeExists",
    "AsddChangeNotFound",
    "AsddStoreError",
    "CHANGES_DIRECTORY",
    "CapabilityDelta",
    "ChangeRecord",
    "DESIGN_FILE",
    "EVIDENCE_DIRECTORY",
    "PROJECT_FILE",
    "PROPOSAL_FILE",
    "SPECS_DIRECTORY",
    "SPEC_FILE",
    "TASKS_FILE",
    "normalize_data_directory",
    "normalize_slug",
    "parse_tasks",
    "slugify",
]
