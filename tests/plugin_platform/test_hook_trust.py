from __future__ import annotations

from pathlib import Path

from app.plugin_platform.hook_trust_store import HookTrustGrant, HookTrustStore


def _grant(**overrides: str) -> HookTrustGrant:
    values = {
        "owner_type": "plugin",
        "owner_id": "installation-123",
        "hook_id": "bootstrap",
        "digest": "a" * 64,
        "isolation_profile": "deny-network-v1",
    }
    return HookTrustGrant(**(values | overrides))


def test_hook_trust_is_bound_to_digest_and_isolation_profile(tmp_path: Path) -> None:
    store = HookTrustStore(tmp_path / "hook-trust.json")
    store.approve(_grant())

    assert store.is_trusted(
        owner_type="plugin",
        owner_id="installation-123",
        hook_id="bootstrap",
        digest="a" * 64,
        isolation_profile="deny-network-v1",
    )
    assert not store.is_trusted(
        owner_type="plugin",
        owner_id="installation-123",
        hook_id="bootstrap",
        digest="b" * 64,
        isolation_profile="deny-network-v1",
    )
    assert not store.is_trusted(
        owner_type="plugin",
        owner_id="installation-123",
        hook_id="bootstrap",
        digest="a" * 64,
        isolation_profile="deny-network-v2",
    )


def test_revoking_hook_approval_removes_all_prior_digests(tmp_path: Path) -> None:
    store = HookTrustStore(tmp_path / "hook-trust.json")
    store.approve(_grant())
    store.approve(_grant(digest="b" * 64))

    store.revoke(owner_type="plugin", owner_id="installation-123", hook_id="bootstrap")

    assert store.grants() == ()
    assert store.path.exists()


def test_corrupt_trust_file_never_authorizes_a_hook(tmp_path: Path) -> None:
    path = tmp_path / "hook-trust.json"
    path.write_text("{broken", encoding="utf-8")
    store = HookTrustStore(path)

    assert store.grants() == ()
    assert not store.is_trusted(
        owner_type="plugin",
        owner_id="installation-123",
        hook_id="bootstrap",
        digest="a" * 64,
        isolation_profile="deny-network-v1",
    )
