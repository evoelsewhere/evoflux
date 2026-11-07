// Area edits: the annotation message block, its parser, the batch store and
// the annotator's geometry (docs/features/office-v3-parity/sdd.md, FR-10;
// ported from v3 web/src/__tests__/components/InputBarAnnotations.test.tsx).
// Run with `bun test` in apps/desktop.

import { beforeEach, describe, expect, test } from "bun:test";
import {
  areaOf,
  cellRange,
  clampArea,
  cleanText,
  columnName,
  composeAnnotatedMessage,
  describeAnnotation,
  overlapShare,
  parseAnnotatedMessage,
  parseCell,
  workspacePath,
  type DocumentAnnotation,
} from "../src/lib/document-annotations";
import { MAX_BATCH_ANNOTATIONS, useAnnotationsStore } from "../src/stores/annotations-store";

const chart: DocumentAnnotation = {
  id: "a1",
  file: "deck.pptx",
  slide: 7,
  shapes: [{ id: 12, name: "Chart 3" }],
  area: { x: 10.04, y: 20, w: 50, h: 40 },
  text: "Quarterly P&L",
  instruction: "Keep the colors in a unified tone.",
  label: "Slide 7 · Chart 3",
};

beforeEach(() => {
  useAnnotationsStore.setState({ pending: {}, submitRequest: null });
});

describe("document annotation messages", () => {
  test("round-trips the annotation block and activates the skill", () => {
    const message = composeAnnotatedMessage("Also check the legend.", [chart]);

    expect(message.startsWith("/skill:office-annotation-edit Also check the legend.\n\n<evo-annotations>\n")).toBe(true);
    expect(message.endsWith("\n</evo-annotations>")).toBe(true);
    expect(parseAnnotatedMessage(message)).toEqual({
      text: "Also check the legend.",
      annotations: [
        {
          n: 1,
          file: "deck.pptx",
          slide: 7,
          shapes: [{ id: 12, name: "Chart 3" }],
          text: "Quarterly P&L",
          instruction: "Keep the colors in a unified tone.",
        },
      ],
    });
    expect(parseAnnotatedMessage("plain text")).toBeNull();
    // CRLF line breaks still parse.
    expect(parseAnnotatedMessage(message.replace(/\n/g, "\r\n"))?.annotations).toHaveLength(1);
  });

  test("writes compact JSON with the v3 keys and 0.1 rounding", () => {
    const message = composeAnnotatedMessage("", [chart]);
    const json = message.split("\n")[1];
    expect(json).toBe(
      '[{"n":1,"file":"deck.pptx","slide":7,"shapes":[{"id":12,"name":"Chart 3"}],"area":{"x":10,"y":20,"w":50,"h":40},"text":"Quarterly P&L","instruction":"Keep the colors in a unified tone."}]',
    );
    expect(message.startsWith("/skill:office-annotation-edit <evo-annotations>\n")).toBe(true);
    expect(composeAnnotatedMessage("hi", [])).toBe("hi");
    const long = composeAnnotatedMessage("", [{ ...chart, text: "x".repeat(400) }]);
    expect(JSON.parse(long.split("\n")[1])[0].text).toHaveLength(300);
  });

  test("still reads v3 messages", () => {
    const legacy =
      'Fix it\n\n$office-annotation-edit\n<evoflux-annotations>\n[{"n":1,"file":"deck.pptx","slide":7,"shapes":[],"area":{"x":0,"y":0,"w":1,"h":1},"text":"","instruction":""}]\n</evoflux-annotations>';
    expect(parseAnnotatedMessage(legacy)?.text).toBe("Fix it");
    // A replayed skill command shows as `/name args`.
    const replayed = composeAnnotatedMessage("Fix it", [chart]).replace("/skill:", "/");
    expect(parseAnnotatedMessage(replayed)?.text).toBe("Fix it");
    const v3 = composeAnnotatedMessage("Fix it", [chart]).replace(/evo-annotations/g, "evoflux-annotations");
    expect(parseAnnotatedMessage(v3)?.annotations[0].slide).toBe(7);
    expect(parseAnnotatedMessage(v3)?.text).toBe("Fix it");
    // Mixed tags are not a block.
    const mixed = v3.replace("</evoflux-annotations>", "</evo-annotations>");
    expect(parseAnnotatedMessage(mixed)).toBeNull();
  });

  test("carries a workbook annotation's sheet and range", () => {
    const cells: DocumentAnnotation = {
      ...chart,
      file: "model.xlsx",
      slide: 2,
      sheet: "Model",
      range: "B3:D8",
      shapes: [],
      label: "Model · B3:D8",
    };

    const parsed = parseAnnotatedMessage(composeAnnotatedMessage("", [cells]));

    expect(parsed?.annotations[0]).toMatchObject({ file: "model.xlsx", slide: 2, sheet: "Model", range: "B3:D8" });
    expect(describeAnnotation(parsed!.annotations[0])).toBe("Model · B3:D8");
  });

  test("describes shapes, quoted text and bare areas", () => {
    expect(describeAnnotation(chart)).toBe("Slide 7 · Chart 3");
    expect(describeAnnotation({ slide: 2, shapes: [], text: "Revenue grew" })).toBe("Slide 2 · “Revenue grew”");
    expect(describeAnnotation({ slide: 2, shapes: [], text: "a".repeat(50) })).toBe(`Slide 2 · “${"a".repeat(40)}…”`);
    expect(describeAnnotation({ slide: 3, shapes: [] })).toBe("Slide 3 · Selected area");
    expect(describeAnnotation({ slide: 4, shapes: [], range: "A1" })).toBe("Sheet 4 · A1");
  });

  test("names files relative to the chat's folder", () => {
    expect(workspacePath("C:\\work\\deck\\out\\deck.pptx", "C:\\Work\\deck")).toBe("out/deck.pptx");
    expect(workspacePath("/home/me/proj/a.xlsx", "/home/me/proj/")).toBe("a.xlsx");
    expect(workspacePath("./slides/a.pptx", "/x")).toBe("slides/a.pptx");
    expect(workspacePath("D:/other/a.pptx", "C:/work")).toBe("D:/other/a.pptx");
    expect(workspacePath("/home/me/project2/a.pptx", "/home/me/project")).toBe("/home/me/project2/a.pptx");
  });
});

