"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const {
  filter,
  canPaint,
  formatDecimal,
} = require("../../research_console/static/lab.js");
const {
  seriesExportAllowed,
  samplingGap,
} = require("../../research_console/static/charts.js");

test("exact financial formatting preserves cents beyond IEEE754 and uses half-even", () => {
  for (const [value, places, expected] of [
    ["9007199254740993.01", 2, "9.007.199.254.740.993,01"],
    ["1/3", 8, "0,33333333"],
    ["1.005", 2, "1"],
    ["1.015", 2, "1,02"],
    ["-1.015", 2, "-1,02"],
    ["-0.0001", 2, "0"],
    ["1e-8", 8, "0,00000001"],
    ["123e3", 0, "123.000"],
    ["2001/2000", 3, "1"],
  ])
    assert.equal(formatDecimal(value, places), expected);
  for (const value of ["NaN", "Infinity", "1/0", "<svg>", "1e999", null, 1])
    assert.throws(() => formatDecimal(value));
  assert.throws(() => formatDecimal("1", 20));
});

test("raw SVG export defaults to denied and respects an explicit rights projection", () => {
  assert.equal(seriesExportAllowed({}), false);
  assert.equal(
    seriesExportAllowed({ source_kind: "ARCHIVED_RESEARCH_RESULT" }),
    false,
  );
  assert.equal(seriesExportAllowed({ source_kind: "SYNTHETIC_DEMO" }), true);
  assert.equal(
    seriesExportAllowed({
      source_kind: "SYNTHETIC_DEMO",
      allow_series_export: false,
    }),
    false,
  );
  assert.equal(seriesExportAllowed({ allow_series_export: true }), true);
});

test("declared irregular sampling breaks curves consistently with risk segmentation", () => {
  const time = "2020-01-01T00:00:00+00:00";
  assert.equal(
    samplingGap(time, "2020-01-02T00:00:00+00:00", { sampling_seconds: 86400 }),
    false,
  );
  assert.equal(
    samplingGap(time, "2020-01-01T12:00:00+00:00", { sampling_seconds: 86400 }),
    true,
  );
  assert.equal(
    samplingGap(time, "2020-01-03T00:00:00+00:00", { sampling_seconds: 86400 }),
    true,
  );
  assert.equal(samplingGap(time, "2020-01-01T12:00:00+00:00", {}), false);
});
const studies = [
  {
    id: "b",
    title: "SYNTHETIC loss",
    source_kind: "SYNTHETIC_DEMO",
    start: "2020-01-02",
    policies: ["MIX"],
  },
  {
    id: "a",
    title: "Archived summary",
    source_kind: "AGGREGATED_RESEARCH_SUMMARY",
    start: "2020-01-01",
    policies: ["CASH"],
  },
  { id: "c", title: "Invalid", source_kind: "DATA_INVALID" },
];
test("library search includes policy and source filter without mutating data", () => {
  const before = JSON.stringify(studies);
  assert.deepEqual(
    filter(studies, "mix", "SYNTHETIC_DEMO", "title").map((s) => s.id),
    ["b"],
  );
  assert.equal(JSON.stringify(studies), before);
});
test("empty and invalid-state filters retain their classification", () => {
  assert.deepEqual(filter(studies, "missing", "", "title"), []);
  assert.deepEqual(
    filter(studies, "", "DATA_INVALID", "title").map((s) => s.id),
    ["c"],
  );
});
test("deterministic order and unknown sort fallback", () => {
  assert.deepEqual(
    filter(studies, "", "", "start").map((s) => s.id),
    ["c", "a", "b"],
  );
  assert.deepEqual(
    filter(studies, "", "", "__proto__"),
    filter(studies, "", "", "title"),
  );
});
test("late rendering cannot overwrite another page or a disconnected root", () => {
  assert.equal(canPaint(null), false);
  assert.equal(
    canPaint({ isConnected: false, classList: { contains: () => true } }),
    false,
  );
  assert.equal(
    canPaint({ isConnected: true, classList: { contains: () => false } }),
    false,
  );
  assert.equal(
    canPaint({
      isConnected: true,
      classList: { contains: (s) => s === "research-lab" },
    }),
    true,
  );
});
