(function (root) {
  "use strict";
  const defaults = {
    source: "archive",
    start: "2022-12-02",
    months: "24",
    cost: "CA",
    policy: "B0_BH",
    reference: "B0_BH",
    visible: [],
    page: "overview",
  };
  function validSelection(saved, rows) {
    const state = { ...defaults, ...saved };
    const matches = rows.filter(
      (r) => String(r.months) === state.months && r.cost === state.cost,
    );
    if (!matches.length && rows.length) {
      state.months = String(rows[0].months);
      state.cost = rows[0].cost;
    }
    const available = rows.filter(
      (r) => String(r.months) === state.months && r.cost === state.cost,
    );
    const starts = [
      ...new Set(available.map((r) => r.start.slice(0, 10))),
    ].sort();
    if (!starts.includes(state.start)) state.start = starts[0] || "";
    const policies = rows
      .filter(
        (r) =>
          r.start.slice(0, 10) === state.start &&
          String(r.months) === state.months &&
          r.cost === state.cost,
      )
      .map((r) => r.policy);
    if (!policies.includes(state.policy)) state.policy = policies[0] || "";
    if (!policies.includes(state.reference))
      state.reference = policies[0] || "";
    state.visible = Array.isArray(state.visible)
      ? [...new Set(state.visible.filter((p) => policies.includes(p)))]
      : [];
    if (!state.visible.length) state.visible = policies;
    if (state.reference && !state.visible.includes(state.reference))
      state.visible.push(state.reference);
    if (state.policy && !state.visible.includes(state.policy))
      state.visible.push(state.policy);
    return state;
  }
  function orderedRows(rows, search, key, descending) {
    const allowed = [
      "start",
      "policy",
      "nav_usdt",
      "return",
      "max_drawdown",
      "btc_physical",
    ];
    if (!allowed.includes(key)) key = "start";
    return rows
      .filter((r) =>
        `${r.start} ${r.policy}`.toLowerCase().includes(search.toLowerCase()),
      )
      .sort((a, b) => {
        const x = a[key],
          y = b[key];
        const cmp =
          key === "start" || key === "policy"
            ? String(x).localeCompare(String(y))
            : decimalCompare(x, y);
        return descending ? -cmp : cmp;
      });
  }
  function routePage(hash) {
    const page = String(hash).replace(/^#/, "");
    return ["overview", "wealth", "btc", "risk", "windows", "demo"].includes(
      page,
    )
      ? page
      : null;
  }
  function provenance(synthetic, data = {}, catalog = {}) {
    if (synthetic)
      return {
        source_kind: "SYNTHETIC_DEMO",
        dataset_id: data.dataset_id || "SYNTHETIC_PUBLIC_DEMO_V1",
        integrity: data.integrity || "NOT_EXECUTED",
        manifest_sha256: null,
      };
    return {
      source_kind: catalog.archive_status || "UNAVAILABLE",
      dataset_id: data.dataset_id || catalog.dataset_id || "DATA_UNAVAILABLE",
      integrity:
        data.integrity || catalog.archive_integrity || "SOURCE_NOT_AUTHORIZED",
      manifest_sha256: data.manifest_sha256 || catalog.manifest_sha256 || null,
    };
  }
  function decimalCompare(a, b) {
    // Exact ordering of projected decimal strings; never a portfolio calculation.
    function parts(value) {
      const s = String(value);
      const match = /^(-?)(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d{1,3}))?$/.exec(s);
      if (!match) throw new Error("Número inválido para ordenação");
      const digits = match[2] + (match[3] || ""),
        at = match[2].length + Number(match[4] || 0);
      return {
        negative: !!match[1],
        whole: at <= 0 ? "0" : digits.slice(0, at).padEnd(at, "0"),
        fraction: at < 0 ? "0".repeat(-at) + digits : digits.slice(at),
      };
    }
    const x = parts(a),
      y = parts(b),
      precision = Math.max(x.fraction.length, y.fraction.length);
    const ix = BigInt(
      (x.negative ? "-" : "") + x.whole + x.fraction.padEnd(precision, "0"),
    );
    const iy = BigInt(
      (y.negative ? "-" : "") + y.whole + y.fraction.padEnd(precision, "0"),
    );
    return ix < iy ? -1 : ix > iy ? 1 : 0;
  }
  const api = {
    defaults,
    validSelection,
    orderedRows,
    decimalCompare,
    routePage,
    provenance,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.GridState = api;
})(typeof window !== "undefined" ? window : globalThis);
