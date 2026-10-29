"use strict";
// Structural guard for the scoped layout contract. Real geometry, readable text
// and keyboard operation are verified separately in the browser audit.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const css = fs.readFileSync(
  path.join(__dirname, "../../research_console/static/style.css"),
  "utf8",
);
const rules = [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((match) => ({
  selectors: match[1]
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .trim()
    .split(/\s*,\s*/),
  declarations: Object.fromEntries(
    match[2]
      .split(";")
      .filter((line) => line.includes(":"))
      .map((line) => line.trim().split(/\s*:\s*/)),
  ),
}));
test("Lab identifiers, headings and study actions wrap within the available width", () => {
  for (const selector of [
    ".research-lab .lab-controls label",
    ".research-lab .tag",
    ".research-lab .legend .series-label",
    ".research-lab .readout > span",
    ".research-lab .panel h2",
    ".research-lab .panel h3",
    ".research-lab .lab-study button",
  ]) {
    const properties = Object.assign(
      {},
      ...rules
        .filter((r) => r.selectors.includes(selector))
        .map((r) => r.declarations),
    );
    assert.equal(properties["min-width"], "0", selector);
    assert.equal(properties["max-width"], "100%", selector);
    assert.equal(properties["overflow-wrap"], "anywhere", selector);
    assert.notEqual(properties["overflow"], "hidden", selector);
    assert.notEqual(properties["text-overflow"], "ellipsis", selector);
    assert.equal(properties["font-size"], undefined, selector);
  }
});
test("Exact evidence tables keep local scrolling instead of clipping identifiers", () => {
  const rule = rules.find((r) => r.selectors.includes(".table-wrap"));
  assert.ok(rule);
  const horizontal = (
    rule.declarations["overflow-x"] ||
    rule.declarations.overflow ||
    ""
  ).split(/\s+/)[0];
  assert.ok(["auto", "scroll"].includes(horizontal));
  assert.notEqual(rule.declarations["text-overflow"], "ellipsis");
});
