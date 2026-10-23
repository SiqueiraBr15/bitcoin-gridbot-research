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
const colors = [
  "#81adff",
  "#d1b3ff",
  "#e5c283",
  "#91a3ba",
  "#62ddbb",
  "#ff8b97",
];
const titles = {
  overview: "Visão geral",
  wealth: "Patrimônio",
  btc: "Acumulação de BTC",
  risk: "Risco e drawdown",
  windows: "Janelas históricas",
  demo: "Demonstração PAPER",
};
let catalog,
  accounts = [],
  page = "overview",
  generation = 0,
  demoReady = false;
const money = (x) =>
  x == null
    ? "Dados indisponíveis"
    : Number(x).toLocaleString("pt-BR", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      });
const coins = (x) =>
  x == null
    ? "Dados indisponíveis"
    : Number(x).toLocaleString("pt-BR", {
        minimumFractionDigits: 5,
        maximumFractionDigits: 8,
      });
const percent = (x) =>
  x == null ? "Dados indisponíveis" : money(Number(x) * 100) + "%";
const node = (tag, text, cls) => {
  const e = document.createElement(tag);
  if (text != null) e.textContent = text;
  if (cls) e.className = cls;
  return e;
};
async function api(url) {
  const r = await fetch(url, { credentials: "same-origin", cache: "no-store" });
  if (!r.ok) throw new Error("Dados indisponíveis ou integridade inválida");
  return r.json();
}
function options(id, values, preferred) {
  const e = $(id),
    before = preferred || e.value;
  e.replaceChildren(
    ...values.map((v) => {
      const o = node("option", labels[v] || v);
      o.value = v;
      return o;
    }),
  );
  if (values.includes(before)) e.value = before;
}
function dates() {
  const rows = catalog.rows.filter(
    (r) => String(r.months) === $("months").value && r.cost === $("cost").value,
  );
  options(
    "start",
    [...new Set(rows.map((r) => r.start.slice(0, 10)))],
    $("start").value || "2022-12-02",
  );
}
function card(container, label, value, detail, cls) {
  const c = node("div", null, "card");
  c.append(
    node("div", label, "label"),
    node("div", value, "value " + (cls || "")),
    node("small", detail),
  );
  container.append(c);
}
function panel(title, text) {
  const e = node("section", null, "panel");
  e.append(node("h2", title));
  if (text) e.append(node("p", text));
  return e;
}
function table(container, headers, rows) {
  const w = node("div", null, "table-wrap"),
    t = node("table"),
    head = node("thead"),
    tr = node("tr");
  headers.forEach((h) => tr.append(node("th", h)));
  head.append(tr);
  t.append(head);
  const body = node("tbody");
  rows.forEach((row) => {
    const r = node("tr");
    row.forEach((c) => r.append(node("td", String(c))));
    body.append(r);
  });
  t.append(body);
  w.append(t);
  container.append(w);
}
function chart(container, title, field, unit, selectedOnly = false) {
  const p = panel(
      title,
      "Passe o cursor para consultar somente marcações observadas. Lacunas maiores que um dia ficam desconectadas.",
    ),
    box = node("div", null, "chart"),
    legend = node("div", null, "legend");
  const shown = selectedOnly
    ? accounts.filter((a) => a.summary.policy === $("policy").value)
    : accounts;
  const ns = "http://www.w3.org/2000/svg",
    svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 900 300");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", title);
  const points = shown.flatMap((a) => a.series),
    ys = points.map((p) => Number(p[field]));
  if (!ys.length) {
    p.append(node("p", "Dados indisponíveis"));
    container.append(p);
    return;
  }
  const xmin = Math.min(...points.map((p) => Date.parse(p.time))),
    xmax = Math.max(...points.map((p) => Date.parse(p.time)));
  let ymin = Math.min(...ys),
    ymax = Math.max(...ys);
  if (field === "drawdown") {
    ymin = Math.min(ymin, -0.2);
    ymax = 0;
  }
  const pad = (ymax - ymin || 1) * 0.09;
  ymin -= pad;
  ymax += pad;
  const xx = (t) => 60 + ((Date.parse(t) - xmin) / (xmax - xmin || 1)) * 820,
    yy = (v) => 255 - ((v - ymin) / (ymax - ymin)) * 230;
  function shape(tag, attrs) {
    const el = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
    svg.append(el);
    return el;
  }
  for (let i = 0; i < 5; i++) {
    const value = ymin + ((ymax - ymin) * i) / 4,
      y = yy(value);
    shape("line", { x1: 60, x2: 880, y1: y, y2: y, stroke: "#263248" });
    const text = shape("text", { x: 52, y: y + 4, "text-anchor": "end" });
    text.textContent =
      unit === "%"
        ? money(value * 100)
        : unit === "BTC"
          ? coins(value)
          : money(value);
  }
  if (field === "drawdown") {
    shape("line", {
      x1: 60,
      x2: 880,
      y1: yy(-0.2),
      y2: yy(-0.2),
      stroke: "#ff8b97",
      "stroke-dasharray": "6 4",
    });
    shape("text", { x: 65, y: yy(-0.2) - 6 }).textContent =
      "−20% · referência indicativa";
  }
  shown.forEach((a, i) => {
    const color = colors[i % colors.length];
    legend.append(
      node(
        "span",
        labels[a.summary.policy] || a.summary.policy,
        "legend-color c" + (i % 6),
      ),
    );
    let chunk = [];
    const draw = () => {
      if (chunk.length)
        shape("polyline", {
          points: chunk
            .map((p) => `${xx(p.time)},${yy(Number(p[field]))}`)
            .join(" "),
          fill: "none",
          stroke: color,
          "stroke-width": a.summary.policy === $("policy").value ? 3 : 1.6,
        });
      chunk = [];
    };
    a.series.forEach((p, j) => {
      if (j && Date.parse(p.time) - Date.parse(a.series[j - 1].time) > 86400000)
        draw();
      chunk.push(p);
    });
    draw();
  });
  shape("text", { x: 60, y: 285 }).textContent = new Date(xmin)
    .toISOString()
    .slice(0, 10);
  shape("text", { x: 880, y: 285, "text-anchor": "end" }).textContent =
    new Date(xmax).toISOString().slice(0, 10);
  const readout = node(
      "div",
      "Selecione uma política para consultar os pontos.",
      "readout",
    ),
    cursor = shape("line", {
      x1: 60,
      x2: 60,
      y1: 20,
      y2: 255,
      stroke: "#ffffff",
      "stroke-opacity": 0.3,
    });
  svg.addEventListener("pointermove", (event) => {
    const rect = svg.getBoundingClientRect(),
      x = ((event.clientX - rect.left) / rect.width) * 900;
    const a =
      shown.find((a) => a.summary.policy === $("policy").value) || shown[0];
    let nearest = a.series[0];
    a.series.forEach((p) => {
      if (Math.abs(xx(p.time) - x) < Math.abs(xx(nearest.time) - x))
        nearest = p;
    });
    cursor.setAttribute("x1", xx(nearest.time));
    cursor.setAttribute("x2", xx(nearest.time));
    readout.textContent = `${nearest.time} · ${labels[a.summary.policy] || a.summary.policy}: ${unit === "%" ? percent(nearest[field]) : unit === "BTC" ? coins(nearest[field]) : money(nearest[field])} ${unit === "%" ? "" : unit}`;
  });
  box.append(svg, readout);
  p.append(legend, box);
  container.append(p);
}
function render() {
  const content = $("content");
  content.replaceChildren();
  $("title").textContent = titles[page];
  $("subtitle").textContent =
    page === "demo"
      ? "Dois cenários fictícios, com conservação e replay verificáveis."
      : "Consulte evidências arquivadas; compare a mesma janela e o mesmo custo.";
  document
    .querySelectorAll("nav button")
    .forEach((b) => b.classList.toggle("active", b.dataset.page === page));
  const synthetic = $("source").value === "demo";
  $("start").disabled = $("months").disabled = $("cost").disabled = synthetic;
  $("status").textContent = synthetic
    ? "SYNTHETIC_DEMO · preços fictícios · contas independentes"
    : accounts.length
      ? `ARCHIVED_RESEARCH_RESULT · ${accounts[0].summary.start.slice(0, 10)} → ${accounts[0].summary.end.slice(0, 10)} · UTC · ${accounts[0].series.length} marcas por conta · hashes e NAV conferidos`
      : "UNAVAILABLE · dados indisponíveis · " + catalog.archive_integrity;
  if (page === "overview") {
    const c = node("div", null, "cards");
    card(c, "Modo de execução", "PAPER", "Sem operações reais");
    card(
      c,
      "Resultados arquivados",
      String(catalog.rows.length),
      "Somente resultados admitidos",
    );
    card(
      c,
      "Última pesquisa",
      catalog.research_date || "Indisponível",
      "Data do relatório, não de importação",
    );
    card(c, "Referência de risco", "20%", "Não é mecanismo de proteção");
    content.append(c);
    const p = panel(
      "O que a pesquisa demonstrou",
      "GRID tradicional, GRID persistente e rebalanceamento por bandas não demonstraram vantagem robusta suficiente sobre benchmarks simples.",
    );
    p.append(
      node(
        "p",
        "Nenhuma política com BTC respeitou 20% de drawdown em todas as janelas M1. Menos violações históricas não significa segurança operacional.",
      ),
    );
    content.append(p);
    const q = panel(
      "Fontes e integridade",
      "M1 / M1.R: resultados retrospectivos, com datas e horizontes sobrepostos. M2: revisão do conflito entre crescimento, BTC e risco. R1: vantagem das bandas não demonstrada.",
    );
    q.append(
      node(
        "p",
        `Arquivo: ${catalog.archive_integrity}. Matrizes são conferidas ao abrir; curvas selecionadas são verificadas antes de aparecer. Fonte ausente nunca é substituída por uma curva histórica inventada.`,
      ),
      node(
        "p",
        "Comparadores M1: comprar e manter, 50/50 passivo, DCA, caixa, bandas e mensal. CA/CX2/CB mantêm os contratos de execução arquivados; custos não são condições futuras garantidas.",
      ),
      node(
        "p",
        "Cobertura global PENDING. CORE e V2 permanecem congelados. Nenhum dado prospectivo é coletado.",
      ),
    );
    content.append(q);
    return;
  }
  if (page === "demo" && !demoReady) {
    const p = panel(
      "Execute a demonstração sintética",
      "100 USDT iniciais por conta. Preços deliberadamente fictícios. Reutiliza a demonstração PAPER existente, sem candles históricos ou chamadas de rede.",
    );
    const b = node("button", "Executar cenários sintéticos", "action");
    b.addEventListener("click", async () => {
      b.disabled = true;
      try {
        const result = await api("/api/demo");
        accounts = result.accounts;
        demoReady = true;
        $("source").value = "demo";
        options(
          "policy",
          accounts.map((a) => a.summary.policy),
        );
        render();
      } catch (e) {
        $("status").textContent = e.message;
        b.disabled = false;
      }
    });
    p.append(b);
    content.append(p);
    return;
  }
  if (!accounts.length) {
    const empty = node("section", null, "empty");
    empty.append(
      node("h2", "Dados indisponíveis"),
      node(
        "p",
        "Autorize uma origem arquivada no comando local ou abra Demonstração PAPER. Nenhum histórico é copiado automaticamente.",
      ),
    );
    content.append(empty);
    return;
  }
  const a =
      accounts.find((a) => a.summary.policy === $("policy").value) ||
      accounts[0],
    s = a.summary,
    r = a.risk;
  const cards = node("div", null, "cards");
  card(
    cards,
    "NAV final",
    money(s.nav_usdt) + " USDT",
    "Inicial: " + money(s.initial_usdt),
  );
  card(
    cards,
    "Retorno acumulado",
    percent(a.series.at(-1).return),
    "Sobre o capital inicial",
    Number(a.series.at(-1).return) < 0 ? "negative" : "positive",
  );
  card(
    cards,
    "BTC físico",
    coins(s.btc_physical),
    "Moedas líquidas, sem somar reservas",
  );
  card(
    cards,
    "Drawdown máximo",
    percent(r.max_drawdown_magnitude),
    r.violates_20_percent
      ? "EXCEDEU 20% observados"
      : "Dentro de 20% observados",
    r.violates_20_percent ? "negative" : "positive",
  );
  content.append(cards);
  if (page === "wealth" || page === "windows" || page === "demo") {
    chart(content, "Patrimônio marcado · USDT", "nav", "USDT");
    if (page === "wealth")
      chart(
        content,
        "Retorno acumulado · capital inicial incluído",
        "return",
        "%",
      );
  }
  if (page === "btc") {
    chart(content, "BTC físico líquido", "btc", "BTC");
    chart(content, "BTC equivalente patrimonial", "btc_equivalent", "BTC");
    chart(content, "Caixa em USDT", "cash", "USDT");
    const p = panel(
      "Quantidade de moedas e patrimônio são medidas diferentes",
      "NAV = caixa USDT + BTC físico × preço. BTC equivalente = NAV / preço; ele não adiciona moedas à carteira.",
    );
    p.append(
      node(
        "p",
        "Na mesma janela, mais BTC pode vir acompanhado de menos caixa e menor NAV. Para a comparação pareada: ΔNAV = preço final × ΔBTC + Δcaixa. Se ambas tiverem o mesmo BTC e caixa não negativo frente a uma carteira só de BTC, menor NAV exigiria investigar os dados.",
      ),
    );
    content.append(p);
  }
  if (page === "risk") {
    chart(content, "Drawdown em relação ao pico observado", "drawdown", "%");
    chart(content, "Exposição observada ao BTC", "exposure", "%");
    const p = panel(
      "Episódio do drawdown máximo",
      "Marcações diárias e capital inicial incluídos. Empates, igualdade na recuperação e censura seguem M1.R; não há inferência intradiária.",
    );
    const dl = node("dl");
    for (const [k, v] of [
      ["Pico", r.max_drawdown_peak],
      ["Vale", r.max_drawdown_trough],
      ["NAV no pico", r.peak_nav_usdt],
      ["NAV no vale", r.trough_nav_usdt],
      [
        "Recuperação",
        r.recovery_at ||
          (r.recovery_censored ? "Censurada no fim da janela" : "Sem queda"),
      ],
      [
        "Maior episódio observado",
        money(r.longest_episode_seconds / 86400) + " dias",
      ],
      [
        "Tempo amostral abaixo do pico",
        money(r.sampled_underwater_seconds_left / 86400) +
          " dias (amostra à esquerda)",
      ],
    ]) {
      dl.append(node("dt", k), node("dd", v || "Sem queda"));
    }
    p.append(dl);
    content.append(p);
    if (!synthetic) {
      const q = panel(
        "Frequência histórica de violações",
        "Mesmo horizonte e custo selecionados, todas as datas arquivadas. Janelas se sobrepõem: contagens não são probabilidades futuras ou recomendações.",
      );
      const rows = Object.keys(labels)
        .filter((k) => k.startsWith("B") || k.startsWith("P_"))
        .map((policy) => {
          const rows = catalog.rows.filter(
            (r) =>
              r.policy === policy &&
              String(r.months) === $("months").value &&
              r.cost === $("cost").value,
          );
          return [
            labels[policy],
            rows.filter((r) => r.violates_20_percent).length +
              " / " +
              rows.length,
          ];
        });
      table(q, ["Política", "Violações / janelas"], rows);
      content.append(q);
    }
  }
  const comparison = panel(
    "Comparação na mesma janela",
    synthetic
      ? "Contas sintéticas independentes; não representam estratégias históricas."
      : "M1 retrospectiva · janelas sobrepostas · valores líquidos de fees modeladas, sem liquidação final, impostos ou risco USDT.",
  );
  table(
    comparison,
    [
      "Política",
      "NAV USDT",
      "BTC físico",
      "BTC equivalente",
      "Caixa USDT",
      "Fees USDT",
      "DD máximo",
      "Exposição média",
    ],
    accounts.map((a) => {
      const s = a.summary;
      return [
        labels[s.policy] || s.policy,
        money(s.nav_usdt),
        coins(s.btc_physical),
        coins(s.btc_equivalent),
        money(s.cash_usdt),
        money(s.fees_usdt),
        percent(a.risk.max_drawdown_magnitude),
        percent(s.exposure_mean),
      ];
    }),
  );
  content.append(comparison);
  if (a.benchmark_gaps) {
    const gaps = panel(
      "Diferenças pareadas de patrimônio e retorno",
      "Política selecionada menos benchmark, no mesmo período, capital e preço final. Sem combinar janelas.",
    );
    table(
      gaps,
      ["Benchmark", "ΔNAV USDT", "Δretorno pp", "ΔBTC físico", "Δcaixa USDT"],
      Object.entries(a.benchmark_gaps).map(([key, g]) => [
        labels[key],
        money(g.nav_usdt),
        money(g.return_pp),
        coins(g.btc_physical),
        money(g.cash_usdt),
      ]),
    );
    content.append(gaps);
  }
  if (page === "demo") {
    const p = panel("Eventos, fills e conservação", a.conservation);
    table(
      p,
      ["Revisão", "Evento"],
      a.events.map((e) => [e.revision, e.kind]),
    );
    table(
      p,
      [
        "Instante UTC",
        "Ordem PAPER",
        "Lado simulado",
        "BTC",
        "Preço USDT",
        "Fee USDT",
      ],
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
        "Marca UTC",
        "NAV USDT",
        "Disponível USDT",
        "Reservado USDT",
        "BTC líquido",
      ],
      a.series.map((p) => [
        p.time,
        p.nav,
        p.available_usdt,
        p.reserved_usdt,
        p.btc,
      ]),
    );
    content.append(p);
  }
  if (!synthetic) {
    const b = node("button", "Exportar esta janela · JSON local", "action");
    b.addEventListener("click", async () => {
      try {
        const r = await api("/api/export?" + query()),
          blob = new Blob([JSON.stringify(r, null, 2)], {
            type: "application/json",
          }),
          url = URL.createObjectURL(blob),
          a = node("a");
        a.href = url;
        a.download = "gridbot-selected-research.json";
        a.click();
        URL.revokeObjectURL(url);
      } catch (e) {
        $("status").textContent = e.message;
      }
    });
    content.append(b);
  }
}
function query() {
  return new URLSearchParams({
    start: $("start").value,
    months: $("months").value,
    cost: $("cost").value,
  });
}
async function load() {
  const token = ++generation;
  $("status").textContent = "Validando seleção e hashes…";
  try {
    let result;
    if ($("source").value === "demo") {
      if (!demoReady) {
        accounts = [];
        options("policy", []);
        render();
        return;
      }
      result = await api("/api/demo");
    } else if (catalog.rows.length && $("start").value) {
      result = await api("/api/selection?" + query());
    } else result = { accounts: [] };
    if (token !== generation) return;
    accounts = result.accounts;
    options(
      "policy",
      accounts.map((a) => a.summary.policy),
    );
    render();
  } catch (e) {
    if (token !== generation) return;
    accounts = [];
    render();
    $("status").textContent = "UNAVAILABLE · " + e.message;
  }
}
document.querySelectorAll("nav button").forEach((b) =>
  b.addEventListener("click", () => {
    page = b.dataset.page;
    if (page === "demo") {
      $("source").value = "demo";
      load();
    } else render();
  }),
);
["start", "months", "cost", "source"].forEach((id) =>
  $(id).addEventListener("change", () => {
    if (id === "months" || id === "cost") dates();
    if (id === "source") {
      if ($("source").value === "demo") page = "demo";
      else if (page === "demo") page = "wealth";
    }
    load();
  }),
);
$("policy").addEventListener("change", render);
api("/api/catalog")
  .then((c) => {
    catalog = c;
    $("version").textContent = c.version;
    dates();
    return load();
  })
  .catch(() => {
    $("status").textContent = "Console indisponível. Confira o processo local.";
  });
