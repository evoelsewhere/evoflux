"""Unit tests for the ecosystem coverage expansion in
app/services/code_graph/manifest.py: Gradle, Composer, Gem, Pub, NuGet,
CocoaPods, SwiftPM, Docker Compose, Helm, and Terraform.

Docker/Helm/Terraform only get path-dependency detection (no self-identity,
no declared-dependency filtering) since there's no source-code parser that
ever creates an UnresolvedImport/CrossRepoEdge candidate from Dockerfiles,
Chart.yaml, or .tf files today — this is groundwork, not an end-to-end
resolvable pipeline yet.
"""

from __future__ import annotations

import textwrap

from app.services.code_graph.manifest import (
    is_likely_external,
    read_declared_dependencies,
    read_manifests,
    read_path_dependencies,
)


# ── Gradle ────────────────────────────────────────────────────────────────────


def test_gradle_identity_from_settings_and_build(tmp_path):
    (tmp_path / "settings.gradle").write_text('rootProject.name = "my-service"\n')
    (tmp_path / "build.gradle").write_text('group = "com.acme"\nversion = "1.0.0"\n')
    manifests = read_manifests(tmp_path)
    gradle = [m for m in manifests if m.ecosystem == "gradle"]
    assert len(gradle) == 1
    assert gradle[0].package_name == "com.acme:my-service"


def test_gradle_identity_without_group(tmp_path):
    (tmp_path / "settings.gradle.kts").write_text('rootProject.name = "my-service"\n')
    manifests = read_manifests(tmp_path)
    gradle = [m for m in manifests if m.ecosystem == "gradle"]
    assert gradle[0].package_name == "my-service"


def test_gradle_include_build_path_dependency(tmp_path):
    (tmp_path / "settings.gradle").write_text(
        'rootProject.name = "app"\nincludeBuild("../shared-lib")\n'
    )
    deps = read_path_dependencies(tmp_path)
    gradle_deps = [d for d in deps if d.ecosystem == "gradle"]
    assert len(gradle_deps) == 1
    assert gradle_deps[0].relative_path == "../shared-lib"


def test_gradle_declared_dependencies(tmp_path):
    (tmp_path / "build.gradle").write_text(
        textwrap.dedent(
            """\
            dependencies {
                implementation 'org.springframework:spring-context:5.3.20'
                testImplementation "junit:junit:4.13.2"
            }
            """
        )
    )
    deps = read_declared_dependencies(tmp_path)
    assert "org.springframework" in deps
    assert "junit" in deps


# ── Composer (PHP) ────────────────────────────────────────────────────────────


def test_composer_identity_name_and_psr4(tmp_path):
    (tmp_path / "composer.json").write_text(
        textwrap.dedent(
            """\
            {
                "name": "acme/shared",
                "autoload": {"psr-4": {"Acme\\\\Shared\\\\": "src/"}}
            }
            """
        )
    )
    manifests = read_manifests(tmp_path)
    composer = [m for m in manifests if m.ecosystem == "composer"]
    names = {m.package_name for m in composer}
    assert "acme/shared" in names
    assert "Acme\\Shared" in names


def test_composer_path_dependency_resolves_sibling_name(tmp_path):
    sibling = tmp_path / "shared"
    sibling.mkdir()
    (sibling / "composer.json").write_text('{"name": "acme/shared"}')
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "composer.json").write_text(
        textwrap.dedent(
            """\
            {
                "name": "acme/app",
                "repositories": [{"type": "path", "url": "../shared"}]
            }
            """
        )
    )
    deps = read_path_dependencies(tmp_path / "app")
    composer_deps = [d for d in deps if d.ecosystem == "composer"]
    assert len(composer_deps) == 1
    assert composer_deps[0].alias == "acme/shared"
    assert composer_deps[0].relative_path == "../shared"


def test_composer_declared_dependencies_exclude_php_platform(tmp_path):
    (tmp_path / "composer.json").write_text(
        textwrap.dedent(
            """\
            {
                "name": "acme/app",
                "require": {"php": "^8.1", "illuminate/support": "^10.0"},
                "require-dev": {"phpunit/phpunit": "^10.0"}
            }
            """
        )
    )
    deps = read_declared_dependencies(tmp_path)
    assert "illuminate/support" in deps
    assert "phpunit/phpunit" in deps
    assert "php" not in deps


# ── Gem (Ruby / Bundler) ──────────────────────────────────────────────────────


