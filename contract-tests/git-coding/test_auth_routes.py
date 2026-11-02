"""Every route of the unit needs the access key, before any validation."""

from __future__ import annotations

import httpx
import pytest

from gc_helpers import UNAUTHORIZED_BODY

WS = "C:/does-not-matter"
ID = "11111111-1111-1111-1111-111111111111"
T = "/api/team"
G = f"{T}/workspace/git"

#: (method, path, query, JSON body): valid values, so a 401 proves authentication
#: runs before routing-level validation, the database and git.
ROUTES: list[tuple[str, str, dict[str, str], object]] = [
    ("GET", f"{G}/repository", {"workspace": WS}, None),
    ("POST", f"{G}/repository/init", {}, {"workspace": WS}),
    ("POST", f"{G}/repository/clone", {}, {"parent": WS, "url": "https://example.test/a.git"}),
    ("POST", f"{G}/repository/identity", {}, {"workspace": WS, "name": "n", "email": "e@x"}),
    ("GET", f"{G}/changes", {"workspace": WS}, None),
    ("POST", f"{G}/stage", {}, {"workspace": WS}),
    ("POST", f"{G}/stage-all", {}, {"workspace": WS}),
    ("POST", f"{G}/unstage", {}, {"workspace": WS}),
    ("POST", f"{G}/unstage-all", {}, {"workspace": WS}),
    ("POST", f"{G}/discard", {}, {"workspace": WS}),
    ("POST", f"{G}/commit", {}, {"workspace": WS, "message": "m"}),
    ("GET", f"{G}/branches", {"workspace": WS}, None),
    ("POST", f"{G}/branches", {}, {"workspace": WS, "name": "b"}),
    ("GET", f"{G}/diff-view", {"workspace": WS, "path": "a"}, None),
    ("POST", f"{G}/branches/checkout", {}, {"workspace": WS, "name": "b"}),
    ("DELETE", f"{G}/branches", {}, {"workspace": WS, "name": "b"}),
    ("GET", f"{G}/tags", {"workspace": WS}, None),
    ("POST", f"{G}/tags", {}, {"workspace": WS, "name": "t"}),
    ("DELETE", f"{G}/tags", {}, {"workspace": WS, "name": "t"}),
    ("POST", f"{G}/tags/push", {}, {"workspace": WS}),
    ("POST", f"{G}/merge", {}, {"workspace": WS, "branch": "b"}),
    ("POST", f"{G}/fetch", {}, {"workspace": WS}),
    ("POST", f"{G}/pull", {}, {"workspace": WS}),
    ("POST", f"{G}/push", {}, {"workspace": WS}),
    ("GET", f"{G}/jobs", {"workspace": WS}, None),
    ("GET", f"{G}/remotes", {"workspace": WS}, None),
    ("POST", f"{G}/remotes", {}, {"workspace": WS, "name": "o", "url": "https://example.test/a.git"}),
    ("PUT", f"{G}/remotes", {}, {"workspace": WS, "name": "o", "url": "https://example.test/a.git"}),
    ("DELETE", f"{G}/remotes", {}, {"workspace": WS, "name": "o"}),
    ("GET", f"{G}/log", {"workspace": WS}, None),
    ("GET", f"{G}/log/abcdef12/files", {"workspace": WS}, None),
    ("GET", f"{G}/stash", {"workspace": WS}, None),
    ("POST", f"{G}/stash", {}, {"workspace": WS}),
    ("POST", f"{G}/stash/apply", {}, {"workspace": WS}),
    ("POST", f"{G}/stash/pop", {}, {"workspace": WS}),
    ("DELETE", f"{G}/stash", {}, {"workspace": WS}),
    ("POST", f"{G}/rebase", {}, {"workspace": WS, "onto": "b"}),
    ("POST", f"{G}/cherry-pick", {}, {"workspace": WS, "shas": ["abcdef12"]}),
    ("POST", f"{G}/revert", {}, {"workspace": WS, "sha": "abcdef12"}),
    ("GET", f"{G}/conflicts", {"workspace": WS}, None),
    ("POST", f"{G}/continue", {}, {"workspace": WS}),
    ("POST", f"{G}/abort", {}, {"workspace": WS}),
    ("POST", f"{G}/ai", {}, {"workspace": WS, "kind": "commit_message"}),
    ("GET", f"{T}/workspace/worktrees", {"source_workspace": WS}, None),
    ("POST", f"{T}/workspace/worktrees", {}, {"source_workspace": WS}),
    ("DELETE", f"{T}/workspace/worktrees", {}, {"source_workspace": WS, "directory": WS}),
    ("GET", f"{T}/projects", {}, None),
    ("POST", f"{T}/projects", {}, {"name": "p"}),
    ("GET", f"{T}/projects/{ID}", {}, None),
    ("PUT", f"{T}/projects/{ID}", {}, {"name": "p"}),
    ("DELETE", f"{T}/projects/{ID}", {}, None),
    ("POST", f"{T}/projects/{ID}/workspaces", {}, {"workspace_path": WS}),
    ("PUT", f"{T}/projects/{ID}/workspaces/{ID}", {}, {}),
    ("DELETE", f"{T}/projects/{ID}/workspaces/{ID}", {}, None),
    ("POST", f"{T}/workspace/change-sets", {}, {"workspace": WS}),
    ("GET", f"{T}/workspace/change-sets/x", {"workspace": WS}, None),
    ("GET", f"{T}/workspace/change-sets/x/files/a.txt", {"workspace": WS}, None),
    ("POST", f"{T}/workspace/change-sets/x/apply", {}, {"workspace": WS}),
    ("POST", f"{T}/workspace/change-sets/x/reject", {}, {"workspace": WS}),
    ("GET", f"{T}/workspace/problems", {"workspace": WS}, None),
    ("POST", f"{T}/workspace/problems/x/dismiss", {}, {"workspace": WS}),
    ("POST", f"{T}/workspace/problems/x/suppress", {}, {"workspace": WS}),
    ("POST", f"{T}/workspace/problems/x/restore", {}, {"workspace": WS}),
    ("POST", f"{T}/workspace/editor/context", {}, {"workspace": WS}),
    ("POST", f"{T}/workspace/editor/action", {}, {"workspace": WS}),
    ("GET", f"{T}/reviews/connections", {}, None),
    ("POST", f"{T}/reviews/connections", {}, {"provider": "github"}),
    ("PUT", f"{T}/reviews/connections/{ID}", {}, {}),
    ("DELETE", f"{T}/reviews/connections/{ID}", {}, None),
    ("POST", f"{T}/reviews/connections/test", {}, {"provider": "github"}),
    ("GET", f"{T}/reviews", {}, None),
    ("GET", f"{T}/reviews/{ID}/media", {"url": "https://example.test/x.png"}, None),
    ("GET", f"{T}/reviews/{ID}/1", {}, None),
    ("POST", f"{T}/reviews/{ID}", {}, {}),
    ("POST", f"{T}/reviews/{ID}/1/actions", {}, {}),
]


@pytest.mark.parametrize(
    ("method", "path", "query", "body"),
    ROUTES,
    ids=[f"{m} {p.removeprefix(T)}" for m, p, _, _ in ROUTES],
)
def test_route_requires_the_access_key(backend, method, path, query, body) -> None:
    with httpx.Client(base_url=backend.base_url, timeout=30.0) as anonymous:
        response = anonymous.request(method, path, params=query, json=body)
        assert response.status_code == 401
        assert response.json() == UNAUTHORIZED_BODY
    with httpx.Client(
        base_url=backend.base_url,
        headers={"Authorization": "Bearer wrong"},
        timeout=30.0,
    ) as wrong:
        response = wrong.request(method, path, params=query, json=body)
        assert response.status_code == 401
        assert response.json() == UNAUTHORIZED_BODY
