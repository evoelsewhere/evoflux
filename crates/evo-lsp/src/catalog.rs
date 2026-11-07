//! The language servers evo knows: what they serve, how to start them, and
//! how to install them.

use serde::Serialize;

/// How a server gets onto this computer.
#[derive(Debug, Clone, Serialize)]
#[serde(tag = "kind", rename_all = "camelCase")]
pub enum Install {
    /// `npm install` into its own folder; `bin` from `node_modules/.bin`.
    Npm { packages: &'static [&'static str] },
    /// `go install <module>@latest` with `GOBIN` set to its folder.
    Go { module: &'static str },
    /// `rustup component add <component>`.
    Rustup { component: &'static str },
    /// `dotnet tool install <tool> --tool-path <folder>`.
    Dotnet { tool: &'static str },
    /// `gem install <gem> --install-dir <folder>`.
    Gem { gem: &'static str },
    /// The latest GitHub release: the asset whose name contains every part of
    /// the platform's pattern, unpacked when it is a zip or tar.gz; the binary
    /// found by name inside.
    GithubRelease {
        repo: &'static str,
        assets: &'static [Asset],
    },
    /// Comes with a toolchain; only found on PATH.
    System { hint: &'static str },
}

#[derive(Debug, Clone, Serialize)]
pub struct Asset {
    pub os: &'static str,
    pub arch: &'static str,
    /// Every part must appear in the asset name.
    pub contains: &'static [&'static str],
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Server {
    pub id: &'static str,
    pub name: &'static str,
    /// Shown in the app: "Rust", "TypeScript / JavaScript".
    pub language: &'static str,
    /// LSP language ids by file extension (without the dot).
    pub extensions: &'static [(&'static str, &'static str)],
    /// Files that mark a project root for this language.
    pub root_markers: &'static [&'static str],
    /// The executable's name (without `.exe` / `.cmd`).
    pub command: &'static str,
    pub args: &'static [&'static str],
    pub install: Install,
    /// Programs the installer or the server needs (`node`, `go`, `java`, …).
    pub requires: &'static [&'static str],
    /// Settings sent as `initializationOptions`.
    #[serde(skip)]
    pub init_options: Option<&'static str>,
}

impl Server {
    pub fn language_id(&self, extension: &str) -> Option<&'static str> {
        let ext = extension.to_ascii_lowercase();
        self.extensions
            .iter()
            .find(|(e, _)| *e == ext)
            .map(|(_, id)| *id)
    }
}

const NPM: &[&str] = &["node", "npm"];