def test_gemspec_identity(tmp_path):
    (tmp_path / "acme.gemspec").write_text(
        textwrap.dedent(
            """\
            Gem::Specification.new do |s|
              s.name = "acme"
              s.version = "1.0.0"
            end
            """
        )
    )
    manifests = read_manifests(tmp_path)
    gems = [m for m in manifests if m.ecosystem == "gem"]
    assert len(gems) == 1
    assert gems[0].package_name == "acme"


def test_gemfile_path_dependency(tmp_path):
    (tmp_path / "Gemfile").write_text(
        textwrap.dedent(
            """\
            source "https://rubygems.org"
            gem 'shared_lib', path: '../shared_lib'
            gem 'rails'
            """
        )
    )
    deps = read_path_dependencies(tmp_path)
    gem_deps = [d for d in deps if d.ecosystem == "gem"]
    assert len(gem_deps) == 1
    assert gem_deps[0].alias == "shared_lib"
    assert gem_deps[0].relative_path == "../shared_lib"


def test_gemfile_declared_dependencies(tmp_path):
    (tmp_path / "Gemfile").write_text('gem "rails"\ngem "rspec"\n')
    deps = read_declared_dependencies(tmp_path)
    assert "rails" in deps
    assert "rspec" in deps


# ── Pub (Dart) ────────────────────────────────────────────────────────────────


def test_pubspec_identity(tmp_path):
    (tmp_path / "pubspec.yaml").write_text("name: my_app\nversion: 1.0.0\n")
    manifests = read_manifests(tmp_path)
    pub = [m for m in manifests if m.ecosystem == "pub"]
    assert len(pub) == 1
    assert pub[0].package_name == "my_app"


def test_pubspec_path_dependency(tmp_path):
    (tmp_path / "pubspec.yaml").write_text(
        textwrap.dedent(
            """\
            name: my_app
            dependencies:
              shared_pkg:
                path: ../shared_pkg
              flutter:
                sdk: flutter
            """
        )
    )
    deps = read_path_dependencies(tmp_path)
    pub_deps = [d for d in deps if d.ecosystem == "pub"]
    assert len(pub_deps) == 1
    assert pub_deps[0].alias == "shared_pkg"
    assert pub_deps[0].relative_path == "../shared_pkg"


def test_pubspec_workspace_members(tmp_path):
    member = tmp_path / "packages" / "shared_pkg"
    member.mkdir(parents=True)
    (member / "pubspec.yaml").write_text("name: shared_pkg\n")
    (tmp_path / "pubspec.yaml").write_text(
        textwrap.dedent(
            """\
            name: my_workspace
            workspace:
              - packages/shared_pkg
            """
        )
    )
    deps = read_path_dependencies(tmp_path)
    pub_deps = [d for d in deps if d.ecosystem == "pub"]
    assert len(pub_deps) == 1
    assert pub_deps[0].alias == "shared_pkg"


def test_pubspec_declared_dependencies_exclude_flutter_sdk(tmp_path):
    (tmp_path / "pubspec.yaml").write_text(
        textwrap.dedent(
            """\
            name: my_app
            dependencies:
              http: ^1.0.0
              flutter:
                sdk: flutter
            """
        )
    )
    deps = read_declared_dependencies(tmp_path)
    assert "http" in deps
    assert "flutter" not in deps


# ── NuGet (.NET / C#) ─────────────────────────────────────────────────────────


def test_csproj_identity_from_assembly_name(tmp_path):
    (tmp_path / "Acme.Service.csproj").write_text(
        textwrap.dedent(
            """\
            <Project Sdk="Microsoft.NET.Sdk">
              <PropertyGroup>
                <AssemblyName>Acme.Service.Core</AssemblyName>
              </PropertyGroup>
            </Project>
            """
        )
    )
    manifests = read_manifests(tmp_path)
    nuget = [m for m in manifests if m.ecosystem == "nuget"]
    assert len(nuget) == 1
    assert nuget[0].package_name == "Acme.Service.Core"


def test_csproj_identity_falls_back_to_filename(tmp_path):
    (tmp_path / "Acme.Service.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk"></Project>'
    )
    manifests = read_manifests(tmp_path)
    nuget = [m for m in manifests if m.ecosystem == "nuget"]
    assert nuget[0].package_name == "Acme.Service"


