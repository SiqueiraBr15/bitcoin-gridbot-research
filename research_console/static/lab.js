(function (global) {
  "use strict";
  const numbers =
    typeof module !== "undefined" && module.exports
      ? require("./numbers.js")
      : global.GridNumbers;
  const { NumericFormatError } = numbers;
  const model = {
    maxIntegerDigits: numbers.maxIntegerDigits,
    maxResponseBytes: numbers.maxResponseBytes,
    formatDecimal: numbers.formatDecimal,
    canPaint(target) {
      return !!target?.isConnected && target.classList.contains("research-lab");
    },
    filter(studies, query, kind, sort) {
      if (!["title", "start", "source_kind"].includes(sort)) sort = "title";
      return studies
        .filter(
          (s) =>
            (!kind || s.source_kind === kind) &&
            `${s.title} ${s.study_identity || ""} ${(s.policies || []).join(" ")}`
              .toLowerCase()
              .includes(query.toLowerCase()),
        )
        .sort(
          (a, b) =>
            String(a[sort] || "").localeCompare(String(b[sort] || "")) ||
            a.id.localeCompare(b.id),
        );
    },
  };
  if (typeof module !== "undefined" && module.exports) {
    module.exports = model;
    return;
  }
  const node = (tag, value, cls) => {
    const n = document.createElement(tag);
    if (value != null) n.textContent = String(value);
    if (cls) n.className = cls;
    return n;
  };
  const panel = (title, description) => {
    const p = node("section", null, "panel");
    p.append(node("h2", title));
    if (description) p.append(node("p", description, "explain"));
    return p;
  };
  const button = (label, action, cls = "action") => {
    const b = node("button", label, cls);
    b.type = "button";
    b.disabled = busy;
    b.addEventListener("click", () => {
      const target = root;
      try {
        const pending = action(),
          ticket = revision;
        Promise.resolve(pending).catch((error) => {
          if (
            ticket === revision &&
            root === target &&
            error?.name !== "AbortError"
          )
            showError(error);
        });
      } catch (error) {
        showError(error);
      }
    });
    return b;
  };
  const field = (label, control) => {
    const wrap = node("label", label);
    wrap.append(control);
    return wrap;
  };
  const table = (p, headers, rows) => {
    const wrap = node("div", null, "table-wrap"),
      t = node("table"),
      head = node("thead"),
      tr = node("tr");
    t.append(
      node(
        "caption",
        p.querySelector("h2")?.textContent || "Resultados",
        "sr-only",
      ),
    );
    headers.forEach((v) => {
      const th = node("th", v);
      th.scope = "col";
      tr.append(th);
    });
    head.append(tr);
    t.append(head);
    const body = node("tbody");
    rows.forEach((row) => {
      const r = node("tr");
      row.forEach((v) => {
        const td = node("td");
        if (v instanceof Node) td.append(v);
        else td.textContent = String(v ?? "Indisponível");
        r.append(td);
      });
      body.append(r);
    });
    t.append(body);
    wrap.append(t);
    p.append(wrap);
  };
  const fmt = (v, suffix = "") =>
    v == null ? "Indisponível" : String(v) + suffix;
  const present = (value, decimals = 8) => {
    if (value == null) return "Indisponível";
    const n = node("span", model.formatDecimal(value, decimals));
    n.title =
      value.length <= 512
        ? "Valor exato antes da formatação: " + value
        : "Representação exata longa; consulte a evidência da análise. Prefixo: " +
          value.slice(0, 240) +
          "…";
    return n;
  };
  let root,
    context,
    studies = [],
    analysis = null,
    study = null,
    preview = null,
    revision = 0;
  let query = "",
    kind = "",
    sort = "title",
    chosen = null,
    availableAccounts = [],
    objectives = ["nav_final", "btc_physical", "max_drawdown"],
    focus = "";
  let message = "",
    busy = false;
  let controller = new AbortController();
  try {
    const saved = JSON.parse(
      sessionStorage.getItem("gridbot.g4.filters") || "{}",
    );
    query = typeof saved.query === "string" ? saved.query.slice(0, 100) : "";
    kind = [
      "SYNTHETIC_DEMO",
      "ARCHIVED_RESEARCH_RESULT",
      "AGGREGATED_RESEARCH_SUMMARY",
      "DATA_INVALID",
    ].includes(saved.kind)
      ? saved.kind
      : "";
    sort = ["title", "start", "source_kind"].includes(saved.sort)
      ? saved.sort
      : "title";
  } catch {
    /* Invalid local preferences never become data authority. */
  }
  function save() {
    try {
      sessionStorage.setItem(
        "gridbot.g4.filters",
        JSON.stringify({ query, kind, sort }),
      );
    } catch {}
  }
  async function request(url, options = {}) {
    const response = await fetch(url, {
      ...options,
      credentials: "same-origin",
      signal: AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]),
    });
    if (!response.ok) {
      const problem = await response.json().catch(() => ({}));
      const descriptions = {
        INTEGRITY_MISMATCH: "O SHA-256 diverge ou o pack foi alterado.",
        SIZE_LIMIT: "O arquivo excede os limites de leitura ou descompressão.",
        UNSUPPORTED_VERSION: "A versão de schema não é suportada.",
        INCOMPATIBLE_BENCHMARK: "O benchmark não usa as mesmas condições.",
        NAV_CONSERVATION_FAILED: "NAV não corresponde ao caixa e BTC marcado.",
        INVALID_TIMESTAMPS: "Os timestamps não respeitam o contrato temporal.",
        PERSISTENCE_DISABLED: "Persistência não habilitada por --lab-dir.",
        PREVIEW_EXPIRED: "A prévia expirou; valide novamente.",
        CONFIRMATION_REQUIRED: "É necessária confirmação explícita.",
        EXPORT_RESTRICTED: "A permissão declarada impede esta exportação.",
        DATA_UNAVAILABLE: "A cópia local está indisponível.",
        LIBRARY_BUSY:
          "Outra instância está gravando nesta biblioteca. Tente novamente.",
        ANALYSIS_FAILED:
          "Falha interna na análise. A evidência não foi classificada como inválida.",
      };
      throw new Error(
        descriptions[problem.reason] ||
          (response.status >= 500
            ? "Falha interna do serviço de análise. Tente novamente."
            : "Schema ou dados inválidos. O pack exige manifesto e resultados válidos."),
      );
    }
    if (
      Number(response.headers.get("Content-Length") || 0) >
      model.maxResponseBytes
    )
      throw new Error("Resposta excede limite local.");
    return response;
  }
  async function json(url, options) {
    return (await request(url, options)).json();
  }
  function post(url, data) {
    return json(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-GridBot-Lab": "1" },
      body: JSON.stringify(data),
    });
  }
  function showError(error) {
    busy = false;
    if (error instanceof NumericFormatError) analysis = null;
    message = error?.message || "Não foi possível validar a evidência.";
    if (model.canPaint(root)) paint();
  }
  function params() {
    const p = new URLSearchParams({ id: study.id });
    if (chosen) p.set("accounts", chosen.join(","));
    p.set("objectives", objectives.join(","));
    return p;
  }
  async function selectStudy(s, keep = false) {
    controller.abort();
    controller = new AbortController();
    const ticket = ++revision;
    study = s;
    analysis = null;
    busy = true;
    message = "Validando pack e derivando métricas…";
    if (!keep) {
      chosen = null;
      focus = "";
      availableAccounts = [];
    }
    paint();
    try {
      const result = await json("/api/lab/analysis?" + params());
      if (ticket !== revision || !model.canPaint(root)) return;
      analysis = result;
      if (!keep) availableAccounts = result.accounts.map((a) => a.account_id);
      message =
        "Integridade validada · proveniência declarada, sem autenticação de autoria.";
    } catch (error) {
      if (ticket === revision) throw error;
    } finally {
      if (ticket === revision) {
        busy = false;
        if (model.canPaint(root)) paint();
      }
    }
  }
  async function refresh() {
    const ticket = revision;
    const data = await json("/api/lab/library");
    if (ticket !== revision || !model.canPaint(root)) return;
    studies = data.studies;
    context.persistence = data.persistence_enabled;
    context.archiveAdapter = data.archive_adapter;
    paint();
  }
  async function download(url, filename) {
    const ticket = revision;
    const blob = await (await request(url)).blob();
    if (ticket !== revision || !model.canPaint(root)) return;
    saveBlob(blob, filename);
  }
  function saveBlob(blob, filename) {
    const url = URL.createObjectURL(blob),
      a = node("a");
    a.href = url;
    a.download = filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function details(value) {
    const d = node("details"),
      summary = node(
        "summary",
        "Inspecionar identidades, unidades e restrições",
      );
    d.append(summary, node("pre", JSON.stringify(value, null, 2), "lab-json"));
    return d;
  }
  function imports(parent) {
    const box = panel(
      "Importação controlada",
      context.persistence
        ? "A prévia não persiste arquivos. Confirme explicitamente a cópia local após validar os metadados."
        : "Prévia em memória disponível. Para persistir, inicie com --lab-dir apontando para uma pasta nova ou exclusiva do laboratório.",
    );
    const file = node("input");
    file.type = "file";
    file.accept = ".gbpack,.zip";
    const pin = node("input");
    pin.type = "text";
    pin.maxLength = 64;
    pin.placeholder = "Opcional · fornecido por outra fonte";
    box.append(
      field("Evidence Pack local · limite 2 MiB", file),
      field("SHA-256 externo opcional", pin),
    );
    box.append(
      button("Validar prévia do arquivo", async () => {
        preview = null;
        const ticket = revision;
        const selected = file.files?.[0];
        if (!selected) throw new Error("Escolha um arquivo local.");
        if (selected.size > 2097152) throw new Error("O pack excede 2 MiB.");
        const expectedPin = pin.value.trim().toLowerCase();
        if (expectedPin && !/^[a-f0-9]{64}$/.test(expectedPin))
          throw new Error("SHA-256 externo inválido.");
        busy = true;
        message = "Lendo somente o arquivo escolhido…";
        paint();
        try {
          const data = await json("/api/lab/preview", {
            method: "POST",
            headers: {
              "Content-Type": "application/zip",
              "X-GridBot-Lab": "1",
            },
            body: await selected.arrayBuffer(),
          });
          if (ticket !== revision || !model.canPaint(root)) return;
          if (expectedPin && data.study.id !== expectedPin)
            throw new Error(
              "O SHA-256 externo diverge. Importação não confirmada.",
            );
          preview = data;
          message =
            "Prévia validada. Hash não comprova autoria. Confirme as permissões de uso.";
        } finally {
          if (ticket === revision) {
            busy = false;
            paint();
          }
        }
      }),
    );
    if (preview) {
      box.append(
        node("h3", "Prévia · " + preview.study.title),
        details(preview.study),
      );
      const confirm = node("input");
      confirm.type = "checkbox";
      box.append(
        field(
          "Confirmo persistir esta cópia na pasta exclusiva do laboratório",
          confirm,
        ),
      );
      const action = button("Confirmar importação local", async () => {
        if (!confirm.checked)
          throw new Error("Marque a confirmação explícita antes de persistir.");
        const ticket = revision,
          token = preview.preview_token;
        busy = true;
        paint();
        const imported = await post("/api/lab/confirm", {
          preview_token: token,
          confirmed: true,
        });
        if (ticket !== revision || !model.canPaint(root)) return;
        preview = null;
        await refresh();
        if (ticket !== revision || !model.canPaint(root)) return;
        await selectStudy(imported);
      });
      action.disabled = busy || !context.persistence;
      box.append(action);
    }
    parent.append(box);
  }
  function library(parent) {
    const box = panel(
      "Biblioteca de pesquisas",
      "Três packs pequenos de observações fictícias. Dados históricos só existem quando uma origem é autorizada explicitamente; resumos agregados não substituem séries.",
    );
    const search = node("input");
    search.type = "search";
    search.value = query;
    const type = node("select");
    [
      "",
      "SYNTHETIC_DEMO",
      "ARCHIVED_RESEARCH_RESULT",
      "AGGREGATED_RESEARCH_SUMMARY",
      "DATA_INVALID",
    ].forEach((v) => {
      const o = node("option", v || "Todas as fontes");
      o.value = v;
      type.append(o);
    });
    type.value = kind;
    const order = node("select");
    [
      ["title", "Nome"],
      ["start", "Data inicial"],
      ["source_kind", "Tipo de fonte"],
    ].forEach(([v, label]) => {
      const o = node("option", label);
      o.value = v;
      order.append(o);
    });
    order.value = sort;
    const filters = node("div", null, "lab-controls");
    filters.append(
      field("Buscar estudos", search),
      field("Filtrar fonte", type),
      field("Ordenar biblioteca", order),
    );
    box.append(filters);
    const listing = node("div", null, "lab-library");
    const update = () => {
      query = search.value;
      kind = type.value;
      sort = order.value;
      save();
      listing.replaceChildren();
      const visible = model.filter(studies, query, kind, sort);
      if (!visible.length)
        listing.append(
          node(
            "p",
            "DATA_UNAVAILABLE · nenhum estudo corresponde aos filtros.",
          ),
        );
      visible.forEach((s) => {
        const card = node("article", null, "lab-study");
        card.append(
          node("h3", s.title),
          node(
            "span",
            `${s.source_kind} · ${s.data_nature || "NATUREZA_INDISPONÍVEL"}`,
            "tag",
          ),
          node(
            "p",
            `${s.wallets ?? 0} carteiras · ${s.marks ?? 0} marcas · ${s.integrity}`,
          ),
          node(
            "p",
            `${(s.start || "").slice(0, 10)} → ${(s.end || "").slice(0, 10)} · UTC`,
          ),
        );
        const b = button("Analisar " + s.title, () => selectStudy(s));
        b.disabled = s.integrity !== "VALIDATED";
        card.append(b, details(s));
        if (s.export_scope === "RAW_AND_DERIVED")
          card.append(
            button(
              "Baixar Evidence Pack " + s.pack_id,
              () =>
                download(
                  "/api/lab/source?id=" + s.id,
                  "gridbot-" + s.pack_id + ".gbpack",
                ),
              "secondary",
            ),
          );
        if (s.deletable) {
          const consent = node("input");
          consent.type = "checkbox";
          card.append(
            field("Confirmo remover somente esta cópia local", consent),
          );
          card.append(
            button(
              "Remover cópia local",
              async () => {
                if (!consent.checked)
                  throw new Error("Confirme a remoção da cópia local.");
                const ticket = revision;
                busy = true;
                paint();
                await post("/api/lab/remove", { id: s.id, confirmed: true });
                if (ticket !== revision || !model.canPaint(root)) return;
                busy = false;
                if (study?.id === s.id) {
                  analysis = null;
                  study = null;
                }
                message =
                  "Cópia local removida. A origem escolhida não foi modificada.";
                await refresh();
              },
              "secondary",
            ),
          );
        }
        listing.append(card);
      });
    };
    search.addEventListener("input", update);
    type.addEventListener("change", update);
    order.addEventListener("change", update);
    update();
    box.append(listing);
    if (context.catalog?.archive_status === "ARCHIVED_RESEARCH_RESULT") {
      box.append(
        node(
          "p",
          "ARCHIVED_RESEARCH_RESULT · adaptador M1.R autorizado, somente leitura, sem redistribuição automática.",
        ),
        button("Examinar arquivo autorizado nas janelas", context.openArchive),
        details(context.archiveAdapter || {}),
      );
    } else
      box.append(
        node(
          "p",
          "DATA_UNAVAILABLE · corpus histórico não distribuído. Nenhuma busca por arquivos privados.",
        ),
      );
    parent.append(box);
  }
  function scatter(parent, rows) {
    const box = panel(
      "Trade-offs · NAV × drawdown",
      "Cada ponto é uma conta. Cores ou posições não significam vencedor global. Somente compare dentro do mesmo grupo validado.",
    );
    box.classList.add("lab-scatter");
    const ns = "http://www.w3.org/2000/svg",
      svg = document.createElementNS(ns, "svg");
    const width = Math.max(300, Math.min(720, root.clientWidth - 48)),
      left = 55,
      right = width - 20,
      span = right - left;
    svg.setAttribute("viewBox", `0 0 ${width} 310`);
    svg.setAttribute("role", "img");
    svg.setAttribute(
      "aria-label",
      "NAV final em USDT contra drawdown máximo observado",
    );
    const candidates = rows.filter((r) => r.metrics.max_drawdown != null);
    if (!candidates.length) {
      box.append(
        node(
          "p",
          "Risco incompleto ou amostragem insuficiente; gráfico não inferido.",
        ),
      );
      parent.append(box);
      return;
    }
    const maxNAV = Math.max(
        1,
        ...candidates.map((r) => Number(r.metrics.nav_final)),
      ),
      text = (x, y, value) => {
        const t = document.createElementNS(ns, "text");
        t.setAttribute("x", x);
        t.setAttribute("y", y);
        t.textContent = value;
        svg.append(t);
      };
    text(20, 24, "NAV final · USDT (desde zero)");
    text(20, 305, "Drawdown observado · 0% a 100%");
    text(4, 52, maxNAV.toLocaleString("pt-BR", { maximumFractionDigits: 2 }));
    text(20, 265, "0");
    text(55, 284, "0%");
    text(left + span / 2 - 10, 284, "50%");
    text(right - 30, 284, "100%");
    const riskLine = document.createElementNS(ns, "path");
    riskLine.setAttribute("d", `M${left + 0.2 * span} 40 V265`);
    riskLine.setAttribute("class", "lab-risk-line");
    svg.append(riskLine);
    text(left + 0.2 * span + 4, 74, "Referência 20%");
    const axis = document.createElementNS(ns, "path");
    axis.setAttribute("d", `M${left} 40 V265 H${right}`);
    axis.setAttribute("class", "lab-axis");
    svg.append(axis);
    candidates.forEach((r) => {
      const c = document.createElementNS(ns, "circle");
      c.setAttribute("cx", left + Number(r.metrics.max_drawdown) * span);
      c.setAttribute("cy", 265 - (Number(r.metrics.nav_final) / maxNAV) * 215);
      c.setAttribute("r", 7);
      c.setAttribute("tabindex", "0");
      c.setAttribute("class", "lab-dot");
      c.setAttribute(
        "aria-label",
        `${r.account_id}: NAV ${r.metrics.nav_final} USDT, drawdown ${r.metrics.max_drawdown}, grupo ${r.group_id}`,
      );
      const title = document.createElementNS(ns, "title");
      title.textContent = c.getAttribute("aria-label");
      c.append(title);
      svg.append(c);
    });
    box.append(svg);
    parent.append(box);
  }
  function results(parent) {
    if (!analysis) return;
    const summary = panel(
      "Análise · " + study.title,
      `${analysis.source_kind} · ${analysis.status}. Integridade SHA-256 e conservação; proveniência declarada, sem assinatura de autoria.`,
    );
    summary.append(
      node(
        "p",
        "Pareto: políticas não dominadas apenas em condições equivalentes. Não é recomendação nem evidência de desempenho futuro.",
      ),
    );
    const controls = node("div", null, "lab-controls");
    const accountChoices = node("fieldset");
    accountChoices.append(node("legend", "Contas incluídas"));
    const originalIds = availableAccounts;
    const newChosen = new Set(chosen || originalIds);
    originalIds.forEach((id) => {
      const c = node("input");
      c.type = "checkbox";
      c.checked = newChosen.has(id);
      c.addEventListener("change", () => {
        if (c.checked) newChosen.add(id);
        else newChosen.delete(id);
      });
      accountChoices.append(field(id, c));
    });
    const objectiveChoices = node("fieldset");
    objectiveChoices.append(node("legend", "Objetivos de Pareto · sem pesos"));
    const nextObjectives = new Set(objectives);
    [
      ["nav_final", "Maximizar NAV"],
      ["btc_physical", "Maximizar BTC físico"],
      ["max_drawdown", "Minimizar drawdown"],
      ["fees_usdt", "Minimizar taxas"],
    ].forEach(([key, title]) => {
      const c = node("input");
      c.type = "checkbox";
      c.checked = nextObjectives.has(key);
      c.addEventListener("change", () => {
        if (c.checked) nextObjectives.add(key);
        else nextObjectives.delete(key);
      });
      objectiveChoices.append(field(title, c));
    });
    controls.append(
      accountChoices,
      objectiveChoices,
      button("Aplicar seleção analítica", () => {
        if (!newChosen.size || !nextObjectives.size)
          throw new Error("Selecione ao menos uma conta e um objetivo.");
        chosen = [...newChosen].sort();
        objectives = [...nextObjectives].sort();
        return selectStudy(study, true);
      }),
    );
    summary.append(controls);
    table(
      summary,
      [
        "Conta",
        "NAV · USDT",
        "BTC físico",
        "BTC equivalente",
        "Retorno razão",
        "DD razão",
        "Fees · USDT",
        "Exposição média",
        "Grupo",
        "Não dominada",
      ],
      analysis.rows.map((r) => {
        const m = r.metrics;
        return [
          r.account_id,
          present(m.exact.nav_final, 2),
          present(m.exact.btc_physical),
          present(m.exact.btc_equivalent),
          present(m.exact.return_ratio, 6),
          present(m.exact.max_drawdown, 6),
          present(m.exact.fees_usdt),
          present(m.exact.exposure_mean_left, 6),
          r.group_id.slice(0, 10),
          analysis.pareto.non_dominated.includes(r.account_id)
            ? "Sim · neste grupo"
            : "Não ou evidência insuficiente",
        ];
      }),
    );
    table(
      summary,
      [
        "Conta",
        "Benchmark",
        "Estado",
        "Δ NAV · USDT",
        "Δ BTC",
        "Δ NAV relativo",
        "Δ BTC relativo",
      ],
      analysis.rows.map((r) => {
        const b = r.benchmark_comparison;
        return [
          r.account_id,
          r.benchmark,
          b.status,
          b.delta_nav,
          b.delta_btc,
          b.relative_nav,
          b.relative_btc,
        ];
      }),
    );
    if (analysis.aggregates.length)
      table(
        summary,
        ["Política", "Custo", "Observações", "Perdas", "Violações"],
        analysis.aggregates.map((a) => [
          a.policy,
          a.cost_scenario,
          a.observations,
          a.losses,
          a.violations,
        ]),
      );
    parent.append(summary);
    scatter(parent, analysis.rows);
    if (!focus || !analysis.rows.some((r) => r.account_id === focus))
      focus = analysis.rows[0]?.account_id || "";
    const select = node("select");
    analysis.rows.forEach((r) => {
      const o = node("option", r.account_id);
      o.value = r.account_id;
      select.append(o);
    });
    select.value = focus;
    select.addEventListener("change", () => {
      focus = select.value;
      paint();
    });
    const evidence = panel(
      "Risco e investigação de evidências",
      "Episódios delimitados por marcas observadas. Gaps encerram o segmento sem presumir recuperação. Marcação diária não revela perdas intradiárias.",
    );
    evidence.append(field("Conta para investigar", select));
    const row = analysis.rows.find((r) => r.account_id === focus);
    if (row) {
      const risk = row.metrics.risk;
      evidence.append(
        node(
          "p",
          `${risk.status} · distância para referência 20%: ${fmt(risk.distance_to_20_pp, " pp")} · ${risk.violates_20_percent === true ? "EXCEDEU 20% observados" : "Sem violação demonstrada neste recorte"}`,
        ),
      );
      const choices = node("select");
      risk.episodes.forEach((e, i) => {
        const o = node(
          "option",
          `${i + 1}: ${e.peak_at} → ${e.observed_end} · ${e.reason}`,
        );
        o.value = String(i);
        choices.append(o);
      });
      const target = node("pre", null, "lab-json");
      const showEpisode = () => {
        target.textContent = risk.episodes.length
          ? JSON.stringify(risk.episodes[Number(choices.value) || 0], null, 2)
          : "Sem episódio observado; evidência insuficiente ou série no pico.";
      };
      choices.addEventListener("change", showEpisode);
      evidence.append(field("Episódio observado", choices), target);
      showEpisode();
      evidence.append(
        details({
          source: row.evidence,
          exact_metrics: row.metrics.exact,
          sampling_seconds: risk.sampling_seconds,
          gaps: risk.gaps,
          formula:
            "NAV = caixa + BTC físico × marca; BTCeq = NAV ÷ marca; DD = NAV ÷ pico − 1",
          redistribution: analysis.redistribution,
        }),
      );
    }
    parent.append(evidence);
    if (analysis.accounts.length) {
      const converted = analysis.accounts.map((a) => {
        const row = analysis.rows.find((r) => r.account_id === a.account_id),
          m = row.metrics,
          last = a.points.at(-1);
        return {
          summary: {
            policy: a.account_id,
            initial_usdt: a.initial_nav,
            nav_usdt: last[4],
            btc_physical: last[3],
            cash_usdt: last[2],
            final_mark: last[1],
            btc_equivalent: m.btc_equivalent,
            return: m.return_ratio,
            fees_usdt: m.fees_usdt,
            max_drawdown: m.max_drawdown,
            exposure_mean: m.exposure_mean_left,
            marks_sha256: row.evidence.series_sha256,
          },
          series: a.points.map((p, i) => ({
            time: p[0],
            price: p[1],
            cash: p[2],
            btc: p[3],
            nav: p[4],
            drawdown: row.metrics.risk.drawdowns[i],
          })),
        };
      });
      const chartContext = {
        allow_series_export: analysis.export_scope === "RAW_AND_DERIVED",
        dataset_id: study.dataset_identity,
        manifest_sha256: analysis.manifest_sha256,
        source_kind: analysis.source_kind,
        focused_policy: focus,
        pack_sha256: analysis.pack_sha256,
        data_nature: analysis.data_nature,
        redistribution: analysis.redistribution,
        analytics_version: analysis.analytics_version,
        implementation_sha256: analysis.analysis_manifest.implementation_sha256,
        analysis_result_sha256:
          analysis.analysis_manifest.expected_result_sha256,
        sampling_seconds: study.sampling_seconds,
        risk_definition: "G4_SEGMENTED_HIGH_WATER_V1",
      };
      GridCharts.lineChart(parent, {
        accounts: converted,
        field: "nav",
        unit: "USDT",
        title: "Marcas validadas · NAV em USDT",
        selected: focus,
        labels: Object.create(null),
        context: chartContext,
      });
      const riskAccounts = converted.filter((a) =>
        a.series.every((p) => p.drawdown != null),
      );
      if (riskAccounts.length)
        GridCharts.lineChart(parent, {
          accounts: riskAccounts,
          field: "drawdown",
          unit: "%",
          title: "Drawdown nas marcas observadas · referência −20%",
          selected: focus,
          labels: Object.create(null),
          context: chartContext,
        });
    }
    const robustness = panel(
      "Robustez descritiva",
      "Janelas sobrepostas são dependentes. Não há intervalo de confiança, causalidade, agregação como execução contínua ou busca de parâmetros vencedores.",
    );
    table(
      robustness,
      [
        "Política",
        "Custo",
        "Duração s",
        "Janelas",
        "Perdas",
        "Violações",
        "Risco completo",
        "Retorno mín.",
        "Retorno máx.",
        "Sobreposição",
      ],
      analysis.descriptive.map((d) => [
        d.policy,
        d.cost_scenario,
        d.duration_seconds,
        d.windows,
        d.losses,
        d.violations,
        d.complete_risk_windows,
        d.return_min,
        d.return_max,
        d.overlapping,
      ]),
    );
    parent.append(robustness);
    const exports = panel(
      "Reprodução e exportação",
      "Replay recalcula análises dos mesmos dados e código. Não executa estratégias históricas. As restrições declaradas são aplicadas no servidor.",
    );
    const reviewed = node("input");
    reviewed.type = "checkbox";
    if (
      (!analysis.export_scope ||
        (analysis.export_scope === "DERIVED_ONLY" &&
          analysis.redistribution === "PUBLIC")) &&
      analysis.redistribution !== "RESTRICTED"
    ) {
      exports.append(
        node(
          "p",
          analysis.export_scope
            ? "Autorização atual: somente derivados. Dados brutos e SVG continuam bloqueados. Uma ampliação exige nova confirmação dos direitos."
            : "Exportação bloqueada: a licença declarada pelo pack não comprova direitos. Autorize somente após verificar uma base independente. A autorização vale apenas nesta sessão e para estes bytes.",
        ),
      );
      const basis = node("select"),
        scope = node("select"),
        consent = node("input");
      consent.type = "checkbox";
      for (const [value, text] of [
        ["OWN_DATA", "Dados próprios"],
        ["VERIFIED_PUBLIC_LICENSE", "Licença pública verificada fora do pack"],
        ["RIGHTSHOLDER_PERMISSION", "Permissão do titular dos direitos"],
      ]) {
        const option = node("option", text);
        option.value = value;
        basis.append(option);
      }
      for (const [value, text] of [
        ["DERIVED_ONLY", "Somente resultados derivados"],
        ...(analysis.redistribution === "PUBLIC"
          ? [["RAW_AND_DERIVED", "Dados brutos e derivados"]]
          : []),
      ]) {
        const option = node("option", text);
        option.value = value;
        scope.append(option);
      }
      exports.append(
        field("Base independente dos direitos", basis),
        field("Escopo da autorização", scope),
        field(
          "Verifiquei os direitos fora do pack e autorizo esta exportação",
          consent,
        ),
      );
      exports.append(
        button("Autorizar exportação nesta sessão", async () => {
          if (!consent.checked)
            throw new Error(
              "Confirme a verificação independente dos direitos.",
            );
          const ticket = revision,
            id = study.id,
            authorization = {
              id,
              scope: scope.value,
              basis: basis.value,
              confirmed: true,
            };
          busy = true;
          paint();
          const authorized = await post(
            "/api/lab/authorize-export",
            authorization,
          );
          if (ticket !== revision || !model.canPaint(root)) return;
          await refresh();
          if (ticket !== revision || !model.canPaint(root)) return;
          await selectStudy(authorized, true);
        }),
      );
    }
    if (analysis.redistribution === "AGGREGATES_ONLY")
      exports.append(
        field("Revisei e autorizo somente os agregados permitidos", reviewed),
      );
    const exportButton = button("Baixar pacote de análise", () => {
      const p = params();
      if (analysis.redistribution === "AGGREGATES_ONLY") {
        if (!reviewed.checked)
          throw new Error("Revise os agregados antes de exportar.");
        p.set("reviewed", "1");
      }
      return download("/api/lab/export?" + p, "gridbot-analysis.zip");
    });
    exportButton.disabled = !analysis.export_scope;
    const manifestButton = button(
      "Baixar manifesto da análise",
      () =>
        saveBlob(
          new Blob([JSON.stringify(analysis.analysis_manifest, null, 2)], {
            type: "application/json",
          }),
          "gridbot-analysis-manifest.json",
        ),
      "secondary",
    );
    manifestButton.disabled = !analysis.export_scope;
    exports.append(
      exportButton,
      manifestButton,
      button(
        "Conferir reprodução determinística",
        async () => {
          const ticket = revision;
          const result = await post("/api/lab/replay", {
            id: study.id,
            manifest: analysis.analysis_manifest,
          });
          if (ticket !== revision || !model.canPaint(root)) return;
          message = `Replay ${result.status} · nenhuma estratégia executada`;
          paint();
        },
        "secondary",
      ),
    );
    const replayFile = node("input");
    replayFile.type = "file";
    replayFile.accept = ".json";
    exports.append(
      field("Manifesto de outra sessão para reproduzir", replayFile),
    );
    exports.append(
      button(
        "Validar manifesto escolhido",
        async () => {
          const ticket = revision,
            identity = study.id;
          const f = replayFile.files?.[0];
          if (!f || f.size > 16000)
            throw new Error("Escolha um manifesto JSON de até 16 KB.");
          const manifest = JSON.parse(await f.text());
          if (ticket !== revision || !model.canPaint(root)) return;
          const result = await post("/api/lab/replay", {
            id: identity,
            manifest,
          });
          if (ticket !== revision || !model.canPaint(root)) return;
          message = `Replay ${result.status}`;
          paint();
        },
        "secondary",
      ),
    );
    exports.append(details(analysis.analysis_manifest));
    parent.append(exports);
  }
  function paint() {
    if (!model.canPaint(root)) return;
    const renderStarted = performance.now();
    GridCharts.dispose(root);
    root.replaceChildren();
    root.setAttribute("aria-busy", String(busy));
    const status = node(
      "p",
      message || "Pesquisa offline · escolha uma evidência",
      "status",
    );
    status.setAttribute("role", "status");
    root.append(status);
    library(root);
    imports(root);
    if (!busy) results(root);
    const paper = panel(
      "Rastreabilidade PAPER existente",
      "O motor sintético original permanece separado. Inspecione os fills e seus saldos antes e depois, sem criar ordens novas.",
    );
    paper.append(
      button("Investigar fills da demonstração PAPER", async () => {
        const ticket = revision;
        const trace = await json("/api/lab/paper");
        if (ticket !== revision || !model.canPaint(root) || !paper.isConnected)
          return;
        const fills = trace.accounts.flatMap((a) =>
          a.fills.map((f) => ({ policy: a.policy, ...f })),
        );
        const choose = node("select"),
          out = node("pre", null, "lab-json");
        fills.forEach((f, i) => {
          const option = node(
            "option",
            `${f.policy} · ${f.time} · ${f.side} · fill ${f.fill_index}`,
          );
          option.value = String(i);
          choose.append(option);
        });
        const update = () => {
          out.textContent = JSON.stringify(
            fills[Number(choose.value) || 0],
            null,
            2,
          );
        };
        choose.addEventListener("change", update);
        update();
        paper.append(field("Fill PAPER para investigar", choose), out);
      }),
    );
    root.append(paper);
    root.dataset.labRenderMs = String(performance.now() - renderStarted);
  }
  global.GridLab = {
    deactivate() {
      controller.abort();
      revision++;
      root = null;
      busy = false;
    },
    render(target, options) {
      if (controller.signal.aborted) controller = new AbortController();
      root = target;
      context = { ...options };
      paint();
      const ticket = revision;
      refresh().catch((error) => {
        if (ticket === revision && error?.name !== "AbortError")
          showError(error);
      });
    },
  };
})(typeof window !== "undefined" ? window : globalThis);