describe("annotation batch", () => {
  test("adds up to 20 per chat", () => {
    const store = useAnnotationsStore.getState();
    for (let i = 0; i < MAX_BATCH_ANNOTATIONS; i++) expect(store.add("c1", { ...chart, id: `a${i}` })).toBe(true);
    expect(store.add("c1", { ...chart, id: "extra" })).toBe(false);
    expect(store.add("c2", chart)).toBe(true);
    expect(useAnnotationsStore.getState().pending.c1).toHaveLength(20);
  });

  test("removes, clears and restores only into an empty batch", () => {
    const store = useAnnotationsStore.getState();
    store.add("c1", chart);
    store.add("c1", { ...chart, id: "a2" });
    store.remove("c1", "a1");
    expect(useAnnotationsStore.getState().pending.c1?.map((a) => a.id)).toEqual(["a2"]);
    store.remove("c1", "a2");
    expect(useAnnotationsStore.getState().pending.c1).toBeUndefined();

    store.restore("c1", [chart]);
    expect(useAnnotationsStore.getState().pending.c1).toHaveLength(1);
    store.restore("c1", [{ ...chart, id: "other" }]);
    expect(useAnnotationsStore.getState().pending.c1?.[0].id).toBe("a1");
    store.clear("c1");
    expect(useAnnotationsStore.getState().pending.c1).toBeUndefined();
  });

  test("submit requests count up per request", () => {
    const store = useAnnotationsStore.getState();
    store.requestSubmit("c1");
    store.requestSubmit("c1");
    expect(useAnnotationsStore.getState().submitRequest).toEqual({ chatId: "c1", nonce: 2 });
  });
});

describe("annotator geometry", () => {
  test("areas are percent of the surface, clamped inside it", () => {
    const surface = { left: 100, top: 50, width: 200, height: 100 };
    expect(areaOf({ left: 150, top: 75, width: 50, height: 25 }, surface)).toEqual({ x: 25, y: 25, w: 25, h: 25 });
    expect(areaOf({ left: 50, top: 0, width: 400, height: 400 }, surface)).toEqual({ x: 0, y: 0, w: 100, h: 100 });
    expect(clampArea({ x: 90, y: 95, w: 30, h: 30 })).toEqual({ x: 90, y: 95, w: 10, h: 5 });
  });

  test("overlap share is the part of the shape inside the drag", () => {
    const shape = { left: 0, top: 0, right: 10, bottom: 10, width: 10, height: 10 };
    expect(overlapShare(shape, { left: 0, top: 0, right: 10, bottom: 6 })).toBeCloseTo(0.6);
    expect(overlapShare(shape, { left: 20, top: 20, right: 30, bottom: 30 })).toBe(0);
  });

  test("cell names and A1 ranges", () => {
    expect(parseCell("B3")).toEqual({ column: 2, row: 3 });
    expect(parseCell("AA10")).toEqual({ column: 27, row: 10 });
    expect(parseCell("b3")).toBeNull();
    expect(columnName(1)).toBe("A");
    expect(columnName(26)).toBe("Z");
    expect(columnName(27)).toBe("AA");
    expect(columnName(703)).toBe("AAA");
    expect(cellRange("D8", "B3")?.name).toBe("B3:D8");
    expect(cellRange("C2", "C2")?.name).toBe("C2");
    expect(cellRange("x", "C2")).toBeNull();
  });

  test("text is collapsed and capped", () => {
    expect(cleanText("  a\n\n b  ")).toBe("a b");
    expect(cleanText("x".repeat(500))).toHaveLength(300);
    expect(cleanText(null)).toBe("");
  });
});
