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
