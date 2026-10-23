"use strict";
const $ = (id) => document.getElementById(id);
const labels = {
  B0_BH: "Comprar e manter",
  B1_HALF: "50/50 passivo",
  B2_DCA: "DCA",
  B3_CASH: "Caixa USDT",
  P_BANDS: "Bandas 40/60",
  P_MONTHLY: "Rebalanceamento mensal",
  round_trip: "Round trip · sintético",
  falling_mark: "Queda de marcação · sintético",
};
const titles = {
  overview: "Visão geral",
  wealth: "Patrimônio",
  btc: "Acumulação de BTC",
  risk: "Risco e drawdown",
  windows: "Janelas históricas",
  demo: "Demonstração PAPER",
};
const money = (v) =>
  v == null
    ? "Indisponível"
    : Number(v).toLocaleString("pt-BR", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      });
const coins = (v) =>
  v == null
    ? "Indisponível"
    : Number(v).toLocaleString("pt-BR", {
        minimumFractionDigits: 5,
        maximumFractionDigits: 8,
      });
const pct = (v) => (v == null ? "Indisponível" : money(Number(v) * 100) + "%");
const el = (tag, text, cls) => {
  const e = document.createElement(tag);
  if (text != null) e.textContent = String(text);
  if (cls) e.className = cls;
  return e;
};
let catalog = { rows: [], archive_status: "UNAVAILABLE" },
  state = { ...GridState.defaults },
  payload = { accounts: [] },
  demoPolicy = "round_trip",
  loading = false,
  error = "",
  requestId = 0,
  search = "",
  sort = "start",
  descending = false,
  offset = 0,
  zoom = false;