def test_csproj_project_reference_path_dependency(tmp_path):
    shared_dir = tmp_path / "Shared"
    shared_dir.mkdir()
    (shared_dir / "Shared.csproj").write_text(
        textwrap.dedent(
            """\
            <Project Sdk="Microsoft.NET.Sdk">
              <PropertyGroup><AssemblyName>Acme.Shared</AssemblyName></PropertyGroup>
            </Project>
            """
        )
    )
    app_dir = tmp_path / "App"
    app_dir.mkdir()
    (app_dir / "App.csproj").write_text(
        textwrap.dedent(
            """\
            <Project Sdk="Microsoft.NET.Sdk">
              <ItemGroup>
                <ProjectReference Include="..\\Shared\\Shared.csproj" />
              </ItemGroup>
            </Project>
            """
        )
    )
    deps = read_path_dependencies(app_dir)
    nuget_deps = [d for d in deps if d.ecosystem == "nuget"]
    assert len(nuget_deps) == 1
    assert nuget_deps[0].alias == "Acme.Shared"


def test_csproj_declared_dependencies(tmp_path):
    (tmp_path / "App.csproj").write_text(
        textwrap.dedent(
            """\
            <Project Sdk="Microsoft.NET.Sdk">
              <ItemGroup>
                <PackageReference Include="Newtonsoft.Json" Version="13.0.1" />
              </ItemGroup>
            </Project>
            """
        )
    )
    deps = read_declared_dependencies(tmp_path)
    assert "Newtonsoft.Json" in deps


# ── CocoaPods (iOS) ───────────────────────────────────────────────────────────


def test_podspec_identity(tmp_path):
    (tmp_path / "Acme.podspec").write_text(
        textwrap.dedent(
            """\
            Pod::Spec.new do |s|
              s.name = "Acme"
              s.version = "1.0.0"
            end
            """
        )
    )
    manifests = read_manifests(tmp_path)
    pods = [m for m in manifests if m.ecosystem == "cocoapods"]
    assert len(pods) == 1
    assert pods[0].package_name == "Acme"


def test_podfile_path_dependency(tmp_path):
    (tmp_path / "Podfile").write_text(
        textwrap.dedent(
            """\
            target 'App' do
              pod 'SharedKit', :path => '../SharedKit'
              pod 'Alamofire'
            end
            """
        )
    )
    deps = read_path_dependencies(tmp_path)
    pod_deps = [d for d in deps if d.ecosystem == "cocoapods"]
    assert len(pod_deps) == 1
    assert pod_deps[0].alias == "SharedKit"
    assert pod_deps[0].relative_path == "../SharedKit"


def test_podfile_declared_dependencies(tmp_path):
    (tmp_path / "Podfile").write_text("pod 'Alamofire'\npod 'SnapKit'\n")
    deps = read_declared_dependencies(tmp_path)
    assert "Alamofire" in deps
    assert "SnapKit" in deps


# ── Swift Package Manager ─────────────────────────────────────────────────────


def test_package_swift_identity(tmp_path):
    (tmp_path / "Package.swift").write_text(
        textwrap.dedent(
            """\
            // swift-tools-version:5.9
            import PackageDescription

            let package = Package(
                name: "SharedKit",
                products: []
            )
            """
        )
    )
    manifests = read_manifests(tmp_path)
    spm = [m for m in manifests if m.ecosystem == "swiftpm"]
    assert len(spm) == 1
    assert spm[0].package_name == "SharedKit"


def test_package_swift_local_path_dependency(tmp_path):
    sibling = tmp_path / "SharedKit"
    sibling.mkdir()
    (sibling / "Package.swift").write_text(
        'let package = Package(\n    name: "SharedKit"\n)\n'
    )
    app_dir = tmp_path / "App"
    app_dir.mkdir()
    (app_dir / "Package.swift").write_text(
        textwrap.dedent(
            """\
            let package = Package(
                name: "App",
                dependencies: [
                    .package(path: "../SharedKit")
                ]
            )
            """
        )
    )
    deps = read_path_dependencies(app_dir)
    spm_deps = [d for d in deps if d.ecosystem == "swiftpm"]
    assert len(spm_deps) == 1
    assert spm_deps[0].alias == "SharedKit"
    assert spm_deps[0].relative_path == "../SharedKit"


def test_package_swift_declared_dependencies_from_url(tmp_path):
    (tmp_path / "Package.swift").write_text(
        textwrap.dedent(
            """\
            let package = Package(
                name: "App",
                dependencies: [
                    .package(url: "https://github.com/apple/swift-log.git", from: "1.0.0")
                ]
            )
            """
        )
    )
    deps = read_declared_dependencies(tmp_path)
    assert "swift-log" in deps


# ── Docker Compose (path-detection only) ──────────────────────────────────────


