"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const markdownSource = fs.readFileSync(
  path.join(__dirname, "..", "extensions", "webbridge", "markdown.js"),
  "utf8"
);

function loadMarkdown() {
  const context = vm.createContext({ URL });
  vm.runInContext(markdownSource, context, { filename: "markdown.js" });
  return context.WebBridgeMarkdown;
}

test("exposes typed blocks that preserve incomplete streaming state", () => {
  const markdown = loadMarkdown();
  const blocks = markdown.parseBlocks([
    "# Result",
    "",
    "```js",
    "const answer = 42;",
  ].join("\n"), { streaming: true });

  assert.equal(blocks.length, 2);
  assert.equal(blocks[0].type, "heading");
  assert.equal(blocks[0].level, 1);
  assert.equal(blocks[0].complete, true);
  assert.equal(blocks[1].type, "code");
  assert.equal(blocks[1].language, "javascript");
  assert.equal(blocks[1].complete, false);
  assert.equal(blocks[1].streaming, true);
  assert.equal(blocks[1].start, 10);
  assert.equal(blocks[1].end, 34);
  assert.match(blocks[1].html, /wb-streaming-incomplete/);
  assert.match(markdown.renderBlocks(blocks), /wb-syntax-keyword[^>]*>const<\/span>/);

  const target = { innerHTML: "" };
  const rendered = markdown.render(target, "**safe**");
  assert.equal(rendered[0].type, "paragraph");
  assert.equal(target.innerHTML, "<p><strong>safe</strong></p>");
});

test("highlights common code safely without executing source markup", () => {
  const markdown = loadMarkdown();
  const highlighted = markdown.highlight(
    'function greet(name) { return "<img src=x onerror=alert(1)>"; } // hi',
    "js"
  );

  assert.match(highlighted, /wb-syntax-keyword[^>]*>function<\/span>/);
  assert.match(highlighted, /wb-syntax-function[^>]*>greet<\/span>/);
  assert.match(highlighted, /wb-syntax-string/);
  assert.match(highlighted, /wb-syntax-comment/);
  assert.match(highlighted, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.doesNotMatch(highlighted, /<img\b/i);

  const unknownLanguage = markdown.highlight("<script>alert(1)</script>", "brainfuck");
  assert.equal(unknownLanguage, "&lt;script&gt;alert(1)&lt;/script&gt;");
});

test("renders bounded common TeX as accessible MathML", () => {
  const markdown = loadMarkdown();
  const html = markdown.toSafeHtml([
    "Einstein wrote $E = mc^2$.",
    "",
    "$$",
    String.raw`x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}`,
    "$$",
  ].join("\n"));

  assert.match(html, /class="wb-math wb-math-inline"/);
  assert.match(html, /class="wb-math wb-math-display"/);
  assert.match(html, /<msup>/);
  assert.match(html, /<mfrac>/);
  assert.match(html, /<msqrt>/);
  assert.match(html, /<mo>±<\/mo>/);
  assert.match(html, /<annotation encoding="application\/x-tex">/);
});

test("supports Greek symbols and common matrix environments", () => {
  const markdown = loadMarkdown();
  const matrix = markdown.renderMath(
    String.raw`\begin{pmatrix}\alpha & \beta \\ \gamma & \delta\end{pmatrix}`,
    { display: true }
  );

  assert.match(matrix, /<mtable>/);
  assert.equal((matrix.match(/<mtr>/g) || []).length, 2);
  assert.match(matrix, /<mi>α<\/mi>/);
  assert.match(matrix, /<mi>δ<\/mi>/);
  assert.match(matrix, /<mo stretchy="true">\(<\/mo>/);
});

test("math, links, media, and forged blocks remain inert", () => {
  const markdown = loadMarkdown();
  const math = markdown.renderMath(String.raw`\text{<img src=x onerror=alert(1)>}`);
  assert.doesNotMatch(math, /<img\b/i);
  assert.doesNotMatch(math, /<script\b/i);
  assert.match(math, /&lt;img src=x onerror=alert\(1\)&gt;/);

  const html = markdown.toSafeHtml([
    '<script>alert("x")</script>',
    "[bad](javascript:alert(1))",
    "![bad](data:image/svg+xml;base64,PHN2Zz4=)",
    "![escape](../../secret.png)",
    "[good](https://example.com/docs)",
  ].join("\n"));
  assert.doesNotMatch(html, /<script\b/i);
  assert.doesNotMatch(html, /javascript:/i);
  assert.doesNotMatch(html, /data:image/i);
  assert.doesNotMatch(html, /data-webbridge-media-src="\.\.\//i);
  assert.match(html, /href="https:\/\/example\.com\/docs"/);

  const forged = markdown.renderBlocks([{
    raw: '<img src=x onerror="alert(1)">',
    html: '<img src=x onerror="alert(1)">',
  }]);
  assert.equal(forged, "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;");
});