try {
  state = {
    ...state,
    ...JSON.parse(sessionStorage.getItem("gridbot.g2.selection") || "{}"),
  };
} catch {}
if (!titles[state.page]) state.page = "overview";
if (!["archive", "demo"].includes(state.source)) state.source = "archive";
const synthetic = () => state.page === "demo" || state.source === "demo";
const selected = () => (synthetic() ? demoPolicy : state.policy);
function save() {
  try {
    sessionStorage.setItem("gridbot.g2.selection", JSON.stringify(state));
  } catch {}
}
function panel(title, text) {
  const p = el("section", null, "panel");
  p.append(el("h2", title));
  if (text) p.append(el("p", text, "explain"));
  return p;
}
function metric(parent, title, value, detail, cls = "") {
  const c = el("div", null, "metric " + cls);
  c.append(
    el("span", title, "metric-label"),
    el("strong", value, "metric-value"),
    el("small", detail),
  );
  parent.append(c);
}
function table(parent, headers, rows) {
  const wrap = el("div", null, "table-wrap"),
    t = el("table"),
    tr = el("tr"),
    head = el("thead"),
    body = el("tbody");
  headers.forEach((h) => tr.append(el("th", h)));
  head.append(tr);
  t.append(head);
  rows.forEach((row) => {
    const r = el("tr");
    row.forEach((cell) => {
      const td = el("td");
      if (cell instanceof Node) td.append(cell);
      else td.textContent = String(cell ?? "Indisponível");
      r.append(td);
    });
    body.append(r);
  });
  t.append(body);
  wrap.append(t);
  parent.append(wrap);
}
function button(text, fn, cls = "action") {
  const b = el("button", text, cls);
  b.type = "button";
  b.addEventListener("click", fn);
  return b;
}
function select(id, values, value, names = labels) {
  const control = $(id);
  control.replaceChildren(
    ...values.map((v) => {
      const option = el("option", names[v] || v);
      option.value = v;
      return option;
    }),
  );
  if (!values.length) {
    const option = el("option", "Dados indisponíveis");
    option.value = "";
    control.append(option);
  }
  control.value = values.includes(value) ? value : values[0] || "";
  control.disabled = !values.length;
}
function controls() {
  const demo = synthetic();
  $("source").value = state.source;
  $("history-controls").hidden = demo;
  $("demo-controls").hidden = !demo;
  $("reference-wrap").hidden = demo;
  $("source-wrap").hidden = state.page === "demo";
  $("reset").hidden = demo;
  if (demo) {
    select("demo-policy", ["round_trip", "falling_mark"], demoPolicy);
    return;
  }
  state = GridState.validSelection(state, catalog.rows);
  save();
  const rows = catalog.rows;
  select(
    "months",
    [...new Set(rows.map((r) => String(r.months)))],
    state.months,
    { 6: "6 meses", 12: "12 meses", 24: "24 meses" },
  );
  select(
    "cost",
    [
      ...new Set(
        rows
          .filter((r) => String(r.months) === state.months)
          .map((r) => r.cost),
      ),
    ],
    state.cost,
    { CA: "CA · principal", CX2: "CX2 · fee duplicada", CB: "CB · adverso" },
  );
  select(
    "start",
    [
      ...new Set(
        rows
          .filter(
            (r) => String(r.months) === state.months && r.cost === state.cost,
          )
          .map((r) => r.start.slice(0, 10)),
      ),
    ],
    state.start,
    {},
  );
  const policies = rows
    .filter(
      (r) =>
        r.start.slice(0, 10) === state.start &&
        String(r.months) === state.months &&
        r.cost === state.cost,
    )
    .map((r) => r.policy);
  select("policy", policies, state.policy);
  select("reference", policies, state.reference);
}
async function api(url) {
  const response = await fetch(url, {
    credentials: "same-origin",
    cache: "no-store",
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.reason || "LOCAL_REQUEST_FAILED");
  return data;
}
function query() {
  return new URLSearchParams({
    start: state.start,
    months: state.months,
    cost: state.cost,
    reference: state.reference,
    policies: state.visible.join(","),
  });
}
async function load(runDemo = false) {
  const id = ++requestId;
  loading = true;
  error = "";
  payload = { accounts: [] };
  controls();
  render();
  try {
    let result;
    if (synthetic()) {
      if (!runDemo) {
        loading = false;
        render();
        return;
      }
      result = await api("/api/demo");
    } else if (state.start && catalog.rows.length)
      result = await api("/api/selection?" + query());
    else result = { accounts: [], source_kind: "UNAVAILABLE" };
    if (id !== requestId) return;
    payload = result;
    loading = false;
    render();
  } catch (e) {
    if (id !== requestId) return;
    error = e.message;
    loading = false;
    payload = { accounts: [], source_kind: "UNAVAILABLE" };
    render();
  }
}
function navigate(page) {
  state.page = page;
  window.scrollTo({ top: 0, behavior: "auto" });
  save();
  load(synthetic() && demoLoaded);
}
let demoLoaded = false;
function drawChart(parent, title, field, unit) {
  GridCharts.lineChart(parent, {
    accounts: payload.accounts,
    field,
    unit,
    title,
    selected: selected(),
    labels,
    zoom: field === "nav" && zoom,
  });
}
function empty(parent) {
  const why = error || catalog.archive_reason;
  const p = panel(
    why ? "Evidência recusada" : "Dados indisponíveis",
    why
      ? {
          INTEGRITY_MISMATCH:
            "O hash da origem divergiu. Valores e cache não serão usados.",
          MISSING_SOURCE: "Um arquivo autorizado está ausente.",
          INVALID_SELECTION: "A combinação escolhida não é admitida.",
          INVALID_SCHEMA_OR_SERIES:
            "Schema, contagem ou série temporal inválida.",
        }[why] || "Não foi possível validar os dados locais."
      : "Nenhum histórico foi autorizado ou distribuído. Não geramos curvas para preencher lacunas.",
  );
  p.append(button("Abrir demonstração sintética", () => navigate("demo")));
  parent.append(p);
}
function overview(parent) {
  const c = el("div", null, "metrics");
  metric(c, "Execução", "PAPER / OFFLINE", "Sem ordens reais");
  metric(
    c,
    "Acervo admitido",
    catalog.rows.length,
    "Linhas de resultados, não janelas independentes",
  );
  metric(
    c,
    "Última pesquisa",
    catalog.research_date || "Indisponível",
    "Data do relatório arquivado",
  );
  metric(
    c,
    "Referência de risco",
    "20%",
    "Preferência analítica, não stop-loss",
  );
  parent.append(c);
  const p = panel(
    "Pesquisa com resultados verificáveis",
    "GRID tradicional, GRID persistente e bandas não demonstraram vantagem robusta suficiente sobre benchmarks simples. Nenhuma política com BTC respeitou 20% em todas as janelas M1.",
  );
  p.append(
    el(
      "p",
      "O console compara contas equivalentes e separa patrimônio, quantidade física de BTC e risco. A pesquisa é retrospectiva; janelas sobrepostas não são amostras independentes.",
    ),
  );
  p.append(
    button("Explorar patrimônio", () => navigate("wealth")),
    button("Executar demo PAPER", () => navigate("demo"), "secondary"),
  );
  parent.append(p);
  provenance(parent);
}
function provenance(parent) {
  const p = panel(
    "Proveniência da análise",
    "Resultados arquivados e cenários fictícios mantêm identidades distintas. O checksum confirma igualdade ao artefato admitido; não autentica o mercado externo.",
  );
  const data = payload.provenance || {},
    dl = el("dl");
  const items = [
    ["Fonte", synthetic() ? "SYNTHETIC_DEMO" : catalog.archive_status],
    ["Dataset", data.dataset_id || catalog.dataset_id || "UNAVAILABLE"],
    [
      "Integridade",
      data.integrity || catalog.archive_integrity || "Fonte não autorizada",
    ],
    ["Unidades", "USDT · BTC · UTC · ratios / pp explícitos"],
    [
      "Manifesto SHA-256",
      data.manifest_sha256 || catalog.manifest_sha256 || "Não aplicável à demo",
    ],
  ];
  items.forEach(([key, value]) => dl.append(el("dt", key), el("dd", value)));
  p.append(
    dl,
    el(
      "p",
      "Sem impostos, liquidação final ou risco USDT modelados. Marcação diária não prova ausência de perdas intradiárias. Cobertura global PENDING.",
      "explain",
    ),
  );
  parent.append(p);
}
function comparison(parent) {
  const p = panel(
    synthetic()
      ? "Contas sintéticas independentes"
      : "Comparador na mesma janela",
    synthetic()
      ? "As trajetórias de preços fictícios diferem; não há benchmark pareado entre esses cenários."
      : `Referência: ${labels[state.reference]}. Diferenças em USDT, pontos percentuais e BTC; não há vencedora geral.`,
  );
  const rows =
      payload.comparison?.rows || payload.accounts.map((a) => a.summary),
    ext = payload.comparison?.extrema;
  function value(row, key, formatter) {
    const span = el("span", formatter(row[key]));
    if (ext && ext[key]) {
      const min = ext[key].minimum.includes(row.policy),
        max = ext[key].maximum.includes(row.policy);
      if (max || min)
        span.append(
          el(
            "small",
            max && min ? " = empate" : max ? " ↑ maior" : " ↓ menor",
            "extremum",
          ),
        );
    }
    return span;
  }
  table(
    p,
    [
      "Política",
      "NAV USDT",
      "Retorno",
      "BTC físico",
      "BTC equivalente",
      "Caixa USDT",
      "DD máximo",
      "Exposição média",
      "Fees USDT",
      "ΔNAV USDT",
      "Δretorno pp",
      "ΔBTC",
    ],
    rows.map((row) => [
      labels[row.policy] || row.policy,
      value(row, "nav_usdt", money),
      value(row, "return", pct),
      value(row, "btc_physical", coins),
      value(row, "btc_equivalent", coins),
      value(row, "cash_usdt", money),
      value(row, "max_drawdown", pct),
      value(row, "exposure_mean", pct),
      value(row, "fees_usdt", money),
      row.delta_nav_usdt == null ? "—" : money(row.delta_nav_usdt),
      row.delta_return_pp == null ? "—" : money(row.delta_return_pp),
      row.delta_btc == null ? "—" : coins(row.delta_btc),
    ]),
  );
  parent.append(p);
}
function visibleControls(parent) {
  if (synthetic()) return;
  const p = el("div", null, "series-controls");
  p.append(el("strong", "Políticas na comparação"));
  catalog.rows
    .filter(
      (r) =>
        r.start.slice(0, 10) === state.start &&
        String(r.months) === state.months &&
        r.cost === state.cost,
    )
    .forEach((row) => {
      const label = el("label"),
        input = el("input");
      input.type = "checkbox";
      input.checked = state.visible.includes(row.policy);
      input.disabled = row.policy === state.reference;
      input.setAttribute("aria-label", "Comparar " + labels[row.policy]);
      input.addEventListener("change", () => {
        state.visible = input.checked
          ? [...state.visible, row.policy]
          : state.visible.filter((x) => x !== row.policy);
        if (!state.visible.includes(state.policy))
          state.policy = state.reference;
        save();
        load();
      });
      label.append(input, el("span", labels[row.policy]));
      p.append(label);
    });
  parent.append(p);
}
function risk(parent, a) {
  drawChart(parent, "Drawdown observado · zero no topo", "drawdown", "%");
  const r = a.risk,
    details = panel(
      "Pico, vale e recuperação",
      "Limite de referência analítico, não mecanismo garantido de proteção. Durações são observadas entre marcas; não trajetórias intradiárias.",
    );
  const summary = payload.comparison?.rows.find(
    (r) => r.policy === a.summary.policy,
  );
  const dl = el("dl");
  [
    ["Pico UTC", r.max_drawdown_peak || "Sem drawdown"],
    ["Vale UTC", r.max_drawdown_trough || "Sem drawdown"],
    [
      "NAV no pico",
      r.peak_nav_usdt == null
        ? "Não aplicável"
        : money(r.peak_nav_usdt) + " USDT",
    ],
    [
      "NAV no vale",
      r.trough_nav_usdt == null
        ? "Não aplicável"
        : money(r.trough_nav_usdt) + " USDT",
    ],
    [
      "Recuperação",
      r.recovery_at ||
        (r.recovery_censored
          ? "Não observada · censurada no endpoint"
          : "Sem queda"),
    ],
    [
      "Maior episódio observado",
      money(r.longest_episode_seconds / 86400) + " dias",
    ],
    [
      "Amostragem abaixo do pico",
      money(r.sampled_underwater_seconds_left / 86400) +
        " dias · amostra à esquerda",
    ],
    [
      "Excesso acima de 20%",
      summary
        ? money(summary.risk_excess_pp) + " pp"
        : r.violates_20_percent
          ? "Violação no cenário sintético"
          : "Sem excesso observado",
    ],
  ].forEach(([k, v]) => dl.append(el("dt", k), el("dd", v)));
  details.append(dl);
  parent.append(details);
  if (payload.frequencies) {
    const f = panel(
      "Violações em todas as entradas disponíveis",
      "Mesmo horizonte e custo. Contagens históricas não estimam probabilidades futuras.",
    );
    table(
      f,
      ["Política", "Violações / janelas"],
      payload.frequencies.map((r) => [
        labels[r.policy],
        r.violations + " / " + r.observations,
      ]),
    );
    parent.append(f);
  }
  drawChart(parent, "Exposição ao BTC nas marcas observadas", "exposure", "%");
}
function btc(parent) {
  const pair = el("div", null, "chart-grid");
  parent.append(pair);
  drawChart(pair, "BTC físico líquido · sem CORE pessoal", "btc", "BTC");
  drawChart(
    pair,
    "BTC equivalente · NAV dividido pelo mark",
    "btc_equivalent",
    "BTC",
  );
  const p = panel(
    "BTC físico, poder de compra e patrimônio",
    "BTC físico são moedas líquidas na carteira simulada. BTC equivalente expressa NAV / mark e não adiciona moedas. NAV é patrimônio total em USDT.",
  );
  const gaps =
    payload.comparison?.rows.filter((r) => r.more_btc_less_nav) || [];
  if (gaps.length) {
    for (const row of gaps) {
      p.append(
        el(
          "p",
          `${labels[row.policy]} tem ${coins(row.delta_btc)} BTC a mais que ${labels[state.reference]}, mas NAV ${money(row.delta_nav_usdt)} USDT menor: o valor dos BTC adicionais é ${money(row.btc_mark_component_usdt)} USDT, enquanto a diferença de caixa é ${money(row.delta_cash_usdt)} USDT.`,
        ),
      );
    }
  } else
    p.append(
      el(
        "p",
        "Nesta seleção não há caso de mais BTC e menor NAV contra a referência escolhida. Compare sempre o mesmo instante e mark.",
      ),
    );
  parent.append(p);
  drawChart(
    parent,
    "Caixa USDT · reservas não somadas novamente",
    "cash",
    "USDT",
  );
}
function explorer(parent) {
  const p = panel(
    "Consultar janelas existentes",
    "Pesquisa retrospectiva. Ordenação descreve resultados conhecidos; não seleciona política para o futuro. Custos e horizontes continuam separados.",
  );
  const toolbar = el("div", null, "explorer-tools"),
    input = el("input");
  input.type = "search";
  input.placeholder = "Pesquisar data ou ID da política";
  input.setAttribute("aria-label", "Pesquisar janelas");
  input.value = search;
  const ordering = el("select");
  ordering.setAttribute("aria-label", "Ordenar janelas");
  [
    ["start", "Data inicial"],
    ["nav_usdt", "NAV"],
    ["return", "Retorno"],
    ["max_drawdown", "Drawdown"],
    ["btc_physical", "BTC físico"],
  ].forEach(([v, t]) => {
    const o = el("option", t);
    o.value = v;
    ordering.append(o);
  });
  ordering.value = sort;
  const desc = button(
    descending ? "Ordem decrescente" : "Ordem crescente",
    () => {
      descending = !descending;
      offset = 0;
      render();
    },
    "secondary",
  );
  const applySearch = () => {
    search = input.value;
    offset = 0;
    render();
  };
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") applySearch();
  });
  const searchButton = button("Pesquisar", applySearch, "secondary");
  ordering.addEventListener("change", () => {
    sort = ordering.value;
    offset = 0;
    render();
  });
  toolbar.append(input, searchButton, ordering, desc);
  p.append(toolbar);
  const rows = synthetic()
    ? payload.accounts.map((a) => a.summary)
    : catalog.rows.filter(
        (r) =>
          String(r.months) === state.months &&
          r.cost === state.cost &&
          state.visible.includes(r.policy),
      );
  const ordered = GridState.orderedRows(rows, search, sort, descending),
    shown = ordered.slice(offset, offset + 18);
  p.append(
    el(
      "p",
      `${ordered.length} resultados existentes · exibindo ${ordered.length ? offset + 1 : 0}–${Math.min(offset + 18, ordered.length)}. Nenhuma janela nova foi gerada.`,
    ),
  );
  table(
    p,
    [
      "Início UTC",
      "Política",
      "Horizonte",
      "Custo",
      "NAV USDT",
      "Retorno",
      "DD máximo",
      "20%",
    ],
    shown.map((r) => [
      r.start.slice(0, 10),
      labels[r.policy] || r.policy,
      r.months ? r.months + " meses" : "3 minutos sintéticos",
      r.cost,
      money(r.nav_usdt),
      pct(r.return),
      pct(r.max_drawdown),
      r.violates_20_percent ? "EXCEDEU" : "Dentro observado",
    ]),
  );
  const prev = button(
      "Anterior",
      () => {
        offset = Math.max(0, offset - 18);
        render();
      },
      "secondary",
    ),
    next = button(
      "Próxima",
      () => {
        offset += 18;
        render();
      },
      "secondary",
    );
  prev.disabled = offset === 0;
  next.disabled = offset + 18 >= ordered.length;
  p.append(prev, next);
  parent.append(p);
  const d = payload.distributions;
  if (!d || d.status === "UNAVAILABLE") {
    parent.append(
      panel(
        "Distribuições novas indisponíveis para o acervo interno",
        "O item G2-E limita novas análises a artefatos públicos auditados ou sintéticos. O corpus M1 não foi copiado. A consulta local continua disponível; selecione a fonte sintética para demonstrar distribuições explicitamente fictícias.",
      ),
    );
    return;
  }
  const dist = panel(
    "Distribuições · SYNTHETIC_DEMO",
    `${d.observations} cenários fictícios, não uma campanha histórica e não amostra para inferência.`,
  );
  for (const [key, title] of [
    ["return", "Retornos"],
    ["max_drawdown", "Drawdowns"],
  ]) {
    GridCharts.histogram(dist, d[key].bins, title);
    dist.append(
      el("h3", title),
      el(
        "p",
        `Positivos: ${d[key].positive}; negativos: ${d[key].negative}; zeros: ${d[key].zero}.`,
      ),
    );
    table(
      dist,
      ["Faixa inferior", "Faixa superior", "Contagem"],
      d[key].bins.map((b) => [pct(b.low), pct(b.high), b.count]),
    );
  }
  parent.append(dist);
}
function demo(parent, a) {
  const p = panel(
    "Linha do tempo PAPER",
    "Intenções e reservas não são ativos adicionais. Fills e fees são os eventos executados no motor sintético existente.",
  );
  p.append(el("p", a.conservation, "verified"));
  table(
    p,
    ["Revisão", "Evento"],
    a.events.map((e) => [e.revision, e.kind]),
  );
  table(
    p,
    ["UTC", "Ordem simulada", "Lado", "BTC", "Preço fictício USDT", "Fee USDT"],
    a.fills.map((f) => [
      f.time,
      f.order_ref,
      f.side,
      f.btc,
      f.price,
      f.fee_usdt,
    ]),
  );
  table(
    p,
    [
      "UTC",
      "Preço fictício",
      "Disponível USDT",
      "Reservado USDT",
      "BTC líquido",
      "NAV USDT",
    ],
    a.series.map((s) => [
      s.time,
      s.price,
      s.available_usdt,
      s.reserved_usdt,
      s.btc,
      s.nav,
    ]),
  );
  parent.append(p);
}
async function download(format) {
  try {
    let url = synthetic()
      ? "/api/demo" + (format === "csv" ? ".csv" : "")
      : (format === "csv" ? "/api/export.csv?" : "/api/export?") + query();
    const response = await fetch(url, {
      credentials: "same-origin",
      cache: "no-store",
    });
    if (!response.ok) throw new Error("Exportação recusada por integridade.");
    const blob = await response.blob(),
      link = el("a");
    link.href = URL.createObjectURL(blob);
    link.download = "gridbot-selection." + format;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  } catch (e) {
    $("status").textContent = e.message;
  }
}
function render() {
  controls();
  $("title").textContent = titles[state.page];
  $("subtitle").textContent = synthetic()
    ? "SYNTHETIC_DEMO · contas fictícias independentes · PAPER / OFFLINE"
    : "Evidência arquivada, comparação equivalente e risco explícito.";
  document.querySelectorAll("nav button").forEach((b) => {
    b.classList.toggle("active", b.dataset.page === state.page);
    b.setAttribute(
      "aria-current",
      b.dataset.page === state.page ? "page" : "false",
    );
  });
  const content = $("content");
  content.replaceChildren();
  $("status").className = error ? "status error" : "status";
  $("status").textContent = loading
    ? "Validando origem, hashes e seleção…"
    : error
      ? "Evidência recusada · " + error
      : payload.accounts.length
        ? `${synthetic() ? "SYNTHETIC_DEMO" : "ARCHIVED_RESEARCH_RESULT"} · ${payload.accounts[0].summary.start} → ${payload.accounts[0].summary.end} · ${payload.accounts.length} contas`
        : catalog.archive_integrity || "Dados indisponíveis";
  content.setAttribute("aria-busy", String(loading));
  if (loading) {
    content.append(
      panel(
        "Carregando evidências",
        "Aguarde a validação. Nenhum valor da seleção anterior é exibido sob os novos filtros.",
      ),
    );
    return;
  }
  if (error || (catalog.archive_reason && !synthetic())) {
    empty(content);
    return;
  }
  if (state.page === "overview") {
    overview(content);
    return;
  }
  if (synthetic() && !payload.accounts.length && !error) {
    const p = panel(
      "Demonstração determinística existente",
      "100 USDT por conta. Preços fictícios, sem credenciais, candles históricos ou conexão à exchange.",
    );
    const run = button("Executar cenários sintéticos", () => {
      demoLoaded = true;
      load(true);
    });
    p.append(run);
    content.append(p);
    return;
  }
  if (!payload.accounts.length) {
    empty(content);
    return;
  }
  const account =
      payload.accounts.find((a) => a.summary.policy === selected()) ||
      payload.accounts[0],
    s = account.summary,
    r = account.risk;
  const cards = el("div", null, "metrics");
  metric(
    cards,
    "NAV final",
    money(s.nav_usdt) + " USDT",
    "Inicial: " + money(s.initial_usdt) + " USDT",
  );
  metric(
    cards,
    "Retorno",
    pct(s.return),
    "Sobre o capital inicial",
    Number(s.return) < 0 ? "negative" : "positive",
  );
  metric(
    cards,
    "BTC físico",
    coins(s.btc_physical),
    "Moedas líquidas; BTCeq é outra medida",
  );
  metric(
    cards,
    "Drawdown máximo",
    pct(r.max_drawdown_magnitude),
    r.violates_20_percent
      ? "EXCEDEU 20% observados"
      : "Dentro dos 20% observados",
    r.violates_20_percent ? "negative" : "positive",
  );
  content.append(cards);
  visibleControls(content);
  if (state.page === "wealth" || state.page === "demo") {
    const tools = el("div", null, "chart-tools");
    tools.append(
      button(
        zoom
          ? "Usar domínio desde zero"
          : "Ajustar domínio Y · corte identificado",
        () => {
          zoom = !zoom;
          render();
        },
        "secondary",
      ),
    );
    content.append(tools);
    drawChart(content, "Patrimônio marcado · USDT", "nav", "USDT");
    if (state.page === "wealth") {
      const pair = el("div", null, "chart-grid");
      content.append(pair);
      drawChart(pair, "Retorno acumulado", "return", "%");
      drawChart(pair, "Exposição ao BTC", "exposure", "%");
    }
  }
  if (state.page === "btc") btc(content);
  if (state.page === "risk") risk(content, account);
  if (state.page === "windows") explorer(content);
  comparison(content);
  if (state.page === "demo") demo(content, account);
  const actions = el("div", null, "export-actions");
  actions.append(
    button("Baixar tabela CSV", () => download("csv"), "secondary"),
    button("Baixar seleção JSON", () => download("json"), "secondary"),
  );
  content.append(actions);
  const provenanceDetails = el("details");
  provenanceDetails.append(
    el("summary", "Origem, integridade e limites desta seleção"),
  );
  provenance(provenanceDetails);
  content.append(provenanceDetails);
}
document
  .querySelectorAll("nav button")
  .forEach((b) => b.addEventListener("click", () => navigate(b.dataset.page)));
document.querySelector(".brand").addEventListener("click", (e) => {
  e.preventDefault();
  navigate("overview");
});
["source", "start", "months", "cost", "reference"].forEach((key) =>
  $(key).addEventListener("change", () => {
    state[key] = $(key).value;
    offset = 0;
    state = GridState.validSelection(state, catalog.rows);
    save();
    load(synthetic() && demoLoaded);
  }),
);
$("policy").addEventListener("change", () => {
  state.policy = $("policy").value;
  const needsLoad = !state.visible.includes(state.policy);
  if (needsLoad) state.visible.push(state.policy);
  save();
  if (needsLoad) load();
  else render();
});
$("demo-policy").addEventListener("change", () => {
  demoPolicy = $("demo-policy").value;
  render();
});
$("reset").addEventListener("click", () => {
  state = GridState.validSelection(
    { ...GridState.defaults, page: state.page },
    catalog.rows,
  );
  search = "";
  offset = 0;
  save();
  load();
});
api("/api/catalog")
  .then((c) => {
    catalog = c;
    state = GridState.validSelection(state, c.rows);
    $("version").textContent = c.version;
    load(synthetic() && demoLoaded);
  })
  .catch((e) => {
    error = e.message;
    render();
  });
