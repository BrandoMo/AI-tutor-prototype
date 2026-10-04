/*
 * Tiny, safe Markdown renderer for tutor replies.
 *
 * Gemini formats answers with **bold**, *italics*, bullet and numbered
 * lists. This supports just that subset. It never uses innerHTML: text
 * only ever becomes text nodes, so a reply containing HTML is shown as
 * literal characters, never run.
 *
 * parseMarkdown() is pure (no DOM) so it can be unit-tested in Node;
 * renderMarkdown() turns its output into DOM nodes in the browser.
 */

// `code` | **bold** | *italic*. Italic needs a non-word character (or the
// start) before the opening * and none after the closing *, so maths like
// "2*4 = 8 and 3*4" stays as typed. No lookbehind: older Safari lacks it.
const INLINE_RE = /(`[^`\n]+`)|\*\*([^\s*](?:[^*\n]*[^\s*])?)\*\*|(^|[^\w*])\*([^\s*](?:[^*\n]*[^\s*])?)\*(?![\w*])/g;

// Splits a line into segments: { text, bold?, italic?, code? }
function parseInline(line) {
  const segments = [];
  let last = 0;
  INLINE_RE.lastIndex = 0;
  let m;
  while ((m = INLINE_RE.exec(line)) !== null) {
    let start = m.index;
    if (m[3] !== undefined) start += m[3].length; // keep the char before an italic *
    if (start > last) segments.push({ text: line.slice(last, start) });
    if (m[1] !== undefined) segments.push({ text: m[1].slice(1, -1), code: true });
    else if (m[2] !== undefined) segments.push({ text: m[2], bold: true });
    else segments.push({ text: m[4], italic: true });
    last = INLINE_RE.lastIndex;
  }
  if (last < line.length) segments.push({ text: line.slice(last) });
  return segments;
}

// Returns blocks: { type: "p", lines: [segments] }, { type: "h", line },
// { type: "ul", items: [segments] } or { type: "ol", start, items: [segments] }
function parseMarkdown(text) {
  const blocks = [];
  let current = null;

  for (const raw of String(text).replace(/\r\n?/g, "\n").split("\n")) {
    const line = raw.trim();
    let m;
    if (!line) {
      current = null;
    } else if ((m = /^[-*•]\s+(.*)$/.exec(line))) {
      if (!current || current.type !== "ul") blocks.push(current = { type: "ul", items: [] });
      current.items.push(parseInline(m[1]));
    } else if ((m = /^(\d+)[.)]\s+(.*)$/.exec(line))) {
      if (!current || current.type !== "ol") blocks.push(current = { type: "ol", start: Number(m[1]), items: [] });
      current.items.push(parseInline(m[2]));
    } else if ((m = /^#{1,6}\s+(.*)$/.exec(line))) {
      blocks.push({ type: "h", line: parseInline(m[1]) });
      current = null;
    } else {
      if (!current || current.type !== "p") blocks.push(current = { type: "p", lines: [] });
      current.lines.push(parseInline(line));
    }
  }
  return blocks;
}

function appendInline(parent, segments) {
  for (const seg of segments) {
    let node = document.createTextNode(seg.text);
    for (const [flag, tag] of [["code", "code"], ["italic", "em"], ["bold", "strong"]]) {
      if (seg[flag]) {
        const el = document.createElement(tag);
        el.appendChild(node);
        node = el;
      }
    }
    parent.appendChild(node);
  }
}

// Fills `container` with the rendered Markdown
function renderMarkdown(container, text) {
  container.replaceChildren();
  for (const block of parseMarkdown(text)) {
    let el;
    if (block.type === "p") {
      el = document.createElement("p");
      block.lines.forEach((line, i) => {
        if (i > 0) el.appendChild(document.createElement("br"));
        appendInline(el, line);
      });
    } else if (block.type === "h") {
      el = document.createElement("p");
      const strong = document.createElement("strong");
      appendInline(strong, block.line);
      el.appendChild(strong);
    } else {
      el = document.createElement(block.type);
      if (block.type === "ol" && block.start !== 1) el.start = block.start;
      for (const item of block.items) {
        const li = document.createElement("li");
        appendInline(li, item);
        el.appendChild(li);
      }
    }
    container.appendChild(el);
  }
}

if (typeof module !== "undefined") module.exports = { parseInline, parseMarkdown };
