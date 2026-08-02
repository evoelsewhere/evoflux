#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const FORMULA_ERRORS = "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!";

function fail(message) { throw new Error(message); }
async function readJson(filePath) { return JSON.parse(await fs.readFile(filePath, "utf8")); }
async function writeJson(filePath, value) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}
async function saveBlob(blob, outputPath) {
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.writeFile(outputPath, Buffer.from(await blob.arrayBuffer()));
}
async function artifactTool() {
  const entrypoint = process.env.EVOFLUX_ARTIFACT_TOOL_ENTRYPOINT;
  if (!entrypoint) fail("Missing EVOFLUX_ARTIFACT_TOOL_ENTRYPOINT");
  return import(pathToFileURL(path.resolve(entrypoint)).href);
}
function parseNdjson(value) {
  return String(value || "").split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
}
async function sha256(filePath) {
  const bytes = await fs.readFile(filePath);
  return crypto.createHash("sha256").update(bytes).digest("hex");
}
function sheetNamesFromInspect(inspectResult) {
  return parseNdjson(inspectResult.ndjson)
    .filter((item) => item.kind === "sheet" && item.name)
    .map((item) => String(item.name));
}
async function loadWorkbook(tool, sourcePath) {
  if (sourcePath) {
    const input = await tool.FileBlob.load(sourcePath);
    return tool.SpreadsheetFile.importXlsx(input);
  }
  return tool.Workbook.create();
}
function normalizeFormat(input) {
  const format = {};
  if (input.fill !== undefined) format.fill = input.fill;
  if (input.font !== undefined) format.font = input.font;
  if (input.borders !== undefined) format.borders = input.borders;
  if (input.number_format !== undefined) format.numberFormat = input.number_format;
  if (input.horizontal_alignment !== undefined) format.horizontalAlignment = input.horizontal_alignment;
  if (input.vertical_alignment !== undefined) format.verticalAlignment = input.vertical_alignment;
  if (input.wrap_text !== undefined) format.wrapText = input.wrap_text;
  return format;
}
function applyFormat(range, input) {
  range.format = normalizeFormat(input);
  if (input.column_width !== undefined) range.format.columnWidth = input.column_width;
  if (input.row_height !== undefined) range.format.rowHeight = input.row_height;
}
function assertMatrix(matrix, label) {
  if (!Array.isArray(matrix) || matrix.length === 0 || matrix.some((row) => !Array.isArray(row))) {
    fail(`${label} must be a non-empty two-dimensional matrix`);
  }
  const width = matrix[0].length;
  if (width === 0 || matrix.some((row) => row.length !== width)) fail(`${label} rows must have equal width`);
}
async function applyOperation(sheet, op) {
  if (op.operation === "write_range") {
    const range = sheet.getRange(op.range);
    if (op.values) { assertMatrix(op.values, "values"); range.values = op.values; }
    if (op.formulas) { assertMatrix(op.formulas, "formulas"); range.formulas = op.formulas; }
    if (op.dates) {
      assertMatrix(op.dates, "dates");
      range.values = op.dates.map((row) => row.map((item) => item === null ? null : new Date(item)));
    }
    if (op.format) applyFormat(range, op.format);
    return;
  }
  if (op.operation === "style_range") { applyFormat(sheet.getRange(op.range), op.format); return; }
  if (op.operation === "merge") { sheet.getRange(op.range).merge(); return; }
  if (op.operation === "unmerge") { sheet.getRange(op.range).unmerge(); return; }
  if (op.operation === "clear") { sheet.getRange(op.range).clear({ applyTo: op.apply_to }); return; }
  if (op.operation === "freeze_panes") {
    sheet.freezePanes.unfreeze();
    if (op.rows) sheet.freezePanes.freezeRows(op.rows);
    if (op.columns) sheet.freezePanes.freezeColumns(op.columns);
    return;
  }
  if (op.operation === "data_validation") {
    sheet.getRange(op.range).dataValidation = { rule: { type: "list", values: op.values } };
    return;
  }
  if (op.operation === "conditional_format") {
    sheet.getRange(op.range).conditionalFormats.add(op.rule_type, op.config);
    return;
  }
  if (op.operation === "add_table") {
    const table = sheet.tables.add(op.range, op.has_headers, op.name);
    if (op.style) table.style = op.style;
    return;
  }
  if (op.operation === "add_chart") {
    const chart = sheet.charts.add(op.chart_type, sheet.getRange(op.source_range));
    chart.title = op.title;
    chart.hasLegend = op.has_legend;
    if (op.y_number_format) chart.yAxis = { numberFormatCode: op.y_number_format };
    chart.setPosition(op.start_cell, op.end_cell);
    return;
  }
  if (op.operation === "delete_drawings") { sheet.deleteAllDrawings(); return; }
  fail(`Unsupported workbook operation: ${op.operation}`);
}
async function applyProject(workbook, project) {
  const before = await workbook.inspect({ kind: "sheet", include: "id,name", maxChars: 100000 });
  const existing = new Set(sheetNamesFromInspect(before));
  if (project.mode === "new" && existing.size !== 0) fail("New workbook unexpectedly contains worksheets");
  for (const plan of project.sheets) {
    let sheet;
    if (existing.has(plan.name)) sheet = workbook.worksheets.getItem(plan.name);
    else if (project.mode === "new" || plan.create_if_missing) {
      sheet = workbook.worksheets.add(plan.name);
      existing.add(plan.name);
    } else fail(`Worksheet does not exist in template: ${plan.name}`);
    if (plan.show_grid_lines !== null && plan.show_grid_lines !== undefined) sheet.showGridLines = plan.show_grid_lines;
    for (const operation of plan.operations) await applyOperation(sheet, operation);
  }
}
async function inspectWorkbook(workbook, sourcePath, workDir, sourceSha256) {
  const summary = await workbook.inspect({
    kind: "workbook,sheet,table,drawing", maxChars: 120000,
    tableMaxRows: 10, tableMaxCols: 12, tableMaxCellChars: 120,
  });
  const sheetIndex = await workbook.inspect({ kind: "sheet", include: "id,name", maxChars: 100000 });
  const names = sheetNamesFromInspect(sheetIndex);
  const previewPaths = [];
  const sheets = [];
  for (let index = 0; index < names.length; index += 1) {
    const name = names[index];
    const region = await workbook.inspect({ kind: "region,formula,computedStyle", sheetId: name, maxChars: 50000, tableMaxRows: 20, tableMaxCols: 20 });
    sheets.push({ name, inspect: parseNdjson(region.ndjson), truncated: Boolean(region.truncated) });
    const preview = await workbook.render({ sheetName: name, autoCrop: "all", scale: 1.5, format: "png" });
    const previewPath = path.join(workDir, "previews", `sheet-${String(index + 1).padStart(2, "0")}.png`);
    await saveBlob(preview, previewPath);
    previewPaths.push(previewPath);
  }
  const manifestPath = path.join(workDir, "workbook-manifest.json");
  await writeJson(manifestPath, {
    schemaVersion: 1, sourcePath, sourceSha256,
    sheetCount: names.length, sheetNames: names,
    summary: parseNdjson(summary.ndjson), sheets,
  });
  return { manifestPath, previewPaths, sheetCount: names.length, sheetNames: names, issues: [] };
}
async function verifyWorkbook(workbook, workDir) {
  const errors = await workbook.inspect({
    kind: "match", searchTerm: FORMULA_ERRORS,
    options: { useRegex: true, maxResults: 300 }, summary: "final formula error scan", maxChars: 50000,
  });
  const errorRecords = parseNdjson(errors.ndjson).filter(
    (record) => record.kind !== "notice" && record.kind !== "summary",
  );
  const issues = errorRecords.map((record) => ({ severity: "error", code: "formula-error", detail: record }));
  const sheetIndex = await workbook.inspect({ kind: "sheet", include: "id,name", maxChars: 100000 });
  const names = sheetNamesFromInspect(sheetIndex);
  const previewPaths = [];
  for (let index = 0; index < names.length; index += 1) {
    const preview = await workbook.render({ sheetName: names[index], autoCrop: "all", scale: 1.5, format: "png" });
    const previewPath = path.join(workDir, "previews", `sheet-${String(index + 1).padStart(2, "0")}.png`);
    await saveBlob(preview, previewPath);
    previewPaths.push(previewPath);
  }
  if (names.length === 0) issues.push({ severity: "error", code: "empty-workbook", message: "Workbook has no worksheets" });
  return { issues, previewPaths, sheetNames: names, sheetCount: names.length };
}

