#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const INSPECT_KINDS = "slide,textbox,shape,image,table,chart";
const PLACEHOLDER_PATTERNS = [
  /^click to add (title|subtitle|text)$/i,
  /^(title|subtitle|name|text|body) goes here$/i,
  /^lorem ipsum\b/i,
  /\btemplate instruction\b/i,
];

function fail(message) {
  throw new Error(message);
}

async function readJson(filePath) {
  return JSON.parse(await fs.readFile(filePath, "utf8"));
}

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
  if (blob instanceof Uint8Array || Buffer.isBuffer(blob)) {
    await fs.writeFile(outputPath, Buffer.from(blob));
    return;
  }
  fail(`Expected binary artifact for ${outputPath}`);
}

async function sha256(filePath) {
  const bytes = await fs.readFile(filePath);
  return crypto.createHash("sha256").update(bytes).digest("hex");
}

function parseNdjson(text) {
  return String(text || "")
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

function slidesFromPresentation(presentation) {
  if (Array.isArray(presentation.slides?.items)) return presentation.slides.items;
  if (Number.isInteger(presentation.slides?.count) && typeof presentation.slides.getItem === "function") {
    return Array.from({ length: presentation.slides.count }, (_, index) => presentation.slides.getItem(index));
  }
  fail("Could not enumerate imported presentation slides.");
}

function withOrdinals(records) {
  const counters = new Map();
  return records.map((record) => {
    const slide = Number(record.slide || 0);
    const kind = String(record.kind || "");
    const key = `${slide}:${kind}`;
    const ordinal = counters.get(key) || 0;
    counters.set(key, ordinal + 1);
    return { ...record, kindOrdinal: ordinal };
  });
}

async function inspectAll(presentation) {
  const slideIndex = await presentation.inspect({ kind: "slide", maxChars: 200000 });
  const slideRecords = parseNdjson(slideIndex.ndjson).filter((record) => record.kind === "slide");
  if (slideRecords.length === 0) fail("artifact-tool inspect returned no slides.");

  const records = [];
  let truncated = Boolean(slideIndex.truncated);
  for (const slideRecord of slideRecords) {
    const focused = await presentation.inspect({
      target: { id: slideRecord.id, beforeLines: 0, afterLines: 10000 },
      kind: INSPECT_KINDS,
      maxChars: 1000000,
    });
    truncated = truncated || Boolean(focused.truncated);
    const focusedRecords = parseNdjson(focused.ndjson).filter(
      (record) => Number(record.slide) === Number(slideRecord.slide),
    );
    records.push(...focusedRecords);
  }
  const unique = new Map();
  for (const record of records) {
    if (record.id) unique.set(record.id, record);
  }
  return { records: withOrdinals([...unique.values()]), truncated };
}

async function importArtifactTool() {
  const entrypoint = process.env.EVOFLUX_ARTIFACT_TOOL_ENTRYPOINT;
  if (!entrypoint) fail("Missing EVOFLUX_ARTIFACT_TOOL_ENTRYPOINT.");
  return import(pathToFileURL(path.resolve(entrypoint)).href);
}

function sourceRecordMap(manifest) {
  return new Map(manifest.records.map((record) => [record.id, record]));
}

function destinationRecordMap(records) {
  return new Map(
    records.map((record) => [`${record.slide}:${record.kind}:${record.kindOrdinal}`, record]),
  );
}

function targetForEdit(presentation, edit, sourceRecord, outputSlide, destinationRecords) {
  const key = `${outputSlide}:${sourceRecord.kind}:${sourceRecord.kindOrdinal}`;
  const destinationRecord = destinationRecords.get(key);
  if (!destinationRecord) {
    fail(
      `Could not map source target ${edit.target_id} (${sourceRecord.kind} #${sourceRecord.kindOrdinal}) ` +
        `onto output slide ${outputSlide}.`,
    );
  }
  if (sourceRecord.name && destinationRecord.name && sourceRecord.name !== destinationRecord.name) {
    fail(
      `Mapped target name changed for ${edit.target_id}: ` +
        `${JSON.stringify(sourceRecord.name)} -> ${JSON.stringify(destinationRecord.name)}.`,
    );
  }
  return presentation.resolve(destinationRecord.id);
}

async function applyEdit(target, edit, projectDir) {
  if (edit.operation === "set_text") {
    target.text = edit.text;
    return;
  }
  if (edit.operation === "replace_text") {
    const current = String(target.text?.text ?? target.text ?? "");
    if (!current.includes(edit.find)) {
      fail(`Text target ${edit.target_id} does not contain ${JSON.stringify(edit.find)}.`);
    }
    target.text.replace(edit.find, edit.replace);
    return;
  }
  if (edit.operation === "replace_image") {
    const assetPath = path.isAbsolute(edit.asset_path)
      ? path.resolve(edit.asset_path)
      : path.resolve(projectDir, edit.asset_path);
    const stat = await fs.stat(assetPath).catch(() => undefined);
    if (!stat?.isFile()) fail(`Replacement image does not exist: ${assetPath}`);
    const preserved = {
      frame: target.frame,
      crop: target.crop,
      fit: target.fit,
      geometry: target.geometry,
      borderRadius: target.borderRadius,
      rotation: target.rotation,
      flipHorizontal: target.flipHorizontal,
      flipVertical: target.flipVertical,
      lockAspectRatio: target.lockAspectRatio,
    };
    target.replace({ path: assetPath, ...(edit.alt ? { alt: edit.alt } : {}) });
    for (const [key, value] of Object.entries(preserved)) {
      if (value !== undefined) target[key] = value;
    }
    return;
  }
  if (edit.operation === "set_table_cell") {
    target.setCellValue(edit.row, edit.column, edit.text);
    return;
  }
  if (edit.operation === "set_chart_series") {
    target.series.getItemAt(edit.series_index).values = edit.values;
    return;
  }
  fail(`Unsupported edit operation: ${edit.operation}`);
}

function placeholderIssues(records) {
  const issues = [];
  for (const record of records) {
    const text = String(record.text ?? record.textPreview ?? "").trim();
    if (text && PLACEHOLDER_PATTERNS.some((pattern) => pattern.test(text))) {
      issues.push({
        severity: "error",
        code: "unresolved-placeholder",
        message: `Output slide ${record.slide} still contains placeholder text: ${text}`,
        slide: record.slide,
        targetId: record.id,
      });
    }
  }
  return issues;
}

async function renderPresentation(presentation, slides, workDir, prefix) {
  const previewDir = path.join(workDir, "previews");
  const layoutDir = path.join(workDir, "layouts");
  await fs.mkdir(previewDir, { recursive: true });
  await fs.mkdir(layoutDir, { recursive: true });
  const previewPaths = [];
  const layoutPaths = [];
  const layouts = [];
  for (let index = 0; index < slides.length; index += 1) {
    const padded = String(index + 1).padStart(2, "0");
    const previewPath = path.join(previewDir, `${prefix}-${padded}.png`);
    const layoutPath = path.join(layoutDir, `${prefix}-${padded}.layout.json`);
    await saveBlob(await presentation.export({ slide: slides[index], format: "png", scale: 1 }), previewPath);
    await saveBlob(await presentation.export({ slide: slides[index], format: "layout" }), layoutPath);
    previewPaths.push(previewPath);
    layoutPaths.push(layoutPath);
    layouts.push(await readJson(layoutPath));
  }
  return { previewPaths, layoutPaths, layouts };
}

async function inspectTemplate(request, artifactTool) {
  const sourcePath = path.resolve(request.sourcePath);
  const workDir = path.resolve(request.workDir);
  await fs.mkdir(workDir, { recursive: true });
  const { FileBlob, PresentationFile } = artifactTool;
  const presentation = await PresentationFile.importPptx(await FileBlob.load(sourcePath));
  const slides = slidesFromPresentation(presentation);
  const inspection = await inspectAll(presentation);
  if (inspection.truncated) fail("Template inspection was truncated; the source deck is too complex to edit safely.");
  const rendered = await renderPresentation(presentation, slides, workDir, "source-slide");
  const sourceSha256 = await sha256(sourcePath);
  const slideArtifacts = rendered.layouts.map((layout, index) => ({
    slide: index + 1,
    previewPath: rendered.previewPaths[index],
    layoutPath: rendered.layoutPaths[index],
    layoutId: layout.slide?.layoutId,
    layoutName: layout.slide?.layoutName,
    layoutType: layout.slide?.layoutType,
    masterLayoutId: layout.slide?.masterLayoutId,
  }));
  const manifestPath = path.join(workDir, "template-manifest.json");
  const manifest = {
    schemaVersion: 1,
    sourcePath,
    sourceSha256,
    generatedAt: new Date().toISOString(),
    slideCount: slides.length,
    slideArtifacts,
    records: inspection.records,
  };
  await writeJson(manifestPath, manifest);
  await fs.writeFile(
    path.join(workDir, "template-inspect.ndjson"),
    `${inspection.records.map((record) => JSON.stringify(record)).join("\n")}\n`,
    "utf8",
  );
  return {
    manifestPath,
    sourceSha256,
    slideCount: slides.length,
    previewPaths: rendered.previewPaths,
    layoutPaths: rendered.layoutPaths,
    issues: [],
    objectCounts: inspection.records.reduce((counts, record) => {
      counts[record.kind] = (counts[record.kind] || 0) + 1;
      return counts;
    }, {}),
  };
}

async function buildTemplate(request, artifactTool, action) {
  const sourcePath = path.resolve(request.sourcePath);
  const projectPath = path.resolve(request.projectPath);
  const manifestPath = path.resolve(request.manifestPath);
  const workDir = path.resolve(request.workDir);
  const project = await readJson(projectPath);
  const manifest = await readJson(manifestPath);
  const actualHash = await sha256(sourcePath);
  if (actualHash !== project.source_sha256 || actualHash !== manifest.sourceSha256) {
    fail("Source PPTX hash differs from the inspected template.");
  }

  const { FileBlob, PresentationFile } = artifactTool;
  const presentation = await PresentationFile.importPptx(await FileBlob.load(sourcePath));
  const originals = [...slidesFromPresentation(presentation)];
  const outputEntries = [...project.output_slides].sort((a, b) => a.output_slide - b.output_slide);
  const outputSlides = outputEntries.map((entry) => originals[entry.source_slide - 1].duplicate());
  for (const slide of originals) slide.delete();
  outputSlides.forEach((slide, index) => slide.moveTo(index));

  const duplicatedInspection = await inspectAll(presentation);
  if (duplicatedInspection.truncated) fail("Duplicated-deck inspection was truncated; refusing unsafe edits.");
  const sourceRecords = sourceRecordMap(manifest);
  const destinationRecords = destinationRecordMap(duplicatedInspection.records);
  const projectDir = path.dirname(projectPath);

  for (const entry of outputEntries) {
    for (const edit of entry.edits) {
      const sourceRecord = sourceRecords.get(edit.target_id);
      if (!sourceRecord) fail(`Unknown source edit target: ${edit.target_id}`);
      if (Number(sourceRecord.slide) !== Number(entry.source_slide)) {
        fail(`Edit target ${edit.target_id} does not belong to source slide ${entry.source_slide}.`);
      }
      const target = targetForEdit(
        presentation,
        edit,
        sourceRecord,
        entry.output_slide,
        destinationRecords,
      );
      await applyEdit(target, edit, projectDir);
    }
    if (entry.speaker_notes !== null && entry.speaker_notes !== undefined) {
      outputSlides[entry.output_slide - 1].speakerNotes.textFrame.setText(entry.speaker_notes);
      outputSlides[entry.output_slide - 1].speakerNotes.setVisible(true);
    }
  }

  const finalInspection = await inspectAll(presentation);
  if (finalInspection.truncated) fail("Final deck inspection was truncated; refusing export.");
  const rendered = await renderPresentation(presentation, outputSlides, workDir, "output-slide");
  const issues = placeholderIssues(finalInspection.records);
  const sourceArtifactMap = new Map(manifest.slideArtifacts.map((item) => [Number(item.slide), item]));
  rendered.layouts.forEach((layout, index) => {
    const entry = outputEntries[index];
    const source = sourceArtifactMap.get(Number(entry.source_slide));
    const actual = layout.slide || {};
    if (source?.layoutId !== actual.layoutId || source?.masterLayoutId !== actual.masterLayoutId) {
      issues.push({
        severity: "error",
        code: "template-lineage-changed",
        message: `Output slide ${index + 1} no longer inherits source slide ${entry.source_slide}'s master/layout.`,
        slide: index + 1,
      });
    }
  });

  let outputPath;
  if (action === "compose") {
    outputPath = path.resolve(request.outputPath);
  } else {
    outputPath = path.join(workDir, "template-preview.pptx");
  }
  if (!issues.some((issue) => issue.severity === "error")) {
    await fs.mkdir(path.dirname(outputPath), { recursive: true });
    await (await PresentationFile.exportPptx(presentation)).save(outputPath);
    const stat = await fs.stat(outputPath);
    if (!stat.isFile() || stat.size === 0) fail(`Exported PPTX is empty: ${outputPath}`);
  }

  const qaPath = path.join(workDir, "qa.json");
  await writeJson(qaPath, {
    status: issues.some((issue) => issue.severity === "error") ? "fail" : "pass",
    sourcePath,
    sourceSha256: actualHash,
    outputPath: issues.some((issue) => issue.severity === "error") ? null : outputPath,
    slideCount: outputSlides.length,
    issues,
  });
  return {
    manifestPath,
    outputPath: issues.some((issue) => issue.severity === "error") ? null : outputPath,
    previewDeckPath: action === "render" ? outputPath : undefined,
    qaPath,
    slideCount: outputSlides.length,
    previewPaths: rendered.previewPaths,
    layoutPaths: rendered.layoutPaths,
    issues,
    sourceSha256: actualHash,
    editCount: outputEntries.reduce((count, entry) => count + entry.edits.length, 0),
    preserveOnlySlideCount: outputEntries.filter((entry) => entry.edits.length === 0).length,
  };
}

async function main() {
  const [action, requestPath] = process.argv.slice(2);
  if (!["inspect", "render", "compose"].includes(action) || !requestPath) {
    fail("Usage: node pptx_template_worker.mjs <inspect|render|compose> <request.json>");
  }
  const request = await readJson(path.resolve(requestPath));
  const artifactTool = await importArtifactTool();
  const result = action === "inspect"
    ? await inspectTemplate(request, artifactTool)
    : await buildTemplate(request, artifactTool, action);
  process.stdout.write(JSON.stringify(result));
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message || String(error)}\n`);
  process.exit(1);
});
