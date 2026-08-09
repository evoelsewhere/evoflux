#!/usr/bin/env node

import fs from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";
import { pathToFileURL } from "node:url";

const PLACEHOLDERS = [
  /^click to add (title|subtitle|text)$/i,
  /^(title|subtitle|name|text|body) goes here$/i,
  /^lorem ipsum\b/i,
  /\b(?:todo|tbd)\b/i,
];

function fail(message) { throw new Error(message); }
async function readJson(filePath) { return JSON.parse(await fs.readFile(filePath, "utf8")); }
async function writeJson(filePath, value) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}
async function saveBlob(blob, outputPath) {
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  if (blob && typeof blob.arrayBuffer === "function") {
    await fs.writeFile(outputPath, Buffer.from(await blob.arrayBuffer()));
    return;
  }
  if (blob?.data instanceof Uint8Array || Buffer.isBuffer(blob?.data)) {
    await fs.writeFile(outputPath, Buffer.from(blob.data));
    return;
  }
  fail(`Expected binary artifact for ${outputPath}`);
}
async function artifactTool() {
  const entrypoint = process.env.EVOFLUX_ARTIFACT_TOOL_ENTRYPOINT;
  if (!entrypoint) fail("Missing EVOFLUX_ARTIFACT_TOOL_ENTRYPOINT");
  return import(pathToFileURL(path.resolve(entrypoint)).href);
}
function contentType(filePath) {
  const suffix = path.extname(filePath).toLowerCase();
  if (suffix === ".png") return "image/png";
  if (suffix === ".jpg" || suffix === ".jpeg") return "image/jpeg";
  if (suffix === ".webp") return "image/webp";
  if (suffix === ".gif") return "image/gif";
  if (suffix === ".svg") return "image/svg+xml";
  fail(`Unsupported presentation image type: ${suffix}`);
}
function parseNdjson(value) {
  return String(value || "").split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
}
function position(value) {
  return { left: value.left, top: value.top, width: value.width, height: value.height };
}
function line(fill, width) {
  return { style: "solid", fill, width };
}
function runChromium(executable, args, outputPath, timeoutMs = 60000) {
  return new Promise((resolve, reject) => {
    const child = spawn(executable, args, { stdio: ["ignore", "ignore", "pipe"] });
    let stderr = "";
    let screenshotReady = false;
    let statPending = false;
    let lastSize = -1;
    let stableChecks = 0;
    let forceKill = null;
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
      if (stderr.length > 20000) stderr = stderr.slice(-20000);
    });
    const screenshotPoll = setInterval(async () => {
      if (statPending || screenshotReady) return;
      statPending = true;
      try {
        const stat = await fs.stat(outputPath);
        if (stat.isFile() && stat.size > 0) {
          stableChecks = stat.size === lastSize ? stableChecks + 1 : 0;
          lastSize = stat.size;
          if (stableChecks >= 2) {
            screenshotReady = true;
            child.kill("SIGTERM");
            forceKill = setTimeout(() => child.kill("SIGKILL"), 2000);
          }
        }
      } catch (error) {
        if (error?.code !== "ENOENT") reject(error);
      } finally {
        statPending = false;
      }
    }, 150);
    const timeout = setTimeout(() => {
      child.kill("SIGKILL");
      reject(new Error(`Chromium render exceeded ${timeoutMs}ms`));
    }, timeoutMs);
    child.on("error", (error) => {
      clearTimeout(timeout);
      clearInterval(screenshotPoll);
      if (forceKill) clearTimeout(forceKill);
      reject(error);
    });
    child.on("exit", (code, signal) => {
      clearTimeout(timeout);
      clearInterval(screenshotPoll);
      if (forceKill) clearTimeout(forceKill);
      if (code === 0 || screenshotReady) resolve();
      else reject(new Error(
        `Chromium render failed (${code ?? signal}): ${stderr.trim() || "no diagnostics"}`,
      ));
    });
  });
}
async function renderHtmlShell({ chromiumPath, htmlPath, outputPath, profilePath, width, height, scale }) {
  if (!chromiumPath) fail("Missing bundled Chromium for PPTX visual-shell rendering");
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.mkdir(profilePath, { recursive: true });
  const args = [
    "--headless=new",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-extensions",
    "--disable-gpu",
    "--disable-javascript",
    "--disable-sync",
    "--hide-scrollbars",
    "--metrics-recording-only",
    "--mute-audio",
    "--no-first-run",
    "--run-all-compositor-stages-before-draw",
    "--allow-file-access-from-files",
    "--host-resolver-rules=MAP * 0.0.0.0",
    `--force-device-scale-factor=${scale}`,
    `--window-size=${width},${height}`,
    `--user-data-dir=${profilePath}`,
    `--screenshot=${outputPath}`,
    pathToFileURL(htmlPath).href,
  ];
  try {
    await runChromium(chromiumPath, args, outputPath);
    const stat = await fs.stat(outputPath);
    if (!stat.isFile() || stat.size === 0) fail(`Chromium screenshot is empty: ${outputPath}`);
  } finally {
    await fs.rm(profilePath, { recursive: true, force: true });
  }
}
async function addElement(slide, element, projectDir) {
  if (element.type === "text") {
    const shape = slide.shapes.add({
      geometry: "textbox", name: element.name, position: position(element.position),
      fill: element.fill, line: line(element.line_fill, element.line_width),
    });
    shape.text = element.text;
    shape.text.style = {
      fontSize: element.font_size, typeface: element.typeface || undefined,
      color: element.color, bold: element.bold, italic: element.italic,
      alignment: element.alignment, verticalAlignment: element.vertical_alignment,
      autoFit: element.auto_fit,
    };
    return;
  }
  if (element.type === "shape") {
    const shape = slide.shapes.add({
      geometry: element.geometry, name: element.name, position: position(element.position),
      fill: element.fill, line: line(element.line_fill, element.line_width),
      ...(element.border_radius == null ? {} : { borderRadius: element.border_radius }),
      ...(element.shadow ? { shadow: element.shadow } : {}),
    });
    if (element.text) {
      shape.text = element.text;
      shape.text.style = {
        fontSize: element.font_size, color: element.text_color, bold: element.bold,
        alignment: element.alignment, verticalAlignment: element.vertical_alignment,
        autoFit: "shrinkText",
      };
    }
    return;
  }
  if (element.type === "image") {
    const assetPath = path.isAbsolute(element.asset_path)
      ? path.resolve(element.asset_path)
      : path.resolve(projectDir, element.asset_path);
    const bytes = await fs.readFile(assetPath);
    slide.images.add({
      blob: bytes, contentType: contentType(assetPath), alt: element.alt,
      fit: element.fit, position: position(element.position), geometry: element.geometry,
      ...(element.border_radius == null ? {} : { borderRadius: element.border_radius }),
    });
    return;
  }
  if (element.type === "table") {
    const rows = element.values.length;
    const columns = element.values[0].length;
    const frame = element.position;
    const table = slide.tables.add({
      rows, columns, left: frame.left, top: frame.top, width: frame.width,
      height: frame.height, values: element.values,
    });
    const body = table.cells.block({ row: 0, column: 0, rowCount: rows, columnCount: columns });
    body.fill = element.body_fill;
    body.textStyle.color = element.body_text_color;
    body.textStyle.fontSize = element.font_size;
    if (element.header_row) {
      const header = table.cells.block({ row: 0, column: 0, rowCount: 1, columnCount: columns });
      header.fill = element.header_fill;
      header.textStyle.color = element.header_text_color;
      header.textStyle.bold = true;
    }
    return;
  }
  if (element.type === "chart") {
    slide.charts.add(element.chart_type, {
      position: position(element.position), title: element.title || undefined,
      categories: element.categories,
      series: element.series.map((series) => ({
        name: series.name, values: series.values, fill: series.fill || undefined,
      })),
      hasLegend: element.has_legend,
      dataLabels: element.show_values ? { showValue: true } : undefined,
    });
    return;
  }
  fail(`Unsupported native PPTX element: ${element.type}`);
}

