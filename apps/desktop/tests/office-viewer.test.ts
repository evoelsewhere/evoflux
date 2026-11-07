// Unit tests for the Files tool's Office viewer helpers
// (docs/features/office-v3-parity/spec.md FR-5, FR-9). Run with `bun test` in apps/desktop.

import { describe, expect, test } from "bun:test";
import { NATIVE_OFFICE_FILE, officeKind } from "../src/features/files/office/kinds";
import { adjacentCellName } from "../src/features/files/office/search";
import { emitOfficeFileChanged, onOfficeFileChanged, type OfficeFileChange } from "../src/stores/office-events";

describe("adjacentCellName (v3 workbook arrows)", () => {
  test("moves one cell in each direction", () => {
    expect(adjacentCellName("B3", "ArrowLeft")).toBe("A3");
    expect(adjacentCellName("B3", "ArrowRight")).toBe("C3");
    expect(adjacentCellName("B3", "ArrowUp")).toBe("B2");
    expect(adjacentCellName("B3", "ArrowDown")).toBe("B4");
  });

  test("carries across multi-letter columns", () => {
    expect(adjacentCellName("Z1", "ArrowRight")).toBe("AA1");
    expect(adjacentCellName("AA1", "ArrowLeft")).toBe("Z1");
    expect(adjacentCellName("AZ9", "ArrowRight")).toBe("BA9");
  });

  test("stops at the sheet's edge and ignores other keys or names", () => {
    expect(adjacentCellName("A1", "ArrowLeft")).toBeNull();
    expect(adjacentCellName("A1", "ArrowUp")).toBeNull();
    expect(adjacentCellName("A1", "Enter")).toBeNull();
    expect(adjacentCellName("a1", "ArrowRight")).toBeNull();
    expect(adjacentCellName("A0", "ArrowRight")).toBeNull();
  });
});

describe("officeKind", () => {
  test("Word, Excel and PowerPoint go to the native viewer, whatever the case", () => {
    expect(officeKind("C:\\work\\Deck.PPTX")).toBe("pptx");
    expect(officeKind("/tmp/report.docx")).toBe("docx");
    expect(officeKind("book.xlsx")).toBe("xlsx");
    expect(NATIVE_OFFICE_FILE.test("book.xlsx")).toBe(true);
  });

  test("legacy, OpenDocument and PDF files keep the pdf.js pages", () => {
    for (const path of ["old.doc", "old.ppt", "old.xls", "a.odt", "a.odp", "a.ods", "a.pdf", "a.docx.txt"]) {
      expect(officeKind(path)).toBeNull();
    }
  });
});

describe("office_file_changed routing", () => {
  test("valid changes reach every listener; malformed ones are dropped", () => {
    const seen: Array<[string, OfficeFileChange[]]> = [];
    const off = onOfficeFileChanged((chat, changes) => seen.push([chat, changes]));
    try {
      emitOfficeFileChanged("chat-1", [
        { kind: "added", path: "out/deck.pptx" },
        { kind: "renamed", path: "x.pptx" },
        { kind: "modified" },
        null,
        { kind: "deleted", path: "old.xlsx" },
      ]);
      emitOfficeFileChanged("chat-2", "not a list");
      emitOfficeFileChanged("chat-3", [{ kind: "added", path: "" }]);
    } finally {
      off();
    }
    expect(seen).toEqual([
      [
        "chat-1",
        [
          { kind: "added", path: "out/deck.pptx" },
          { kind: "deleted", path: "old.xlsx" },
        ],
      ],
    ]);
  });

  test("a failing listener does not stop the others, and unsubscribing works", () => {
    let calls = 0;
    const offBad = onOfficeFileChanged(() => {
      throw new Error("boom");
    });
    const offGood = onOfficeFileChanged(() => {
      calls += 1;
    });
    const warn = console.warn;
    console.warn = () => undefined;
    try {
      emitOfficeFileChanged("chat", [{ kind: "modified", path: "a.docx" }]);
      offGood();
      emitOfficeFileChanged("chat", [{ kind: "modified", path: "a.docx" }]);
    } finally {
      console.warn = warn;
      offBad();
    }
    expect(calls).toBe(1);
  });
});
