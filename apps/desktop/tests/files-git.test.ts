// Unit tests for the Files tool's git helpers (docs/features/files-git/sdd.md).
// Run with `bun test` in apps/desktop.

import { describe, expect, test } from "bun:test";
import { diffLines, splitLines } from "../src/features/files/git-gutter";
import { buildDecorations, rowGit } from "../src/features/files/git-state";

const lines = (s: string) => splitLines(s);
/** A Windows path with backslashes, as the tree lists it. */
const win = (p: string) => p.replaceAll("/", String.fromCharCode(92));

describe("diffLines", () => {
  test("identical text has no hunks", () => {
    expect(diffLines(lines("a\nb\nc\n"), lines("a\nb\nc\n"))).toEqual([]);
  });

  test("added, modified and removed lines", () => {
    const base = lines("one\ntwo\nthree\nfour\nfive\n");
    const doc = lines("one\nTWO\nthree\nfive\nsix\n");
    expect(diffLines(base, doc)).toEqual([
      { baseFrom: 1, baseTo: 2, docFrom: 1, docTo: 2 }, // two → TWO
      { baseFrom: 3, baseTo: 4, docFrom: 3, docTo: 3 }, // four removed
      { baseFrom: 5, baseTo: 5, docFrom: 4, docTo: 5 }, // six added
    ]);
  });

  test("insertion at the top and deletion at the end", () => {
    expect(diffLines(lines("a\nb"), lines("x\na\nb"))).toEqual([{ baseFrom: 0, baseTo: 0, docFrom: 0, docTo: 1 }]);
    expect(diffLines(lines("a\nb\nc"), lines("a\nb"))).toEqual([{ baseFrom: 2, baseTo: 3, docFrom: 2, docTo: 2 }]);
  });

  test("CRLF against LF is unchanged", () => {
    expect(diffLines(lines("a\r\nb\r\n"), lines("a\nb\n"))).toEqual([]);
  });

  test("an empty base marks every line added", () => {
    expect(diffLines(lines(""), lines("a\nb"))).toEqual([{ baseFrom: 0, baseTo: 1, docFrom: 0, docTo: 2 }]);
  });

  test("interleaved edits keep unchanged lines out of hunks", () => {
    const base = lines("a\nb\nc\nd\ne\nf\ng");
    const doc = lines("a\nB\nc\nd\nE\nf\ng\nh");
    expect(diffLines(base, doc)).toEqual([
      { baseFrom: 1, baseTo: 2, docFrom: 1, docTo: 2 },
      { baseFrom: 4, baseTo: 5, docFrom: 4, docTo: 5 },
      { baseFrom: 7, baseTo: 7, docFrom: 7, docTo: 8 },
    ]);
  });

  test("random edits: lines outside hunks pair up one to one", () => {
    let seed = 7;
    const rand = (n: number) => ((seed = (seed * 1103515245 + 12345) % 2147483648), seed % n);
    for (let round = 0; round < 300; round++) {
      const base = Array.from({ length: rand(40) }, () => `l${rand(6)}`);
      const doc = [...base];
      for (let e = rand(8); e > 0; e--) {
        const at = rand(doc.length + 1);
        const op = rand(3);
        if (op === 0) doc.splice(at, 0, `n${rand(6)}`);
        else if (op === 1 && doc.length) doc.splice(Math.min(at, doc.length - 1), 1);
        else if (doc.length) doc[Math.min(at, doc.length - 1)] = `m${rand(6)}`;
      }
      const hunks = diffLines(base, doc);
      // Replay: unchanged stretches must match line for line.
      let b = 0;
      let d = 0;
      for (const h of hunks) {
        expect(h.baseFrom - b).toBe(h.docFrom - d);
        for (; b < h.baseFrom; b++, d++) expect(doc[d]).toBe(base[b]);
        b = h.baseTo;
        d = h.docTo;
      }
      expect(base.length - b).toBe(doc.length - d);
      for (; b < base.length; b++, d++) expect(doc[d]).toBe(base[b]);
    }
  });

  test("a very different file falls back to one hunk", () => {
    const base = Array.from({ length: 3000 }, (_, i) => `old ${i}`);
    const doc = Array.from({ length: 3000 }, (_, i) => `new ${i}`);
    expect(diffLines(base, doc)).toEqual([{ baseFrom: 0, baseTo: 3000, docFrom: 0, docTo: 3000 }]);
  });
});

describe("tree decorations", () => {
  const status = {
    root: "C:/repo",
    branch: "main",
    head: "abc1234",
    upstream: null,
    ahead: 0,
    behind: 0,
    added: 0,
    removed: 0,
    files: [
      { path: "src/app/main.ts", status: "modified" as const, added: 1, removed: 1 },
      { path: "src/new.ts", status: "added" as const, added: 3, removed: 0 },
      { path: "docs/gone.md", status: "deleted" as const, added: 0, removed: 4 },
      { path: "assets/logo.svg", status: "added" as const, added: 1, removed: 0 },
    ],
  };
  const deco = buildDecorations(status, ["C:/repo/node_modules/", "C:/repo/debug.log"]);

  test("files carry their state, matched case- and slash-insensitively on Windows", () => {
    expect(rowGit(deco, win("C:/Repo/src/app/main.ts"), false)).toBe("modified");
    expect(rowGit(deco, "c:/repo/src/new.ts", false)).toBe("added");
    expect(rowGit(deco, "C:/repo/src/app/other.ts", false)).toBe("");
  });

  test("folders holding changes get a dot, new-only folders an added one", () => {
    expect(rowGit(deco, win("C:/repo/src"), true)).toBe("folder-modified");
    expect(rowGit(deco, win("C:/repo/src/app"), true)).toBe("folder-modified");
    expect(rowGit(deco, win("C:/repo/assets"), true)).toBe("folder-added");
    expect(rowGit(deco, win("C:/repo/docs"), true)).toBe("folder-modified");
    expect(rowGit(deco, win("C:/repo"), true)).toBe("folder-modified");
  });

  test("ignored files and everything under ignored folders are dimmed", () => {
    expect(rowGit(deco, win("C:/repo/node_modules"), true)).toBe("ignored");
    expect(rowGit(deco, win("C:/repo/node_modules/react/index.js"), false)).toBe("ignored");
    expect(rowGit(deco, win("C:/repo/debug.log"), false)).toBe("ignored");
    expect(rowGit(deco, win("C:/repo/src/debug.log"), false)).toBe("");
  });

  test("outside the repository or without one nothing is marked", () => {
    expect(rowGit(deco, win("C:/other/y.ts"), false)).toBe("");
    expect(rowGit(buildDecorations(null, null), win("C:/repo/src/new.ts"), false)).toBe("");
  });
});