pub static SERVERS: &[Server] = &[
    Server {
        id: "rust-analyzer",
        name: "rust-analyzer",
        language: "Rust",
        extensions: &[("rs", "rust")],
        root_markers: &["Cargo.toml", "rust-project.json"],
        command: "rust-analyzer",
        args: &[],
        install: Install::Rustup { component: "rust-analyzer" },
        requires: &["rustup"],
        init_options: None,
    },
    Server {
        id: "typescript",
        name: "TypeScript Language Server",
        language: "TypeScript / JavaScript",
        extensions: &[
            ("ts", "typescript"),
            ("tsx", "typescriptreact"),
            ("mts", "typescript"),
            ("cts", "typescript"),
            ("js", "javascript"),
            ("jsx", "javascriptreact"),
            ("mjs", "javascript"),
            ("cjs", "javascript"),
        ],
        root_markers: &["tsconfig.json", "jsconfig.json", "package.json"],
        command: "typescript-language-server",
        args: &["--stdio"],
        install: Install::Npm { packages: &["typescript-language-server", "typescript"] },
        requires: NPM,
        init_options: None,
    },
    Server {
        id: "pyright",
        name: "Pyright",
        language: "Python",
        extensions: &[("py", "python"), ("pyi", "python")],
        root_markers: &["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "pyrightconfig.json", "Pipfile"],
        command: "pyright-langserver",
        args: &["--stdio"],
        install: Install::Npm { packages: &["pyright"] },
        requires: NPM,
        init_options: None,
    },
    Server {
        id: "gopls",
        name: "gopls",
        language: "Go",
        extensions: &[("go", "go")],
        root_markers: &["go.mod", "go.work"],
        command: "gopls",
        args: &[],
        install: Install::Go { module: "golang.org/x/tools/gopls" },
        requires: &["go"],
        init_options: None,
    },
    Server {
        id: "clangd",
        name: "clangd",
        language: "C / C++",
        extensions: &[
            ("c", "c"),
            ("h", "c"),
            ("cc", "cpp"),
            ("cpp", "cpp"),
            ("cxx", "cpp"),
            ("hpp", "cpp"),
            ("hh", "cpp"),
            ("hxx", "cpp"),
        ],
        root_markers: &["compile_commands.json", "CMakeLists.txt", ".clangd", "compile_flags.txt", "Makefile"],
        command: "clangd",
        args: &[],
        install: Install::GithubRelease {
            repo: "clangd/clangd",
            assets: &[
                Asset { os: "windows", arch: "", contains: &["clangd-windows-", ".zip"] },
                Asset { os: "linux", arch: "x86_64", contains: &["clangd-linux-", ".zip"] },
                Asset { os: "macos", arch: "", contains: &["clangd-mac-", ".zip"] },
            ],
        },
        requires: &[],
        init_options: None,
    },
    Server {
        id: "csharp-ls",
        name: "csharp-ls",
        language: "C#",
        extensions: &[("cs", "csharp")],
        root_markers: &["*.sln", "*.csproj", "global.json"],
        command: "csharp-ls",
        args: &[],
        install: Install::Dotnet { tool: "csharp-ls" },
        requires: &["dotnet"],
        init_options: None,
    },
    Server {
        id: "kotlin",
        name: "Kotlin Language Server",
        language: "Kotlin",
        extensions: &[("kt", "kotlin"), ("kts", "kotlin")],
        root_markers: &["settings.gradle.kts", "build.gradle.kts", "settings.gradle", "build.gradle", "pom.xml"],
        command: "kotlin-language-server",
        args: &[],
        install: Install::GithubRelease {
            repo: "fwcd/kotlin-language-server",
            assets: &[Asset { os: "", arch: "", contains: &["server.zip"] }],
        },
        requires: &["java"],
        init_options: None,
    },
    Server {
        id: "jdtls",
        name: "Eclipse JDT Language Server",
        language: "Java",
        extensions: &[("java", "java")],
        root_markers: &["pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", ".project"],
        command: "jdtls",
        args: &[],
        install: Install::System { hint: "Install jdtls (needs Java 21+) and put it on PATH, e.g. `brew install jdtls` or the Eclipse download." },
        requires: &["java"],
        init_options: None,
    },
    Server {
        id: "intelephense",
        name: "Intelephense",
        language: "PHP",
        extensions: &[("php", "php")],
        root_markers: &["composer.json"],
        command: "intelephense",
        args: &["--stdio"],
        install: Install::Npm { packages: &["intelephense"] },
        requires: NPM,
        init_options: None,
    },
    Server {
        id: "ruby-lsp",
        name: "Ruby LSP",
        language: "Ruby",
        extensions: &[("rb", "ruby"), ("rake", "ruby")],
        root_markers: &["Gemfile", ".ruby-version"],
        command: "ruby-lsp",
        args: &[],
        install: Install::Gem { gem: "ruby-lsp" },
        requires: &["gem"],
        init_options: None,
    },
    Server {
        id: "html",
        name: "HTML Language Server",
        language: "HTML",
        extensions: &[("html", "html"), ("htm", "html")],
        root_markers: &["index.html", "package.json"],
        command: "vscode-html-language-server",
        args: &["--stdio"],
        install: Install::Npm { packages: &["vscode-langservers-extracted"] },
        requires: NPM,
        init_options: Some(r#"{"provideFormatter":true}"#),
    },
    Server {
        id: "css",
        name: "CSS Language Server",
        language: "CSS / SCSS / Less",
        extensions: &[("css", "css"), ("scss", "scss"), ("less", "less")],
        root_markers: &["package.json"],
        command: "vscode-css-language-server",
        args: &["--stdio"],
        install: Install::Npm { packages: &["vscode-langservers-extracted"] },
        requires: NPM,
        init_options: None,
    },
    Server {
        id: "json",
        name: "JSON Language Server",
        language: "JSON",
        extensions: &[("json", "json"), ("jsonc", "jsonc")],
        root_markers: &["package.json"],
        command: "vscode-json-language-server",
        args: &["--stdio"],
        install: Install::Npm { packages: &["vscode-langservers-extracted"] },
        requires: NPM,
        init_options: None,
    },
    Server {
        id: "yaml",
        name: "YAML Language Server",
        language: "YAML",
        extensions: &[("yaml", "yaml"), ("yml", "yaml")],
        root_markers: &[],
        command: "yaml-language-server",
        args: &["--stdio"],
        install: Install::Npm { packages: &["yaml-language-server"] },
        requires: NPM,
        init_options: None,
    },
    Server {
        id: "bash",
        name: "Bash Language Server",
        language: "Shell",
        extensions: &[("sh", "shellscript"), ("bash", "shellscript"), ("zsh", "shellscript")],
        root_markers: &[],
        command: "bash-language-server",
        args: &["start"],
        install: Install::Npm { packages: &["bash-language-server"] },
        requires: NPM,
        init_options: None,
    },
    Server {
        id: "dockerfile",
        name: "Dockerfile Language Server",
        language: "Dockerfile",
        extensions: &[("dockerfile", "dockerfile")],
        root_markers: &["Dockerfile"],
        command: "docker-langserver",
        args: &["--stdio"],
        install: Install::Npm { packages: &["dockerfile-language-server-nodejs"] },
        requires: NPM,
        init_options: None,
    },
    Server {
        id: "svelte",
        name: "Svelte Language Server",
        language: "Svelte",
        extensions: &[("svelte", "svelte")],
        root_markers: &["svelte.config.js", "svelte.config.ts"],
        command: "svelteserver",
        args: &["--stdio"],
        install: Install::Npm { packages: &["svelte-language-server"] },
        requires: NPM,
        init_options: None,
    },
    Server {
        id: "lua",
        name: "Lua Language Server",
        language: "Lua",
        extensions: &[("lua", "lua")],
        root_markers: &[".luarc.json", ".luarc.jsonc"],
        command: "lua-language-server",
        args: &[],
        install: Install::GithubRelease {
            repo: "LuaLS/lua-language-server",
            assets: &[
                Asset { os: "windows", arch: "x86_64", contains: &["win32-x64", ".zip"] },
                Asset { os: "linux", arch: "x86_64", contains: &["linux-x64", ".tar.gz"] },
                Asset { os: "linux", arch: "aarch64", contains: &["linux-arm64", ".tar.gz"] },
                Asset { os: "macos", arch: "aarch64", contains: &["darwin-arm64", ".tar.gz"] },
                Asset { os: "macos", arch: "x86_64", contains: &["darwin-x64", ".tar.gz"] },
            ],
        },
        requires: &[],
        init_options: None,
    },
    Server {
        id: "marksman",
        name: "Marksman",
        language: "Markdown",
        extensions: &[("md", "markdown"), ("markdown", "markdown")],
        root_markers: &[".marksman.toml"],
        command: "marksman",
        args: &["server"],
        install: Install::GithubRelease {
            repo: "artempyanykh/marksman",
            assets: &[
                Asset { os: "windows", arch: "", contains: &["marksman.exe"] },
                Asset { os: "linux", arch: "x86_64", contains: &["marksman-linux-x64"] },
                Asset { os: "linux", arch: "aarch64", contains: &["marksman-linux-arm64"] },
                Asset { os: "macos", arch: "", contains: &["marksman-macos"] },
            ],
        },
        requires: &[],
        init_options: None,
    },
    Server {
        id: "sourcekit-lsp",
        name: "SourceKit-LSP",
        language: "Swift",
        extensions: &[("swift", "swift")],
        root_markers: &["Package.swift"],
        command: "sourcekit-lsp",
        args: &[],
        install: Install::System { hint: "Comes with the Swift toolchain (Xcode, or swift.org on Linux and Windows)." },
        requires: &[],
        init_options: None,
    },
    Server {
        id: "dart",
        name: "Dart Analysis Server",
        language: "Dart / Flutter",
        extensions: &[("dart", "dart")],
        root_markers: &["pubspec.yaml"],
        command: "dart",
        args: &["language-server", "--protocol=lsp"],
        install: Install::System { hint: "Comes with the Dart or Flutter SDK." },
        requires: &[],
        init_options: None,
    },
];

pub fn find(id: &str) -> Option<&'static Server> {
    SERVERS.iter().find(|s| s.id == id)
}

/// The server for a file, by its extension (or a `Dockerfile` name).
pub fn for_file(path: &std::path::Path) -> Option<&'static Server> {
    let name = path.file_name()?.to_string_lossy().to_ascii_lowercase();
    let ext = if name == "dockerfile" || name.starts_with("dockerfile.") {
        "dockerfile".to_string()
    } else {
        path.extension()?.to_string_lossy().to_ascii_lowercase()
    };
    SERVERS.iter().find(|s| s.language_id(&ext).is_some())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

    #[test]
    fn files_map_to_servers() {
        assert_eq!(
            for_file(Path::new("src/main.rs")).unwrap().id,
            "rust-analyzer"
        );
        assert_eq!(for_file(Path::new("App.TSX")).unwrap().id, "typescript");
        assert_eq!(for_file(Path::new("Dockerfile")).unwrap().id, "dockerfile");
        assert!(for_file(Path::new("notes.xyz")).is_none());
        let ids: std::collections::HashSet<_> = SERVERS.iter().map(|s| s.id).collect();
        assert_eq!(ids.len(), SERVERS.len(), "ids are unique");
    }
}