def test_docker_compose_build_context_path_dependency(tmp_path):
    (tmp_path / "docker-compose.yml").write_text(
        textwrap.dedent(
            """\
            services:
              worker:
                build:
                  context: ../worker-service
              db:
                image: postgres:16
            """
        )
    )
    deps = read_path_dependencies(tmp_path)
    docker_deps = [d for d in deps if d.ecosystem == "docker"]
    assert len(docker_deps) == 1
    assert docker_deps[0].alias == "worker"
    assert docker_deps[0].relative_path == "../worker-service"


# ── Helm ──────────────────────────────────────────────────────────────────────


def test_helm_chart_identity(tmp_path):
    (tmp_path / "Chart.yaml").write_text("name: my-chart\nversion: 1.0.0\n")
    manifests = read_manifests(tmp_path)
    helm = [m for m in manifests if m.ecosystem == "helm"]
    assert len(helm) == 1
    assert helm[0].package_name == "my-chart"


def test_helm_file_dependency_path(tmp_path):
    (tmp_path / "Chart.yaml").write_text(
        textwrap.dedent(
            """\
            name: umbrella
            dependencies:
              - name: common
                repository: "file://../common-chart"
                version: "1.0.0"
            """
        )
    )
    deps = read_path_dependencies(tmp_path)
    helm_deps = [d for d in deps if d.ecosystem == "helm"]
    assert len(helm_deps) == 1
    assert helm_deps[0].alias == "common"
    assert helm_deps[0].relative_path == "../common-chart"


# ── Terraform (path-detection only) ───────────────────────────────────────────


def test_terraform_module_path_dependency(tmp_path):
    (tmp_path / "main.tf").write_text(
        textwrap.dedent(
            """\
            module "networking" {
              source = "../modules/networking"
            }
            """
        )
    )
    deps = read_path_dependencies(tmp_path)
    tf_deps = [d for d in deps if d.ecosystem == "terraform"]
    assert len(tf_deps) == 1
    assert tf_deps[0].alias == "networking"
    assert tf_deps[0].relative_path == "../modules/networking"


# ── is_likely_external: structural rules for the newly-covered languages ──────


def test_csharp_bcl_and_microsoft_namespaces_always_external():
    assert is_likely_external(
        "System.Collections.Generic", file_path="Foo.cs", declared_dependencies=[]
    )
    assert is_likely_external(
        "Microsoft.Extensions.Logging", file_path="Foo.cs", declared_dependencies=[]
    )


def test_csharp_company_namespace_not_external():
    assert not is_likely_external(
        "MyCompany.Shared", file_path="Foo.cs", declared_dependencies=[]
    )


def test_dart_sdk_scheme_always_external():
    assert is_likely_external("dart:async", file_path="main.dart", declared_dependencies=[])
    assert is_likely_external("dart:core", file_path="main.dart", declared_dependencies=[])


def test_dart_flutter_package_always_external():
    assert is_likely_external(
        "package:flutter/material.dart", file_path="main.dart", declared_dependencies=[]
    )


def test_dart_own_package_not_external():
    assert not is_likely_external(
        "package:my_pkg/foo.dart", file_path="main.dart", declared_dependencies=[]
    )
    assert not is_likely_external(
        "sibling.dart", file_path="main.dart", declared_dependencies=[]
    )


def test_swift_apple_frameworks_always_external():
    assert is_likely_external("Foundation", file_path="Foo.swift", declared_dependencies=[])
    assert is_likely_external("UIKit", file_path="Foo.swift", declared_dependencies=[])


def test_swift_own_module_not_external():
    assert not is_likely_external(
        "MyOwnModule", file_path="Foo.swift", declared_dependencies=[]
    )


def test_objc_apple_framework_header_always_external():
    assert is_likely_external(
        "Foundation/Foundation.h", file_path="Foo.m", declared_dependencies=[]
    )


def test_objc_own_header_not_external():
    assert not is_likely_external(
        "MyHeader.h", file_path="Foo.m", declared_dependencies=[]
    )


def test_php_well_known_framework_namespace_always_external():
    assert is_likely_external(
        "Illuminate\\Support\\Facades\\DB", file_path="Foo.php", declared_dependencies=[]
    )


def test_php_own_namespace_not_external():
    assert not is_likely_external(
        "App\\Models\\User", file_path="Foo.php", declared_dependencies=[]
    )


def test_ruby_well_known_gem_always_external():
    assert is_likely_external(
        "active_support", file_path="foo.rb", declared_dependencies=[]
    )
    assert is_likely_external(
        "active_support/core_ext", file_path="foo.rb", declared_dependencies=[]
    )


def test_ruby_own_lib_not_external():
    assert not is_likely_external(
        "my_app/service", file_path="foo.rb", declared_dependencies=[]
    )
