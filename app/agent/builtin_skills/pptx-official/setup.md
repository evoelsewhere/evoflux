# Environment setup

Read this only when a required tool is missing. The runtime contract in
SKILL.md decides *which* tier you are on; this file is how to install the
pieces once you know.



### Prerequisites

If `uv` or `bun` are not yet installed:

```bash
# Install uv (Python package/project manager)
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Install bun (TypeScript runtime, replaces Node.js for this workflow)
# macOS / Linux
curl -fsSL https://bun.sh/install | bash
# Windows: powershell -c "irm bun.sh/install.ps1|iex"
```

Only if the user explicitly refuses `uv` / `bun`, substitute `pip` (in a venv you manage yourself) for `uv`, and `npm`/`pnpm` + `npx tsx` for `bun` — everything else in this skill stays the same.

### Python (uv)

Python dependencies are managed by `uv`. Do not use `pip` directly.

```bash
# Initialize project (if no pyproject.toml exists)
uv init -p 3.12

# Add dependencies
uv add python-pptx lxml Pillow
uv add defusedxml                  # safe XML parsing (recommended for manual XML edits)
```

**Rules:**
- Never use `pip` — always `uv add` for packages.
- Never run `python scripts/...` directly — always `uv run scripts/...`.
- Don't manually manage environments with `python -m venv` or `source .venv/bin/activate`.

### TypeScript (bun)

For PptxGenJS creation, use `bun` (project-local, not global installs):

```bash
# Initialize (if no package.json exists)
bun init -y

# Add dependencies
bun add pptxgenjs                  # core PPTX creation library
bun add react react-dom sharp      # rasterization (icons + formulas)
bun add react-icons                # icon library (FA, MD, etc.)
bun add mathjax-full               # LaTeX formula rendering

# Type definitions (including Bun runtime types)
bun add -d @types/bun @types/react @types/react-dom
```

Create a `tsconfig.json` if one doesn't exist:
```json
{
  "compilerOptions": {
    "lib": ["ESNext"],
    "target": "ESNext",
    "module": "Preserve",
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "skipLibCheck": true,
    "types": ["bun"]
  }
}
```

Run scripts directly as TypeScript — no transpilation needed:
```bash
bun run create-ppt.ts
```

**Always run type checking after writing or modifying TS code:**
```bash
bun tsc --noEmit
```
Models may inadvertently use outdated PptxGenJS API signatures or
deprecated syntax without realizing it. A type check catches these
mismatches before runtime.

### System dependencies (PDF/PNG rendering)

```bash
# macOS
brew install --cask libreoffice
brew install poppler

# Debian/Ubuntu
sudo apt-get install -y libreoffice poppler-utils
```

Every script under `scripts/` uses only the standard library plus
`python-pptx`, `lxml`, and `Pillow`. No proprietary dependencies. External
binaries (`soffice`, `pdftoppm`) are invoked as subprocesses; nothing is
bundled or statically linked.
