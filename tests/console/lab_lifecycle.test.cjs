"use strict";
// Exercise the browser script itself. The tiny DOM/fetch doubles do not assert
// physical layout or real HTTP; those are checked separately in a real browser.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const numbers = require("../../research_console/static/numbers.js");
class Element {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.parent = null;
    this.attributes = {};
    this.dataset = {};
    this.listeners = {};
    this.className = "";
    this.value = "";
    this.clientWidth = 390;
    this.classList = {
      contains: (name) => this.className.split(" ").includes(name),
      add: (name) => {
        this.className += " " + name;
      },
    };
  }
  get isConnected() {
    return !!this.connected || !!this.parent?.isConnected;
  }
  get textContent() {
    return (this.text || "") + this.children.map((x) => x.textContent).join("");
  }
  set textContent(value) {
    this.text = String(value);
    this.replaceChildren();
  }
  append(...items) {
    for (let item of items) {
      if (!(item instanceof Element)) {
        const n = new Element("text");
        n.textContent = item;
        item = n;
      }
      item.parent = this;
      this.children.push(item);
    }
  }
  replaceChildren(...items) {
    for (const item of this.children) item.parent = null;
    this.children = [];
    this.append(...items);
  }
  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }
  getAttribute(name) {
    return this.attributes[name] ?? null;
  }
  addEventListener(name, listener) {
    (this.listeners[name] ||= []).push(listener);
  }
  querySelector(tag) {
    return walk(this).find((e) => e !== this && e.tagName === tag) || null;
  }
  click() {
    if (!this.disabled)
      for (const listener of this.listeners.click || [])
        listener({ target: this });
  }
}
function walk(root) {
  return [root, ...root.children.flatMap(walk)];
}
const json = (value, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
const study = (id) => ({
  id,
  title: id,
  integrity: "VALIDATED",
  source_kind: "SYNTHETIC_DEMO",
  policies: [],
  export_scope: "RAW_AND_DERIVED",
});
const result = () => ({
  source_kind: "SYNTHETIC_DEMO",
  status: "VALIDATED_OBSERVATIONS",
  rows: [],
  accounts: [],
  aggregates: [],
  descriptive: [],
  pareto: { non_dominated: [] },
  redistribution: "RESTRICTED",
  export_scope: "DERIVED_ONLY",
  analysis_manifest: {},
});
const flush = async () => {
  for (let i = 0; i < 8; i++) await new Promise(setImmediate);
};
function harness(route) {
  const calls = [],
    root = new Element("main");
  root.connected = true;
  root.className = "research-lab";
  const context = {
    Node: Element,
    document: {
      createElement: (tag) => new Element(tag),
      createElementNS: (_, tag) => new Element(tag),
    },
    GridNumbers: numbers,
    GridCharts: { dispose() {}, lineChart() {} },
    AbortController,
    AbortSignal,
    URLSearchParams,
    performance,
    setTimeout,
    sessionStorage: { getItem: () => null, setItem() {} },
    fetch: async (url, options) => {
      calls.push({ url, options });
      return route(url, options);
    },
  };
  context.window = context;
  vm.runInNewContext(
    fs.readFileSync(
      path.join(__dirname, "../../research_console/static/lab.js"),
      "utf8",
    ),
    context,
  );
  context.GridLab.render(root, {});
  return {
    root,
    api: context.GridLab,
    calls,
    buttons: (name) =>
      walk(root).filter(
        (e) => e.tagName === "button" && e.textContent === name,
      ),
    status: () => walk(root).find((e) => e.className === "status")?.textContent,
    all: () => walk(root),
  };
}
test("leaving during analysis replaces pending progress with an explicit cancelled state", async () => {
  let finish;
  const h = harness((url) =>
    url === "/api/lab/library"
      ? json({ studies: [study("A")], persistence_enabled: true })
      : new Promise((resolve) => {
          finish = () => resolve(json(result()));
        }),
  );
  await flush();
  h.buttons("Analisar A")[0].click();
  await flush();
  assert.equal(h.root.dataset.analysisState, "ANALYSIS_PENDING");
  h.api.deactivate();
  h.api.render(h.root, {});
  await flush();
  assert.equal(h.root.dataset.analysisState, "DATA_UNAVAILABLE");
  assert.match(h.status(), /interrompida/);
  finish();
  await flush();
  assert.equal(
    h.all().some((e) => e.tagName === "table"),
    false,
  );
});
test("leaving during confirmation preserves uncertainty instead of inventing import success", async () => {
  let finish;
  const h = harness((url) => {
    if (url === "/api/lab/library")
      return json({ studies: [], persistence_enabled: true });
    if (url === "/api/lab/preview")
      return json({
        study: study("B"),
        preview_token: "synthetic",
        persistence_enabled: true,
      });
    if (url === "/api/lab/confirm")
      return new Promise((resolve) => {
        finish = () => resolve(json(study("B")));
      });
    throw new Error("No analysis after uncertain confirmation");
  });
  await flush();
  await importPack(h);
  assert.equal(h.root.dataset.importState, "IMPORT_PENDING");
  h.api.deactivate();
  h.api.render(h.root, {});
  await flush();
  finish();
  await flush();
  assert.equal(h.root.dataset.importState, "IMPORT_UNCONFIRMED");
  assert.match(h.status(), /verifique a biblioteca/);
  assert.equal(
    h.calls.some((c) => c.url.startsWith("/api/lab/analysis")),
    false,
  );
});
async function importPack(h) {
  h.all().find((e) => e.type === "file").files = [
    { size: 10, arrayBuffer: async () => new ArrayBuffer(10) },
  ];
  h.buttons("Validar prévia do arquivo")[0].click();
  await flush();
  h.all().find((e) => e.type === "checkbox").checked = true;
  h.buttons("Confirmar importação local")[0].click();
  await flush();
}
test("catalog capabilities survive navigation and study cancellation without discarding a fresh capability", async () => {
  let catalogs = 0,
    finish;
  const h = harness((url, options) => {
    if (url === "/api/lab/library") {
      if (++catalogs === 1)
        return json({ studies: [study("A")], persistence_enabled: true });
      return new Promise((resolve, reject) => {
        finish = () =>
          resolve(json({ studies: [study("A")], persistence_enabled: false }));
        options.signal.addEventListener(
          "abort",
          () => reject(new DOMException("Aborted", "AbortError")),
          { once: true },
        );
      });
    }
    return json(result());
  });
  await flush();
  h.api.deactivate();
  h.api.render(h.root, {});
  h.buttons("Analisar A")[0].click();
  await flush();
  const pending = h.calls.filter((c) => c.url === "/api/lab/library").at(-1);
  assert.equal(pending.options.signal.aborted, false);
  assert.ok(h.root.textContent.includes("A prévia não persiste arquivos"));
  finish();
  await flush();
  assert.ok(h.root.textContent.includes("Prévia em memória disponível"));
});
test("automatic analysis failure after successful import is visible, sanitized and retryable", async () => {
  let fail = true;
  const h = harness((url) => {
    if (url === "/api/lab/library")
      return json({ studies: [study("B")], persistence_enabled: true });
    if (url === "/api/lab/preview")
      return json({
        study: study("B"),
        preview_token: "synthetic",
        persistence_enabled: true,
      });
    if (url === "/api/lab/confirm") return json(study("B"));
    if (url.startsWith("/api/lab/analysis"))
      return fail
        ? json(
            {
              reason: "ANALYSIS_FAILED",
              detail: "DO_NOT_DISPLAY_PRIVATE_PATH",
            },
            500,
          )
        : json(result());
    throw new Error("Unexpected test route");
  });
  await flush();
  await importPack(h);
  assert.match(h.status(), /Importação concluída.*Falha interna/);
  assert.equal(h.root.dataset.importState, "IMPORT_SUCCESS");
  assert.equal(h.root.dataset.analysisState, "ANALYSIS_FAILURE");
  assert.equal(h.root.getAttribute("aria-busy"), "false");
  assert.equal(h.all().filter((e) => e.tagName === "table").length, 0);
  assert.equal(h.root.textContent.includes("DO_NOT_DISPLAY"), false);
  fail = false;
  h.buttons("Analisar B")[0].click();
  await flush();
  assert.equal(h.root.dataset.analysisState, "ANALYSIS_SUCCESS");
  assert.ok(h.all().some((e) => e.tagName === "table"));
});
test("failed persistence is distinguished from successful import and does not request analysis", async () => {
  const h = harness((url) => {
    if (url === "/api/lab/library")
      return json({ studies: [], persistence_enabled: true });
    if (url === "/api/lab/preview")
      return json({
        study: study("B"),
        preview_token: "synthetic",
        persistence_enabled: true,
      });
    if (url === "/api/lab/confirm")
      return json({ reason: "DATA_UNAVAILABLE" }, 422);
    throw new Error("Analysis must not run");
  });
  await flush();
  await importPack(h);
  assert.equal(h.root.dataset.importState, "IMPORT_FAILURE");
  assert.equal(
    h.calls.some((c) => c.url.startsWith("/api/lab/analysis")),
    false,
  );
  assert.match(h.status(), /indisponível/);
});
test("late rejection from an old study cannot replace the current successful result", async () => {
  let rejectOld;
  const h = harness((url) => {
    if (url === "/api/lab/library")
      return json({
        studies: [study("A"), study("B")],
        persistence_enabled: true,
      });
    if (url.includes("id=A"))
      return new Promise((_, reject) => {
        rejectOld = reject;
      });
    return json(result());
  });
  await flush();
  h.buttons("Analisar A")[0].click();
  h.buttons("Analisar B")[0].click();
  await flush();
  rejectOld(new Error("OBSOLETE_FAILURE"));
  await flush();
  assert.equal(h.root.dataset.analysisState, "ANALYSIS_SUCCESS");
  assert.equal(h.root.textContent.includes("OBSOLETE_FAILURE"), false);
  assert.ok(h.root.textContent.includes("Análise · B"));
});
test("risk distance has bounded readable precision while the exact evidence is retained", async () => {
  const exactDistance = "-13.333333333333333333333333333333333333333333333333";
  const data = result();
  data.rows = [
    {
      account_id: "ONE",
      group_id: "group",
      benchmark: null,
      benchmark_comparison: { status: "UNAVAILABLE" },
      evidence: {},
      metrics: {
        exact: {
          nav_final: "2",
          btc_physical: "1",
          btc_equivalent: "1",
          return_ratio: "-1/3",
          max_drawdown: "1/3",
          fees_usdt: "0",
          exposure_mean_left: "1",
        },
        max_drawdown: "1/3",
        nav_final: "2",
        risk: {
          status: "OBSERVED_SEGMENTS_ONLY",
          distance_to_20_pp: exactDistance,
          violates_20_percent: true,
          episodes: [],
          gaps: [],
        },
      },
    },
  ];
  const h = harness((url) =>
    url === "/api/lab/library"
      ? json({ studies: [study("RISK")], persistence_enabled: true })
      : json(data),
  );
  await flush();
  h.buttons("Analisar RISK")[0].click();
  await flush();
  const paragraph = h
    .all()
    .find(
      (e) =>
        e.tagName === "p" &&
        e.textContent.includes("distância para referência"),
    );
  assert.match(paragraph.textContent, /20%: -13,33 pp.*EXCEDEU 20%/);
  assert.ok(h.all().some((e) => e.title?.includes(exactDistance)));
  assert.ok(h.root.textContent.includes('"max_drawdown": "1/3"'));
});
test("initial catalog loading is unknown rather than a false disabled-persistence claim", async () => {
  let finish;
  const h = harness(
    () =>
      new Promise((resolve) => {
        finish = () =>
          resolve(json({ studies: [], persistence_enabled: false }));
      }),
  );
  assert.match(h.root.textContent, /Consultando a disponibilidade/);
  assert.equal(
    h.root.textContent.includes("Prévia em memória disponível"),
    false,
  );
  finish();
  await flush();
  assert.ok(h.root.textContent.includes("Prévia em memória disponível"));
});
test("obsolete catalog failure after leave and reentry cannot overwrite the new page", async () => {
  let rejectOld,
    calls = 0;
  const h = harness((url) => {
    if (url === "/api/lab/library" && ++calls === 1)
      return new Promise((_, reject) => {
        rejectOld = reject;
      });
    return json({ studies: [study("CURRENT")], persistence_enabled: true });
  });
  h.api.deactivate();
  h.api.render(h.root, {});
  await flush();
  rejectOld(new Error("STALE_CATALOG_ERROR"));
  await flush();
  assert.equal(h.root.textContent.includes("STALE_CATALOG_ERROR"), false);
  assert.ok(h.root.textContent.includes("Analisar CURRENT"));
});
test("catalog failure after persistence success does not relabel the import as failed", async () => {
  let catalogs = 0;
  const h = harness((url) => {
    if (url === "/api/lab/library")
      return ++catalogs === 1
        ? json({ studies: [], persistence_enabled: true })
        : json({ reason: "DATA_UNAVAILABLE", detail: "DO_NOT_DISPLAY" }, 422);
    if (url === "/api/lab/preview")
      return json({
        study: study("B"),
        preview_token: "synthetic",
        persistence_enabled: true,
      });
    if (url === "/api/lab/confirm") return json(study("B"));
    throw new Error("Analysis must wait for usable catalog");
  });
  await flush();
  await importPack(h);
  assert.equal(h.root.dataset.importState, "IMPORT_SUCCESS");
  assert.equal(h.root.dataset.analysisState, "DATA_UNAVAILABLE");
  assert.match(h.status(), /Importação concluída.*biblioteca/);
  assert.equal(h.root.textContent.includes("DO_NOT_DISPLAY"), false);
  assert.equal(
    h.all().some((e) => e.tagName === "table"),
    false,
  );
});
test("analysis timeout is explicit and never displays an old result or a private error detail", async () => {
  const h = harness((url) => {
    if (url === "/api/lab/library")
      return json({ studies: [study("A")], persistence_enabled: true });
    throw new DOMException("DO_NOT_DISPLAY_PRIVATE_PATH", "TimeoutError");
  });
  await flush();
  h.buttons("Analisar A")[0].click();
  await flush();
  assert.equal(h.root.dataset.analysisState, "ANALYSIS_FAILURE");
  assert.equal(h.root.getAttribute("aria-busy"), "false");
  assert.match(h.status(), /excedeu o prazo/);
  assert.equal(h.root.textContent.includes("DO_NOT_DISPLAY"), false);
  assert.equal(
    h.all().some((e) => e.tagName === "table"),
    false,
  );
});