async function main() {
  const [action, requestPath] = process.argv.slice(2);
  if (action !== "compose" || !requestPath) {
    fail("Usage: pptx_native_worker.mjs compose <request.json>");
  }
  const request = await readJson(path.resolve(requestPath));
  if (request.protocolVersion !== 2) {
    fail(`Unsupported PPTX native worker protocol: ${request.protocolVersion}`);
  }
  const project = await readJson(path.resolve(request.projectPath));
  const projectDir = path.resolve(request.projectDir);
  const workDir = path.resolve(request.workDir);
  const outputPath = path.resolve(request.outputPath);
  const tool = await artifactTool();
  const presentation = tool.Presentation.create({
    slideSize: { width: project.width, height: project.height },
  });
  const slides = [];
  const shellPaths = [];
  const referencePaths = [];
  const htmlRenderDir = path.join(workDir, "html-renders");
  for (let index = 0; index < project.slides.length; index += 1) {
    const plan = project.slides[index];
    const slide = presentation.slides.add();
    slide.background.fill = plan.background;
    if (plan.visual_shell) {
      const number = String(index + 1).padStart(3, "0");
      const shellPath = path.join(htmlRenderDir, `slide-${number}-shell.png`);
      const htmlPath = path.resolve(projectDir, plan.visual_shell.html_path);
      await renderHtmlShell({
        chromiumPath: request.chromiumPath,
        htmlPath,
        outputPath: shellPath,
        profilePath: path.join(htmlRenderDir, `profile-${number}-shell`),
        width: project.width,
        height: project.height,
        scale: plan.visual_shell.render_scale,
      });
      const shellBytes = await fs.readFile(shellPath);
      slide.images.add({
        blob: shellBytes,
        contentType: "image/png",
        alt: plan.visual_shell.alt,
        fit: "cover",
        position: { left: 0, top: 0, width: project.width, height: project.height },
        geometry: "rect",
      });
      shellPaths.push(shellPath);
      if (plan.visual_shell.reference_html_path) {
        const referencePath = path.join(htmlRenderDir, `slide-${number}-reference.png`);
        await renderHtmlShell({
          chromiumPath: request.chromiumPath,
          htmlPath: path.resolve(projectDir, plan.visual_shell.reference_html_path),
          outputPath: referencePath,
          profilePath: path.join(htmlRenderDir, `profile-${number}-reference`),
          width: project.width,
          height: project.height,
          scale: plan.visual_shell.render_scale,
        });
        referencePaths.push(referencePath);
      } else {
        referencePaths.push(shellPath);
      }
    } else {
      shellPaths.push(null);
      referencePaths.push(null);
    }
    for (const element of plan.elements) await addElement(slide, element, projectDir);
    if (plan.speaker_notes) {
      slide.speakerNotes.textFrame.setText(plan.speaker_notes);
      slide.speakerNotes.setVisible(true);
    }
    slides.push(slide);
  }

  const inspection = await presentation.inspect({
    kind: "slide,textbox,shape,image,table,chart,notes", maxChars: 1000000,
  });
  if (inspection.truncated) fail("Native PPTX inspection was truncated");
  const records = parseNdjson(inspection.ndjson);
  const issues = [];
  for (const record of records) {
    const text = String(record.text ?? record.textPreview ?? "").trim();
    if (text && PLACEHOLDERS.some((pattern) => pattern.test(text))) {
      issues.push({
        severity: "error", code: "unresolved-placeholder",
        message: `Slide ${record.slide} contains unresolved placeholder text: ${text}`,
        slide: record.slide, targetId: record.id,
      });
    }
  }

  const previewDir = path.join(workDir, "previews");
  const layoutDir = path.join(workDir, "layouts");
  await fs.mkdir(previewDir, { recursive: true });
  await fs.mkdir(layoutDir, { recursive: true });
  const previewPaths = [];
  const layoutPaths = [];
  for (let index = 0; index < slides.length; index += 1) {
    const number = String(index + 1).padStart(3, "0");
    const previewPath = path.join(previewDir, `slide-${number}.png`);
    const layoutPath = path.join(layoutDir, `slide-${number}.layout.json`);
    await saveBlob(await presentation.export({ slide: slides[index], format: "png", scale: 1 }), previewPath);
    await saveBlob(await slides[index].export({ format: "layout" }), layoutPath);
    previewPaths.push(previewPath);
    layoutPaths.push(layoutPath);
  }

  const manifestPath = path.join(workDir, "native-pptx-manifest.json");
  await writeJson(manifestPath, {
    schemaVersion: 2, projectPath: path.resolve(request.sourceProjectPath),
    qualityProfile: project.quality_profile,
    slideCount: slides.length, records, previewPaths, layoutPaths, shellPaths, referencePaths,
  });
  if (!issues.some((issue) => issue.severity === "error")) {
    await saveBlob(await tool.PresentationFile.exportPptx(presentation), outputPath);
    const stat = await fs.stat(outputPath);
    if (!stat.isFile() || stat.size === 0) fail(`Exported PPTX is empty: ${outputPath}`);
  }
  const powerPointObjectCount = records.filter((record) =>
    ["textbox", "shape", "image", "table", "chart"].includes(record.kind)
  ).length;
  const semanticEditableObjectCount = project.slides.reduce(
    (count, slide) => count + slide.elements.length,
    0,
  );
  process.stdout.write(JSON.stringify({
    outputPath: issues.some((issue) => issue.severity === "error") ? null : outputPath,
    manifestPath, previewPaths, layoutPaths, shellPaths, referencePaths, issues,
    slideCount: slides.length,
    powerPointObjectCount,
    editableObjectCount: semanticEditableObjectCount,
    semanticEditableObjectCount,
    qualityProfile: project.quality_profile,
    engine: "@oai/artifact-tool",
  }));
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message || String(error)}\n`);
  process.exit(1);
});
