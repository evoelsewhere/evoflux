"""Secrets: what reaches ``<config>/.env``, what stays in ``mcp.json``, what the API echoes.

Several tests pin behaviour that looks like a bug (see ``NOTES.md``, findings
S1 to S7); they are marked ``finding`` in their docstrings.
"""

from __future__ import annotations

import os
import stat

import pytest

from mcp_helpers import create, fresh, lf, read_json, stdio_body

MASK = "********"


def env_text(config_dir) -> str:
    return lf((config_dir / ".env").read_bytes()).decode("utf-8")


def child_env(dump) -> dict[str, str]:
    return read_json(dump)["env"]


def test_literal_env_values_move_to_dot_env_and_become_refs(
    client, config_dir, mcp_json, tmp_path
) -> None:
    dump = tmp_path / "dump.json"
    response = create(
        client,
        "alpha",
        stdio_body(dump=dump, env={"API_TOKEN": "s3cret", "REF": "${OTHER}", "EMPTY": ""}),
    )
    assert response.status_code == 201
    assert response.json()["config"]["env"] == {
        "API_TOKEN": "${API_TOKEN}",
        "REF": "${OTHER}",
        "EMPTY": "",
    }
    assert read_json(mcp_json)["servers"]["alpha"]["env"] == {
        "API_TOKEN": "${API_TOKEN}",
        "REF": "${OTHER}",
        "EMPTY": "",
    }
    assert env_text(config_dir) == 'API_TOKEN="s3cret"\n'
    env = child_env(dump)
    # The child sees the resolved literal; an unresolvable ref stays as written.
    assert env["API_TOKEN"] == "s3cret"
    assert env["REF"] == "${OTHER}"
    assert env["EMPTY"] == ""


def test_a_dollar_name_without_braces_is_treated_as_a_literal_secret(
    client, config_dir, mcp_json
) -> None:
    create(client, "alpha", stdio_body(env={"K": "$HOME"}))
    assert read_json(mcp_json)["servers"]["alpha"]["env"] == {"K": "${K}"}
    assert env_text(config_dir) == 'K="$HOME"\n'


def test_a_stored_ref_is_resolved_from_dot_env_at_launch(
    client, config_dir, tmp_path
) -> None:
    create(client, "first", stdio_body(env={"SHARED": "from-env-file"}))
    dump = tmp_path / "dump.json"
    create(client, "second", stdio_body(dump=dump, env={"B": "${SHARED}"}))
    assert env_text(config_dir) == 'SHARED="from-env-file"\n'
    assert child_env(dump)["B"] == "from-env-file"


def test_refs_are_only_expanded_in_env_values_not_in_args_command_or_cwd(
    client, tmp_path
) -> None:
    create(client, "first", stdio_body(env={"SHARED": "x"}))
    dump = tmp_path / "dump.json"
    work = tmp_path / "work"
    work.mkdir()
    response = create(client, "second", stdio_body("${SHARED}", dump=dump, cwd=str(work)))
    assert response.status_code == 201
    assert "${SHARED}" in read_json(dump)["argv"]


def test_values_are_quoted_with_backslash_and_double_quote_escapes(
    client, config_dir, tmp_path
) -> None:
    dump = tmp_path / "dump.json"
    create(client, "alpha", stdio_body(dump=dump, env={"Q": 'a"b\\c', "NL": "l1\nl2"}))
    assert env_text(config_dir) == 'Q="a\\"b\\\\c"\nNL="l1\nl2"\n'
    env = child_env(dump)
    assert env["Q"] == 'a"b\\c'
    assert env["NL"] == "l1\nl2"


def test_existing_dot_env_lines_are_kept_and_the_key_is_updated_in_place(
    client, config_dir
) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / ".env").write_bytes(
        b'# my secrets\nFIRST=1\nTOKEN="old"\n  # indented comment = still a comment\nLAST=2'
    )
    create(client, "alpha", stdio_body(env={"TOKEN": "new", "ADDED": "z"}))
    assert env_text(config_dir) == (
        '# my secrets\nFIRST=1\nTOKEN="new"\n  # indented comment = still a comment\n'
        'LAST=2\nADDED="z"\n'
    )


