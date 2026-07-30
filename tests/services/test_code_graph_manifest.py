"""Unit tests for app/services/code_graph/manifest.py's Maven support and the
``is_likely_external`` cross-repo pre-filter (added to fix a real 4-repo
project showing 27744 unresolved / 0 resolved references — almost entirely
noise from third-party library imports like Liquibase that can never be a
sibling-repo reference)."""

from __future__ import annotations

import textwrap

from app.services.code_graph.manifest import (
    is_likely_external,
    read_declared_dependencies,
    read_manifests,
)


# ── Maven identity ───────────────────────────────────────────────────────────


def test_maven_identity_from_pom(tmp_path):
    (tmp_path / "pom.xml").write_text(
        textwrap.dedent(
            """\
            <project xmlns="http://maven.apache.org/POM/4.0.0">
                <groupId>org.openmrs</groupId>
                <artifactId>openmrs-api</artifactId>
                <version>2.7.0</version>
            </project>
            """
        )
    )
    manifests = read_manifests(tmp_path)
    maven = [m for m in manifests if m.ecosystem == "maven"]
    assert len(maven) == 1
    assert maven[0].package_name == "org.openmrs:openmrs-api"


def test_maven_identity_inherits_parent_group_id(tmp_path):
    (tmp_path / "pom.xml").write_text(
        textwrap.dedent(
            """\
            <project xmlns="http://maven.apache.org/POM/4.0.0">
                <parent>
                    <groupId>org.openmrs</groupId>
                    <artifactId>openmrs</artifactId>
                    <version>2.7.0</version>
                </parent>
                <artifactId>openmrs-api</artifactId>
            </project>
            """
        )
    )
    manifests = read_manifests(tmp_path)
    maven = [m for m in manifests if m.ecosystem == "maven"]
    assert maven[0].package_name == "org.openmrs:openmrs-api"


def test_maven_declared_dependencies(tmp_path):
    (tmp_path / "pom.xml").write_text(
        textwrap.dedent(
            """\
            <project xmlns="http://maven.apache.org/POM/4.0.0">
                <groupId>org.openmrs</groupId>
                <artifactId>openmrs-api</artifactId>
                <dependencies>
                    <dependency>
                        <groupId>org.liquibase</groupId>
                        <artifactId>liquibase-core</artifactId>
                        <version>4.9.1</version>
                    </dependency>
                    <dependency>
                        <groupId>org.springframework</groupId>
                        <artifactId>spring-context</artifactId>
                        <version>5.3.20</version>
                    </dependency>
                </dependencies>
            </project>
            """
        )
    )
    deps = read_declared_dependencies(tmp_path)
    assert "org.liquibase" in deps
    assert "org.springframework" in deps


def test_no_pom_no_manifest(tmp_path):
    assert read_manifests(tmp_path) == []
    assert read_declared_dependencies(tmp_path) == []


# ── is_likely_external: the reported Liquibase case ─────────────────────────


def test_liquibase_import_is_external_even_without_declared_dependency():
    """The real-world case: groupId "org.liquibase" doesn't literally prefix
    the Java package "liquibase.*" — the bundled well-known-library backstop
    must catch this even when the manifest-derived signal can't."""
    assert is_likely_external(
        "liquibase.change.ChangeMetadata",
        file_path="Foo.java",
        declared_dependencies=[],
    )


def test_jdk_imports_always_external():
    assert is_likely_external(
        "java.util.List", file_path="Foo.java", declared_dependencies=[]
    )
    assert is_likely_external(
        "javax.persistence.Entity", file_path="Foo.java", declared_dependencies=[]
    )


def test_declared_dependency_filters_import():
    assert is_likely_external(
        "com.fasterxml.jackson.databind.ObjectMapper",
        file_path="Foo.java",
        declared_dependencies=["com.fasterxml.jackson.core"],
    )


def test_go_standard_library_always_external():
    assert is_likely_external("fmt", file_path="main.go", declared_dependencies=[])
    assert is_likely_external("net/http", file_path="main.go", declared_dependencies=[])
    assert is_likely_external(
        "encoding/json", file_path="main.go", declared_dependencies=[]
    )


def test_go_module_path_not_external():
    assert not is_likely_external(
        "github.com/acme/other", file_path="main.go", declared_dependencies=[]
    )


def test_python_stdlib_always_external():
    assert is_likely_external("os", file_path="main.py", declared_dependencies=[])
    assert is_likely_external(
        "collections.abc", file_path="main.py", declared_dependencies=[]
    )


def test_python_sibling_package_not_external():
    assert not is_likely_external(
        "shared_lib", file_path="main.py", declared_dependencies=[]
    )


def test_npm_scoped_package_not_misclassified_by_go_rule():
    """A scoped npm import contains '/' with no dot in the first segment —
    must not be misidentified as a Go-stdlib-style reference."""
    assert not is_likely_external(
        "@acme/shared", file_path="index.js", declared_dependencies=[]
    )


def test_relative_imports_never_external():
    assert not is_likely_external(
        "./sibling", file_path="index.js", declared_dependencies=[]
    )
    assert not is_likely_external(
        ".utils", file_path="main.py", declared_dependencies=[]
    )


def test_real_cross_repo_java_reference_not_filtered():
    """A plausible sibling-repo Java reference must NOT be caught by any
    rule — false positives here would silently hide a real cross-repo link."""
    assert not is_likely_external(
        "com.acme.other.Helper",
        file_path="Foo.java",
        declared_dependencies=["org.liquibase"],
    )
