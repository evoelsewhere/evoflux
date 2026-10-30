#!/usr/bin/env bash
# Build the SQLite amalgamation (sqlite3.c, sqlite3.h, sqlite3ext.h) from a
# check-in on SQLite's begin-concurrent branch and print the sha256 of sqlite3.c.
#
#   bash scripts/migration/build_sqlite_amalgamation.sh <branch-or-checkin> [out-dir]
#
# Defaults to writing into server/vendor/libsqlite3-sys/sqlite3. Record the
# printed values in server/vendor/SQLITE_BRANCH.toml.
# Linux/macOS need cc and make; Windows (Git Bash) needs Visual Studio Build Tools.
set -euo pipefail
cd "$(dirname "$0")/../.."
ref="${1:?usage: build_sqlite_amalgamation.sh <branch-or-checkin> [out-dir]}"
out="$(mkdir -p "${2:-server/vendor/libsqlite3-sys/sqlite3}" && cd "${2:-server/vendor/libsqlite3-sys/sqlite3}" && pwd)"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# Resolve the branch name to its full check-in hash so the build is reproducible.
checkin=$(curl -sSfL "https://sqlite.org/src/info/$ref" | sed 's/<[^>]*>/ /g' |
  tr -s ' \n' ' ' | grep -o 'SHA3-256: [0-9a-f ]*' | head -1 | tr -cd '0-9a-f' | sed 's/^3256//')
[[ ${#checkin} -eq 64 ]] || { echo "error: cannot resolve check-in for $ref" >&2; exit 1; }
curl -sSfL -o "$work/sqlite.tar.gz" "https://sqlite.org/src/tarball/$checkin/sqlite.tar.gz"
tar -xzf "$work/sqlite.tar.gz" -C "$work"
src="$work/sqlite"
[[ "$(cat "$src/manifest.uuid")" == "$checkin" ]] || { echo "error: tarball check-in mismatch" >&2; exit 1; }

case "$(uname -s)" in
  MINGW* | MSYS* | CYGWIN*)
    vs=$("/c/Program Files (x86)/Microsoft Visual Studio/Installer/vswhere.exe" -latest -products '*' -property installationPath)
    # Makefile.msc runs the jimsh0.exe it builds from the current directory.
    printf '@call "%s\\VC\\Auxiliary\\Build\\vcvars64.bat" >nul\r\nset NoDefaultCurrentDirectoryInExePath=\r\nset "PATH=%%CD%%;%%PATH%%"\r\nnmake /nologo /f Makefile.msc sqlite3.c\r\n' "$vs" >"$src/build.cmd"
    (cd "$src" && cmd //c "$(cygpath -w "$src/build.cmd")")
    ;;
  *)
    (cd "$src" && ./configure && make sqlite3.c)
    ;;
esac

grep -q 'BEGIN CONCURRENT\|SQLITE_OMIT_CONCURRENT' "$src/sqlite3.c" || { echo "error: amalgamation lacks BEGIN CONCURRENT" >&2; exit 1; }
cp "$src/sqlite3.c" "$src/sqlite3.h" "$src/sqlite3ext.h" "$out/"
echo "checkin = \"$checkin\""
echo "version = \"$(cat "$src/VERSION")\""
echo "sqlite3_c_sha256 = \"$( (sha256sum "$out/sqlite3.c" 2>/dev/null || shasum -a 256 "$out/sqlite3.c") | cut -d' ' -f1)\""
