# Environment setup

Read this only when a required tool is missing. Ask the user before
installing anything; every command below changes their machine or workspace.

## Contents

- How this skill runs code
- Installing uv and bun
- TypeScript project for PptxGenJS
- System dependencies (PDF/PNG rendering)

## How this skill runs code

- Python: every bundled script and every generator runs as
  `uv run --with python-pptx python <file>.py`. `uv` fetches `python-pptx`
  (which pulls in `lxml` and `Pillow`) into its cache on first use; no
  project, virtual environment, or `pip install` is needed. Add
  `--with defusedxml` when a script of yours parses XML with `defusedxml`.
- TypeScript: PptxGenJS generators run with `bun run <file>.ts` inside a Bun
  project in the user's workspace.
- Only if the user explicitly refuses `uv` / `bun`: use `pip install
  python-pptx` in a virtual environment you manage and run
  `python scripts/<name>.py`, and `npm`/`pnpm` + `npx tsx` instead of `bun`.

## Installing uv and bun

```bash
# uv (Python package/project manager)
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# bun (TypeScript runtime)
# macOS / Linux
curl -fsSL https://bun.sh/install | bash
# Windows: powershell -c "irm bun.sh/install.ps1|iex"
```

## TypeScript project for PptxGenJS

Use project-local installs, not global ones:

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

Run generators directly as TypeScript — no transpilation needed:

```bash
bun run create-ppt.ts
```

**Always run type checking after writing or modifying TS code:**

```bash
bun tsc --noEmit
```

Generated code can use outdated PptxGenJS API signatures or deprecated
syntax; a type check catches these mismatches before runtime.

## System dependencies (PDF/PNG rendering)

`scripts/render_pdf.py` needs LibreOffice; `scripts/render_slides.py` and
`scripts/contact_sheet.py` also need Poppler's `pdftoppm`. The scripts find
LibreOffice through `EVOFLUX_SOFFICE` or `PATH`.

```bash
# macOS
brew install --cask libreoffice
brew install poppler

# Debian/Ubuntu
sudo apt-get install -y libreoffice poppler-utils
```

On Windows, use the LibreOffice installer and a Poppler build on `PATH`.

The bundled scripts use only the standard library plus `python-pptx`, `lxml`,
and `Pillow`. External binaries (`soffice`, `pdftoppm`) are invoked as
subprocesses; nothing is bundled or statically linked.
