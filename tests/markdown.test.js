// Run with: node --test tests/markdown.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const { parseInline, parseMarkdown } = require("../static/markdown.js");

test("bold, italic and code", () => {
  assert.deepEqual(parseInline("Multiply **both** the top and *bottom* by `4`."), [
    { text: "Multiply " },
    { text: "both", bold: true },
    { text: " the top and " },
    { text: "bottom", italic: true },
    { text: " by " },
    { text: "4", code: true },
    { text: "." },
  ]);
});

test("italics next to punctuation", () => {
  assert.deepEqual(parseInline("(*really*) and *end*."), [
    { text: "(" },
    { text: "really", italic: true },
    { text: ") and " },
    { text: "end", italic: true },
    { text: "." },
  ]);
});

test("multiplication with * is left alone", () => {
  for (const line of ["2*4 = 8 and 3*4 = 12", "2 * 3 = 6 and 4 * 5 = 20", "a ** b ** c"]) {
    assert.deepEqual(parseInline(line), [{ text: line }]);
  }
});

test("HTML stays as literal text", () => {
  const line = "<img src=x onerror=alert(1)> <b>hi</b>";
  assert.deepEqual(parseInline(line), [{ text: line }]);
});

test("paragraphs, line breaks and headings", () => {
  assert.deepEqual(parseMarkdown("## Hint\nGood try!\nKeep going.\n\nNext paragraph."), [
    { type: "h", line: [{ text: "Hint" }] },
    { type: "p", lines: [[{ text: "Good try!" }], [{ text: "Keep going." }]] },
    { type: "p", lines: [[{ text: "Next paragraph." }]] },
  ]);
});

test("bullet and numbered lists", () => {
  assert.deepEqual(parseMarkdown("* Step one\n- Step **two**\n\n3. Third\n4) Fourth"), [
    { type: "ul", items: [[{ text: "Step one" }], [{ text: "Step " }, { text: "two", bold: true }]] },
    { type: "ol", start: 3, items: [[{ text: "Third" }], [{ text: "Fourth" }]] },
  ]);
});

test("Windows line endings and blank input", () => {
  assert.deepEqual(parseMarkdown("a\r\nb"), [{ type: "p", lines: [[{ text: "a" }], [{ text: "b" }]] }]);
  assert.deepEqual(parseMarkdown(""), []);
});