def test_update_rewrites_literals_and_keeps_refs(client, config_dir, mcp_json) -> None:
    create(client, "alpha", stdio_body(env={"K": "one"}))
    response = client.put(
        "/api/mcp/servers/alpha",
        json={"server": stdio_body(env={"K": "${K}", "N": "two"})},
    )
    assert response.status_code == 200
    assert read_json(mcp_json)["servers"]["alpha"]["env"] == {"K": "${K}", "N": "${N}"}
    assert env_text(config_dir) == 'K="one"\nN="two"\n'


def test_a_literal_in_an_update_overwrites_the_stored_secret(client, config_dir) -> None:
    create(client, "alpha", stdio_body(env={"K": "one"}))
    client.put("/api/mcp/servers/alpha", json={"server": stdio_body(env={"K": "two"})})
    assert env_text(config_dir) == 'K="two"\n'


def test_delete_leaves_the_secret_in_dot_env(client, config_dir) -> None:
    """Finding S5: removing a server never removes the secrets it wrote."""
    create(client, "alpha", stdio_body(env={"K": "one"}))
    client.delete("/api/mcp/servers/alpha")
    assert env_text(config_dir) == 'K="one"\n'


def test_removing_an_env_key_in_an_update_leaves_its_secret(client, config_dir) -> None:
    create(client, "alpha", stdio_body(env={"K": "one"}))
    client.put("/api/mcp/servers/alpha", json={"server": stdio_body()})
    assert env_text(config_dir) == 'K="one"\n'


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes do not exist on Windows")
def test_dot_env_is_written_with_mode_0600(client, config_dir) -> None:
    create(client, "alpha", stdio_body(env={"K": "one"}))
    assert stat.S_IMODE((config_dir / ".env").stat().st_mode) == 0o600


# ── Findings: env names are not validated ───────────────────────────────────


def test_env_name_with_a_newline_injects_a_second_dot_env_line(
    client, config_dir, mcp_json
) -> None:
    """Finding S1: the key is written raw, so ``X\\nY`` becomes two lines."""
    response = create(client, "alpha", stdio_body(env={"X\nY": "v"}))
    assert response.status_code == 201
    assert env_text(config_dir) == 'X\nY="v"\n'
    assert read_json(mcp_json)["servers"]["alpha"]["env"] == {"X\nY": "${X\nY}"}


def test_env_names_that_are_not_identifiers_are_accepted(client, config_dir) -> None:
    """Finding S1: ``a b``, ``1BAD`` and ``PATH`` all land in ``.env``."""
    for name, key in (("a", "a b"), ("b", "1BAD"), ("c", "PATH")):
        assert create(client, name, stdio_body(env={key: "v"})).status_code == 201
    assert env_text(config_dir) == 'a b="v"\n1BAD="v"\nPATH="v"\n'


@pytest.mark.parametrize("key", ["A=B", "", "NUL\0X"])
def test_env_names_python_cannot_put_in_os_environ_are_a_500_and_save_nothing(
    client, config_dir, mcp_json, key
) -> None:
    """Finding S2: ``os.environ[key] = ...`` raises, which is an unhandled 500."""
    before = mcp_json.read_bytes()
    response = create(client, "alpha", stdio_body(env={key: "v"}))
    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert mcp_json.read_bytes() == before
    assert not (config_dir / ".env").exists()


def test_a_500_part_way_leaves_earlier_keys_in_the_process_environment(
    client, config_dir, tmp_path
) -> None:
    """Finding S2: ``OK`` reaches ``os.environ`` although ``.env`` is never written."""
    response = create(client, "alpha", stdio_body(env={"LEAKED_OK": "v1", "A=B": "x"}))
    assert response.status_code == 500
    assert not (config_dir / ".env").exists()
    dump = tmp_path / "dump.json"
    with fresh(client) as again:
        create(again, "beta", stdio_body(dump=dump, env={"Z": "${LEAKED_OK}"}))
    assert child_env(dump)["Z"] == "v1"


def test_a_secret_written_by_create_is_live_in_the_process_environment(
    client, tmp_path
) -> None:
    """Finding S3: the value is also exported into the sidecar's ``os.environ``.

    The deleted server's secret still resolves for any later server.
    """
    create(client, "alpha", stdio_body(env={"GLOBAL_SECRET": "v9"}))
    client.delete("/api/mcp/servers/alpha")
    dump = tmp_path / "dump.json"
    create(client, "beta", stdio_body(dump=dump, env={"Z": "${GLOBAL_SECRET}"}))
    assert child_env(dump)["Z"] == "v9"


