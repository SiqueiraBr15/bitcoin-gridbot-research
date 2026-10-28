(function (root) {
  "use strict";
  // Presentation identities and lifecycle only. No financial arithmetic.
  const steps = Object.freeze([
    "Evidência",
    "Patrimônio",
    "BTC",
    "Risco",
    "Comparação",
    "Verificação",
    "Resumo",
  ]);
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const ids = (values) => [...values].sort();
  const hash = (value) =>
    typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
  function preference(value) {
    return {
      mode: value?.mode === "detailed" ? "detailed" : "guided",
      step:
        Number.isInteger(value?.step) && value.step >= 1 && value.step <= 7
          ? value.step
          : 1,
    };
  }
  function accepts(study, result, requested) {
    const m = result?.analysis_manifest;
    return !!(
      study &&
      m &&
      hash(study.id) &&
      result.pack_sha256 === study.id &&
      m.pack_sha256 === study.id &&
      hash(result.manifest_sha256) &&
      m.manifest_sha256 === result.manifest_sha256 &&
      hash(m.implementation_sha256) &&
      hash(m.expected_result_sha256) &&
      m.schema === "GRIDBOT_ANALYSIS_V1" &&
      result.analytics_version === "G4_ANALYTICS_V1" &&
      m.analytics_version === result.analytics_version &&
      result.numeric_contract === "EXACT_RATIONAL_DECIMAL_V2" &&
      result.source_kind === study.source_kind &&
      result.data_nature === study.data_nature &&
      Array.isArray(result.rows) &&
      Array.isArray(result.accounts) &&
      Array.isArray(result.aggregates) &&
      same(
        m.accounts,
        result.rows.map((r) => r.account_id),
      ) &&
      same(m.accounts, result.accounts.map((r) => r.account_id).sort()) &&
      (!requested.accounts || same(ids(requested.accounts), m.accounts)) &&
      same(requested.objectives, m.objectives) &&
      same(result.pareto?.objectives, m.objectives)
    );
  }
  function identity(study, result) {
    const m = result.analysis_manifest;
    return JSON.stringify({
      pack: result.pack_sha256,
      manifest: result.manifest_sha256,
      source: result.source_kind,
      nature: result.data_nature,
      dataset: study.dataset_identity,
      schema: m.schema,
      analytics: m.analytics_version,
      numeric: result.numeric_contract,
      implementation: m.implementation_sha256,
      result: m.expected_result_sha256,
      accounts: m.accounts,
      objectives: m.objectives,
      context: result.rows.map((r) => [
        r.account_id,
        r.policy,
        r.window_id,
        r.start,
        r.end,
        r.cost_scenario,
        r.benchmark,
        r.group_id,
      ]),
    });
  }
  function view(study, result, focus) {
    const row =
      result?.rows.find((r) => r.account_id === focus) ||
      result?.rows[0] ||
      null;
    const account =
      result?.accounts.find((a) => a.account_id === row?.account_id) || null;
    return {
      study,
      result,
      row,
      account,
      last: account?.points.at(-1) || null,
      groups: [...new Set(result?.rows.map((r) => r.group_id) || [])],
      comparison: row?.benchmark_comparison || {
        status: "NOT_SELECTED_OR_UNDECLARED",
      },
      eligibility: !row
        ? "NO_SERIES"
        : result.pareto.objectives.some((k) => row.metrics.exact[k] == null)
          ? "INSUFFICIENT_OBJECTIVE_DATA"
          : result.pareto.non_dominated.includes(row.account_id)
            ? "NON_DOMINATED_IN_GROUP"
            : "DOMINATED_IN_GROUP",
    };
  }
  class State {
    constructor() {
      this.generation = 0;
      this.clear();
    }
    clear() {
      this.availability = "IDLE";
      this.identity = null;
      this.error = null;
      this.replay = "NOT_RUN";
      this.export = "IDLE";
    }
    begin(selection) {
      this.generation++;
      this.clear();
      this.availability = "LOADING";
      this.selection = {
        accounts: selection.accounts ? [...selection.accounts] : null,
        objectives: [...selection.objectives],
      };
      return this.generation;
    }
    commit(ticket, study, result) {
      if (ticket !== this.generation) return false;
      if (!accepts(study, result, this.selection)) {
        const error = new Error(
          "A resposta não corresponde à evidência e seleção atuais. Nenhum valor foi aceito.",
        );
        error.reason = "RESPONSE_IDENTITY_MISMATCH";
        throw error;
      }
      this.identity = identity(study, result);
      this.availability =
        result.status === "AGGREGATE_ONLY_NO_CURVES"
          ? "AGGREGATE_ONLY"
          : "READY";
      return true;
    }
    fail(ticket, error) {
      if (ticket !== this.generation) return false;
      this.clear();
      this.error = error.reason || "REQUEST_FAILED";
      this.availability =
        error.reason === "DATA_UNAVAILABLE"
          ? "UNAVAILABLE"
          : error.status === 422 ||
              error.reason === "RESPONSE_IDENTITY_MISMATCH"
            ? "INVALID"
            : "ERROR";
      return true;
    }
    invalidate() {
      this.generation++;
      this.clear();
    }
    action(kind, status, binding) {
      if (
        !this.identity ||
        binding !== this.identity ||
        !["replay", "export"].includes(kind)
      )
        return false;
      this[kind] = status;
      return true;
    }
  }
  const api = { steps, preference, accepts, identity, view, State };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.GridGuidedReview = api;
})(typeof window !== "undefined" ? window : globalThis);
