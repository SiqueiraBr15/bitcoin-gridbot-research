"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {
  State,
  accepts,
  identity,
  view,
  preference,
  steps,
} = require("../../research_console/static/review_model.js");
const { formatDecimal } = require("../../research_console/static/numbers.js");
const cases = require("../fixtures/g5_guided_analysis.json").cases;
const copy = (x) => structuredClone(x);
const selection = (result) => ({
  accounts: null,
  objectives: result.pareto.objectives,
});
for (const fixture of cases) {
  test(`bind all seven steps to canonical ${fixture.study.pack_id} observations without mutation`, () => {
    const original = JSON.stringify(fixture),
      { study, analysis } = copy(fixture),
      state = new State();
    const ticket = state.begin(selection(analysis));
    assert.equal(state.availability, "LOADING");
    assert.equal(state.commit(ticket, study, analysis), true);
    assert.equal(state.availability, "READY");
    for (let step = 1; step <= steps.length; step++) {
      const snapshot = view(study, analysis, "MIX");
      assert.equal(snapshot.row.policy, "MIX");
      assert.equal(snapshot.row.metrics.exact.btc_physical, "5");
      assert.equal(snapshot.row.metrics.exact.cash_usdt, "50");
      assert.equal(snapshot.comparison.reference, snapshot.row.benchmark);
    }
    assert.equal(JSON.stringify(fixture), original);
  });
}
test("hand-derived NAV and BTC-equivalent remain different, preserving exact rationals", () => {
  const { study, analysis } = cases.find(
    (c) => c.study.pack_id === "favorable",
  );
  const mix = view(study, analysis, "MIX").row.metrics.exact;
  assert.equal(mix.nav_final, "115");
  assert.equal(mix.btc_equivalent, "115/13");
  assert.equal(mix.btc_physical, "5");
  assert.equal(mix.return_ratio, "3/20");
  assert.equal(formatDecimal(mix.return_ratio, 6, 100), "15");
  assert.equal(formatDecimal(mix.btc_equivalent, 8), "8,84615385");
});
test("exactly20 percent retains the backend non-violation flag,40 percent exceeds", () => {
  const { study, analysis } = cases.find(
    (c) => c.study.pack_id === "risk_violation",
  );
  assert.equal(
    view(study, analysis, "MIX").row.metrics.risk.violates_20_percent,
    false,
  );
  assert.equal(
    view(study, analysis, "MIX").row.metrics.exact.max_drawdown,
    "1/5",
  );
  assert.equal(
    view(study, analysis, "BTC_HOLD").row.metrics.risk.violates_20_percent,
    true,
  );
});
test("old success/error/action tickets cannot overwrite a new evidence identity", () => {
  const state = new State(),
    a = cases[0],
    b = cases[1];
  const first = state.begin(selection(a.analysis));
  state.commit(first, a.study, a.analysis);
  const old = state.identity;
  state.action("replay", "EQUIVALENT", old);
  const second = state.begin(selection(b.analysis));
  assert.equal(state.replay, "NOT_RUN");
  assert.equal(state.identity, null);
  assert.equal(state.commit(first, a.study, a.analysis), false);
  assert.equal(state.fail(first, { reason: "DATA_UNAVAILABLE" }), false);
  assert.equal(state.commit(second, b.study, b.analysis), true);
  assert.equal(state.action("replay", "EQUIVALENT", old), false);
  assert.equal(state.identity, identity(b.study, b.analysis));
});
for (const change of [
  (x) => (x.analysis.pack_sha256 = "a".repeat(64)),
  (x) => (x.analysis.analysis_manifest.expected_result_sha256 = "bad"),
  (x) => (x.analysis.analysis_manifest.implementation_sha256 = ""),
  (x) => x.analysis.analysis_manifest.accounts.reverse(),
  (x) => (x.analysis.analysis_manifest.objectives = ["fees_usdt"]),
  (x) => (x.analysis.source_kind = "ARCHIVED_RESEARCH_RESULT"),
  (x) => (x.analysis.numeric_contract = "FLOAT"),
  (x) => (x.analysis.analysis_manifest.schema = "GRIDBOT_ANALYSIS_V2"),
])
  test("a mismatched response binding is refused rather than relabelled", () => {
    const f = copy(cases[0]),
      state = new State(),
      request = selection(f.analysis);
    change(f);
    const ticket = state.begin(request);
    assert.equal(accepts(f.study, f.analysis, request), false);
    assert.throws(
      () => state.commit(ticket, f.study, f.analysis),
      /resposta não corresponde/,
    );
    assert.equal(state.identity, null);
  });
test("missing objective is not dominated, zero, or complete risk", () => {
  const f = copy(cases[0]);
  f.analysis.rows[0].metrics.exact.max_drawdown = null;
  f.analysis.rows[0].metrics.risk.risk_complete = false;
  assert.equal(
    view(f.study, f.analysis, f.analysis.rows[0].account_id).eligibility,
    "INSUFFICIENT_OBJECTIVE_DATA",
  );
});
test("group partitioning uses backend groups and no new global Pareto", () => {
  const f = copy(cases[0]);
  f.analysis.rows[1].group_id = "d".repeat(64);
  assert.equal(view(f.study, f.analysis, "").groups.length, 2);
  assert.deepEqual(
    view(f.study, f.analysis, "").result.pareto,
    f.analysis.pareto,
  );
});
test("aggregate-only has no fabricated wallet and explicit unavailable metrics", () => {
  const f = copy(cases[0]);
  f.analysis.rows = [];
  f.analysis.accounts = [];
  f.analysis.aggregates = [
    { policy: "CASH", observations: 2, losses: 0, violations: 0 },
  ];
  f.analysis.analysis_manifest.accounts = [];
  f.analysis.status = "AGGREGATE_ONLY_NO_CURVES";
  const state = new State();
  state.commit(state.begin(selection(f.analysis)), f.study, f.analysis);
  assert.equal(state.availability, "AGGREGATE_ONLY");
  assert.equal(view(f.study, f.analysis, "").row, null);
});
test("preferences cannot persist evidence, grant, numbers or an invalid stage", () => {
  assert.deepEqual(
    preference({
      step: 7,
      mode: "detailed",
      grants: { PUBLIC: true },
      cash: "10",
    }),
    { step: 7, mode: "detailed" },
  );
  for (const step of [null, -1, 0, 8, 1.5, "3"])
    assert.equal(preference({ step }).step, 1);
});
test("each tab has volatile lifecycle, restart discards replay and export state", () => {
  const a = new State(),
    b = new State(),
    f = cases[0];
  a.commit(a.begin(selection(f.analysis)), f.study, f.analysis);
  a.action("replay", "EQUIVALENT", a.identity);
  assert.equal(b.identity, null);
  a.invalidate();
  assert.equal(a.identity, null);
  assert.equal(a.replay, "NOT_RUN");
  assert.equal(a.export, "IDLE");
});
test("UI model and renderer have no network, storage, financial engine or export channel", () => {
  for (const file of ["review_model.js", "review_view.js"]) {
    const text = fs.readFileSync(
      path.join(__dirname, "../../research_console/static", file),
      "utf8",
    );
    assert.doesNotMatch(
      text,
      /\b(?:fetch|XMLHttpRequest|WebSocket|Blob|localStorage|sessionStorage|innerHTML)\b/,
    );
    assert.doesNotMatch(text, /\b(?:eval|Function)\s*\(/);
  }
});
