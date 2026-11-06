// Build evo-engine and stage it as the Tauri sidecar.
//
//   bun scripts/prepare-sidecar.ts            # debug engine
//   bun scripts/prepare-sidecar.ts --release  # release engine
//
// Tauri's `bundle.externalBin` expects `src-tauri/binaries/evo-engine-<target-triple>[.exe]`
// and installs it next to the app executable as `evo-engine[.exe]`, which is
// where the shell looks for it (src-tauri/src/engine.rs).

import { $ } from "bun";
import { copyFileSync, mkdirSync } from "node:fs";
import path from "node:path";

const release = process.argv.includes("--release");
const root = path.resolve(import.meta.dir, "../../..");
const desktop = path.resolve(import.meta.dir, "..");

const host = (await $`rustc -vV`.text()).match(/^host: (.+)$/m)?.[1]?.trim();
if (!host) throw new Error("could not read the host target triple from `rustc -vV`");

const profile = release ? "release" : "debug";
console.log(`building evo-engine (${profile}) for ${host}…`);
await $`cargo build -p evo-engine ${release ? ["--release"] : []}`.cwd(root);

const exe = host.includes("windows") ? ".exe" : "";
const source = path.join(root, "target", profile, `evo-engine${exe}`);
const targetDir = path.join(desktop, "src-tauri", "binaries");
const target = path.join(targetDir, `evo-engine-${host}${exe}`);
mkdirSync(targetDir, { recursive: true });
copyFileSync(source, target);
console.log(`staged ${path.relative(desktop, target)}`);
