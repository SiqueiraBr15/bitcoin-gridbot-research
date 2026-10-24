"use strict";
const test = require("node:test"),
  assert = require("node:assert/strict");
const { domain, nearest } = require("../../research_console/static/charts.js");
const {
  validSelection,
  orderedRows,
  decimalCompare,
} = require("../../research_console/static/state.js");
test("drawdown top is exactly zero, limit is -20 percent", () => {
  for (const values of [
    [0, 0],
    [0, -0.1],
    [0, -0.7],
  ]) {
    const [low, high] = domain(values, "drawdown");
    assert.equal(high, 0);
    assert.ok(low <= -0.2);
    assert.ok(low <= Math.min(...values));
  }
});
test("nonnegative BTC has no invented negative domain", () => {
  for (const values of [
    [0, 0],
    [0.00001, 0.000011],
    [1, 200],
  ]) {
    const [lo, hi] = domain(values, "btc");
    assert.equal(lo, 0);
    assert.ok(hi > Math.max(...values));
  }
});
test("NAV absolute and adjusted domains are explicit", () => {
  assert.equal(domain([100, 101], "nav")[0], 0);
  assert.ok(domain([100, 101], "nav", true)[0] > 0);
});
test("empty, nonfinite and positive drawdown refused", () => {
  assert.equal(domain([], "nav"), null);
  assert.throws(() => domain([Infinity], "nav"));
  assert.throws(() => domain([0.1], "drawdown"));
});
test("constant, negative, mixed and broad amplitudes remain finite", () => {
  for (const values of [
    [-10, -1],
    [-100, 0, 200],
    [0],
    [100, 100],
    [1e-12, 1e12],
  ]) {
    const d = domain(values, "return");
    assert.ok(d.every(Number.isFinite));
    assert.ok(d[0] < d[1]);
    assert.ok(d[0] <= Math.min(...values));
    assert.ok(d[1] >= Math.max(...values));
  }
});
test("nearest mark is observed, never interpolated", () => {
  const a = [
    { time: "2020-01-01T00:00:00Z" },
    { time: "2020-01-04T00:00:00Z" },
  ];
  assert.equal(nearest(a, Date.parse("2020-01-02T00:00:00Z")), a[0]);
  assert.equal(nearest([], 0), null);
});
const rows = [
  {
    start: "2020-01-02T00:00:00Z",
    months: 6,
    cost: "CA",
    policy: "B0_BH",
    nav_usdt: "100",
    return: "0",
  },
  {
    start: "2022-12-02T00:00:00Z",
    months: 24,
    cost: "CB",
    policy: "P_BANDS",
    nav_usdt: "80",
    return: "-0.2",
  },
];
test("invalid filters normalize only to existing combinations", () => {
  const s = validSelection(
    {
      months: "12",
      cost: "CX2",
      start: "2099-01-01",
      policy: "unknown",
      reference: "unknown",
    },
    rows,
  );
  assert.equal(s.start, "2020-01-02");
  assert.equal(s.months, "6");
  assert.equal(s.cost, "CA");
  assert.equal(s.policy, "B0_BH");
});
test("reference is always included, stale policies removed", () => {
  const s = validSelection(
    { months: "24", cost: "CB", start: "2022-12-02", visible: ["B0_BH"] },
    rows,
  );
  assert.deepEqual(s.visible, ["P_BANDS"]);
});
test("empty archive gives honest empty controls", () => {
  const s = validSelection({}, []);
  assert.equal(s.start, "");
  assert.equal(s.policy, "");
  assert.deepEqual(s.visible, []);
});
test("sorting is exact for values beyond Number precision", () => {
  assert.equal(
    decimalCompare("100000000000000001.1", "100000000000000001.01"),
    1,
  );
  assert.equal(decimalCompare("-1.01", "-1.1"), 1);
  assert.equal(decimalCompare("1.00", "1"), 0);
});
test("search and sorting never mutate archive rows", () => {
  const before = JSON.stringify(rows);
  assert.equal(orderedRows(rows, "2022", "return", false).length, 1);
  assert.equal(orderedRows(rows, "", "return", false)[0].policy, "P_BANDS");
  assert.equal(JSON.stringify(rows), before);
});
test("restored valid session selection survives page navigation", () => {
  const s = validSelection(
    { months: "24", cost: "CB", start: "2022-12-02", page: "risk" },
    rows,
  );
  const saved = JSON.parse(JSON.stringify(s));
  assert.deepEqual(validSelection({ ...saved, page: "wealth" }, rows), {
    ...saved,
    page: "wealth",
  });
});
test("normal text contrast meets WCAG AA for chosen palette", () => {
  const lum = (h) => {
    const v = h.match(/../g).map((c) => {
      const x = parseInt(c, 16) / 255;
      return x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
  };
  for (const color of ["b3c0d5", "edf2fa", "69e4be", "ff96a2"]) {
    assert.ok((lum(color) + 0.05) / (lum("131e2e") + 0.05) >= 4.5);
  }
});

test("scientific notation ordering and duplicate restored policies", () => {
  assert.equal(decimalCompare("1E-8", "0.000000010"), 0);
  assert.equal(decimalCompare("1E2", "99.99"), 1);
  assert.deepEqual(
    validSelection(
      {
        months: "24",
        cost: "CB",
        start: "2022-12-02",
        visible: ["P_BANDS", "P_BANDS"],
      },
      rows,
    ).visible,
    ["P_BANDS"],
  );
});

test("unleveraged exposure chart is bounded by zero and 100 percent", () => {
  assert.deepEqual(domain([0, 0.5, 1], "exposure"), [0, 1]);
});

test("route history accepts known pages and ignores skip links or HTML", () => {
  const { routePage } = require("../../research_console/static/state.js");
  assert.equal(routePage("#risk"), "risk");
  for (const h of ["#content", "#<script>", "#../../private", ""])
    assert.equal(routePage(h), null);
});

test("SVG identity projection preserves exact strings and drops private extras", () => {
  const { exportMetadata } = require("../../research_console/static/charts.js");
  const row = {
    policy: "B0_BH",
    nav_usdt: "100.000000000000000001",
    private_path: "NEVER_EXPORT",
  };
  const result = exportMetadata(
    {
      schema: "GRIDBOT_RESEARCH_SELECTION_V3",
      source_kind: "SYNTHETIC_DEMO",
      dataset_id: "SYNTHETIC_PUBLIC_DEMO_V1",
      focused_policy: "B0_BH",
      private_path: "NEVER_EXPORT",
    },
    [{ summary: row }],
    "nav",
    "USDT",
  );
  assert.equal(result.summaries[0].nav_usdt, row.nav_usdt);
  assert.equal(result.selection.dataset_id, "SYNTHETIC_PUBLIC_DEMO_V1");
  assert.ok(!JSON.stringify(result).includes("NEVER_EXPORT"));
  assert.equal(result.schema, "GRIDBOT_CHART_EXPORT_V1");
});

test("accessible mark table pages original exact observations", () => {
  const { markRows } = require("../../research_console/static/charts.js");
  const series = Array.from({ length: 60 }, (_, i) => ({
    time: String(i),
    nav: "100.000000000000000001",
  }));
  const accounts = [{ summary: { policy: "B0_BH" }, series }];
  assert.equal(markRows(accounts, "nav", "B0_BH", 0).length, 25);
  assert.deepEqual(markRows(accounts, "nav", "B0_BH", 50)[0], {
    time: "50",
    value: "100.000000000000000001",
  });
  assert.equal(markRows([], "nav", "B0_BH").length, 0);
});

test("synthetic provenance never inherits the historical manifest or unexecuted integrity", () => {
  const { provenance } = require("../../research_console/static/state.js");
  const archive = {
    archive_status: "ARCHIVED_RESEARCH_RESULT",
    dataset_id: "M1_R_DAILY_MARKS_V1",
    manifest_sha256: "historical_hash",
    archive_integrity: "MATRICES_VERIFIED",
  };
  const pending = provenance(true, {}, archive);
  assert.equal(pending.manifest_sha256, null);
  assert.equal(pending.dataset_id, "SYNTHETIC_PUBLIC_DEMO_V1");
  assert.equal(pending.integrity, "NOT_EXECUTED");
  const ran = provenance(
    true,
    {
      dataset_id: "SYNTHETIC_PUBLIC_DEMO_V1",
      integrity: "NATIVE_REPLAY_VERIFIED",
    },
    archive,
  );
  assert.equal(ran.manifest_sha256, null);
  assert.equal(ran.integrity, "NATIVE_REPLAY_VERIFIED");
  assert.equal(
    provenance(false, {}, archive).manifest_sha256,
    "historical_hash",
  );
  assert.equal(provenance(false, {}, {}).dataset_id, "DATA_UNAVAILABLE");
});