# ── HTTP headers and OAuth ──────────────────────────────────────────────────


def http_server(url, **fields):
    return {"transport": "http", "url": url, **fields}


def test_oauth_client_values_move_to_dot_env_under_derived_names(
    client, config_dir, mcp_json
) -> None:
    response = create(
        client,
        "my-srv",
        http_server("http://127.0.0.1:9/mcp", oauth={"client_id": "cid", "client_secret": "csec"}),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["state"] == "auth_required"
    assert body["error"] == "MCP server 'my-srv' needs OAuth. Use Settings -> MCP -> Connect OAuth."
    assert body["config"]["oauth"] == {"client_id": MASK, "client_secret": MASK}
    assert read_json(mcp_json)["servers"]["my-srv"]["oauth"] == {
        "client_id": "${MY_SRV_MCP_CLIENT_ID}",
        "client_secret": "${MY_SRV_MCP_CLIENT_SECRET}",
    }
    assert env_text(config_dir) == 'MY_SRV_MCP_CLIENT_ID="cid"\nMY_SRV_MCP_CLIENT_SECRET="csec"\n'


def test_oauth_env_names_fold_runs_of_non_alphanumerics_to_one_underscore(
    client, config_dir
) -> None:
    create(client, "a--b__c", http_server("http://127.0.0.1:9/mcp", oauth={"client_id": "x"}))
    assert env_text(config_dir) == 'A_B_C_MCP_CLIENT_ID="x"\n'


def test_oauth_refs_and_empty_values_are_not_written_to_dot_env(
    client, config_dir, mcp_json
) -> None:
    create(
        client,
        "alpha",
        http_server("http://127.0.0.1:9/mcp", oauth={"client_id": "${MY_ID}", "client_secret": ""}),
    )
    assert not (config_dir / ".env").exists()
    assert read_json(mcp_json)["servers"]["alpha"]["oauth"] == {
        "client_id": "${MY_ID}",
        "client_secret": "",
    }


def test_an_empty_oauth_object_is_kept_and_the_server_needs_oauth(
    client, mcp_json
) -> None:
    response = create(client, "alpha", http_server("http://127.0.0.1:9/mcp", oauth={}))
    assert response.json()["config"]["oauth"] == {"client_id": None, "client_secret": None}
    assert read_json(mcp_json)["servers"]["alpha"]["oauth"] == {
        "client_id": None,
        "client_secret": None,
    }


def test_oauth_with_only_a_client_id_has_a_null_secret(client) -> None:
    response = create(
        client, "alpha", http_server("http://127.0.0.1:9/mcp", oauth={"client_id": "cid"})
    )
    assert response.json()["config"]["oauth"] == {"client_id": MASK, "client_secret": None}


def test_update_with_masked_values_keeps_the_stored_refs(
    client, config_dir, mcp_json
) -> None:
    create(
        client,
        "alpha",
        http_server(
            "http://127.0.0.1:9/mcp",
            headers={"Authorization": "Bearer abc"},
            oauth={"client_id": "cid", "client_secret": "csec"},
        ),
    )
    before_env = env_text(config_dir)
    response = client.put(
        "/api/mcp/servers/alpha",
        json={
            "server": http_server(
                "http://127.0.0.1:9/mcp",
                headers={"Authorization": MASK},
                oauth={"client_id": MASK, "client_secret": MASK},
            )
        },
    )
    assert response.status_code == 200
    stored = read_json(mcp_json)["servers"]["alpha"]
    assert stored["headers"] == {"Authorization": "Bearer abc"}
    assert stored["oauth"] == {
        "client_id": "${ALPHA_MCP_CLIENT_ID}",
        "client_secret": "${ALPHA_MCP_CLIENT_SECRET}",
    }
    assert env_text(config_dir) == before_env


def test_update_with_new_oauth_literals_overwrites_dot_env(client, config_dir) -> None:
    create(client, "alpha", http_server("http://127.0.0.1:9/mcp", oauth={"client_id": "one"}))
    client.put(
        "/api/mcp/servers/alpha",
        json={"server": http_server("http://127.0.0.1:9/mcp", oauth={"client_id": "two"})},
    )
    assert env_text(config_dir) == 'ALPHA_MCP_CLIENT_ID="two"\n'


def test_update_that_drops_oauth_leaves_the_secrets_in_dot_env(
    client, config_dir, mcp_json
) -> None:
    create(client, "alpha", http_server("http://127.0.0.1:9/mcp", oauth={"client_id": "one"}))
    response = client.put(
        "/api/mcp/servers/alpha", json={"server": http_server("http://127.0.0.1:9/mcp")}
    )
    assert response.json()["config"]["oauth"] is None
    assert read_json(mcp_json)["servers"]["alpha"]["oauth"] is None
    assert env_text(config_dir) == 'ALPHA_MCP_CLIENT_ID="one"\n'


def test_a_masked_value_for_a_new_header_is_stored_literally(client, mcp_json) -> None:
    """Finding S4: ``********`` with no earlier value is saved as the header value."""
    create(client, "alpha", http_server("http://127.0.0.1:9/mcp", headers={"A": "one"}))
    client.put(
        "/api/mcp/servers/alpha",
        json={
            "server": http_server(
                "http://127.0.0.1:9/mcp", headers={"A": MASK, "B": MASK, "C": "new"}
            )
        },
    )
    assert read_json(mcp_json)["servers"]["alpha"]["headers"] == {
        "A": "one",
        "B": MASK,
        "C": "new",
    }


def test_masked_oauth_values_on_create_are_stored_literally(client, mcp_json) -> None:
    """Finding S4: on POST there is nothing to merge with, so the mask is the value."""
    create(
        client,
        "alpha",
        http_server("http://127.0.0.1:9/mcp", oauth={"client_id": MASK, "client_secret": MASK}),
    )
    assert read_json(mcp_json)["servers"]["alpha"]["oauth"] == {
        "client_id": MASK,
        "client_secret": MASK,
    }


def test_update_that_switches_transport_does_not_merge_masked_headers(
    client, mcp_json
) -> None:
    create(client, "alpha", stdio_body())
    client.put(
        "/api/mcp/servers/alpha",
        json={"server": http_server("http://127.0.0.1:9/mcp", headers={"A": MASK})},
    )
    assert read_json(mcp_json)["servers"]["alpha"]["headers"] == {"A": MASK}


def test_http_header_refs_are_resolved_from_dot_env_when_connecting(
    client, config_dir, http_mcp
) -> None:
    create(client, "first", stdio_body(env={"MY_TOKEN": "abc123"}))
    response = create(
        client,
        "web",
        http_server(
            http_mcp.url,
            headers={"Authorization": "Bearer ${MY_TOKEN}", "X-Plain": "$MY_TOKEN", "X-Lit": "lit"},
        ),
    )
    assert response.json()["state"] == "ready"
    sent = http_mcp.requests[0]["headers"]
    assert sent["Authorization"] == "Bearer abc123"
    assert sent["X-Plain"] == "abc123"
    assert sent["X-Lit"] == "lit"


def test_an_unresolved_header_ref_is_sent_as_written(client, http_mcp) -> None:
    create(client, "web", http_server(http_mcp.url, headers={"Authorization": "Bearer ${NOPE}"}))
    assert http_mcp.requests[0]["headers"]["Authorization"] == "Bearer ${NOPE}"


def test_an_env_name_that_is_a_provider_key_overwrites_the_users_real_key(
    client, config_dir, mcp_json
) -> None:
    """Finding S1: ``<config>/.env`` is shared with the provider API keys.

    Nothing reserves those names, so one MCP request replaces a stored key.
    """
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / ".env").write_bytes(b'OPENAI_API_KEY="sk-real"\n')
    response = create(client, "alpha", stdio_body(env={"OPENAI_API_KEY": "attacker"}))
    assert response.status_code == 201
    assert env_text(config_dir) == 'OPENAI_API_KEY="attacker"\n'
    assert read_json(mcp_json)["servers"]["alpha"]["env"] == {
        "OPENAI_API_KEY": "${OPENAI_API_KEY}"
    }