async function main() {
  const [action, requestPath] = process.argv.slice(2);
  if (!["inspect", "render", "compose"].includes(action) || !requestPath) fail("Usage: xlsx_artifact_worker.mjs <inspect|render|compose> <request.json>");
  const request = await readJson(requestPath);
  const tool = await artifactTool();
  const workbook = await loadWorkbook(tool, request.sourcePath || null);
  if (action === "inspect") {
    return inspectWorkbook(workbook, request.sourcePath, request.workDir, request.sourceSha256 || await sha256(request.sourcePath));
  }
  const project = await readJson(request.projectPath);
  if (project.mode === "template") {
    const actual = await sha256(request.sourcePath);
    if (actual !== project.source_sha256) fail("Source XLSX hash does not match project lineage");
  }
  await applyProject(workbook, project);
  const qa = await verifyWorkbook(workbook, request.workDir);
  let outputPath = null;
  if (action === "compose" && qa.issues.every((issue) => issue.severity !== "error")) {
    outputPath = path.resolve(request.outputPath);
    await fs.mkdir(path.dirname(outputPath), { recursive: true });
    const blob = await tool.SpreadsheetFile.exportXlsx(workbook);
    await blob.save(outputPath);
  }
  return { ...qa, outputPath };
}

main().then((value) => process.stdout.write(`${JSON.stringify(value)}\n`)).catch((error) => {
  process.stderr.write(`${error?.stack || error}\n`);
  process.exitCode = 1;
});
