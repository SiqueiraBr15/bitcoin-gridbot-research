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
  const button = (label, action, cls = "action", id = "") => {
    const b = node("button", label, cls);
    b.type = "button";
    if (id) b.id = id;
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
  const present = (
    value,
    decimals = 8,
    origin = "Valor exato antes da formatação: ",
  ) => {
    if (value == null) return "Indisponível";
    const n = node("span", model.formatDecimal(value, decimals));
    n.title =
      value.length <= 512
        ? origin + value
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
    actionError = false,
    busy = false,
    analysisState = "DATA_UNAVAILABLE",
    importState = "IMPORT_IDLE";
  const guideModel = global.GridGuidedReview;
  const review = guideModel ? new guideModel.State() : null;
  let reviewMode = guideModel ? "guided" : "detailed",
    reviewStep = 1;
  try {
    if (guideModel) {
      const pref = guideModel.preference(
        JSON.parse(sessionStorage.getItem("gridbot.g5.review") || "{}"),
      );
      reviewMode = pref.mode;
      reviewStep = pref.step;
    }
  } catch {
    /* Corrupt preferences never become data authority. */
  }
  function reviewPreference() {
    try {
      sessionStorage.setItem(
        "gridbot.g5.review",
        JSON.stringify({ mode: reviewMode, step: reviewStep }),
      );
    } catch {}
  }
  function goReview(step) {
    reviewStep = step;
    reviewPreference();
    paint();
    root?.querySelector(".review-step-title")?.focus();
  }
  let controller = new AbortController();
  let catalogController = new AbortController(),
    catalogRevision = 0;
  const capabilities = { persistence: null, archiveAdapter: null };
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
  async function request(url, options = {}, signal = controller.signal) {
    const response = await fetch(url, {
      ...options,
      credentials: "same-origin",
      signal: AbortSignal.any([signal, AbortSignal.timeout(15000)]),
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
      const error = new Error(
        descriptions[problem.reason] ||
          (response.status === 403
            ? "Sessão local expirada ou origem recusada. Recarregue a página."
            : response.status >= 500
              ? "Falha interna do serviço de análise. Tente novamente."
              : "Schema ou dados inválidos. O pack exige manifesto e resultados válidos."),
      );
      error.status = response.status;
      error.reason = Object.hasOwn(descriptions, problem.reason)
        ? problem.reason
        : "";
      throw error;
    }
    if (
      Number(response.headers.get("Content-Length") || 0) >
      model.maxResponseBytes
    )
      throw new Error("Resposta excede limite local.");
    return response;
  }
  async function json(url, options, signal) {
    return (await request(url, options, signal)).json();
  }
  function post(url, data) {
    return json(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-GridBot-Lab": "1" },
      body: JSON.stringify(data),
    });
  }
  function showError(error, prefix = "") {
    busy = false;
    actionError = true;
    if (error instanceof NumericFormatError) {
      review?.fail(review.generation, error);
      analysis = null;
      analysisState = "ANALYSIS_FAILURE";
    }
    const description =
      error?.name === "TimeoutError"
        ? "O serviço excedeu o prazo da requisição. Nenhum resultado foi concluído; tente novamente."
        : error?.name === "SyntaxError"
          ? "Resposta ou manifesto JSON inválido. Nenhum resultado foi concluído."
          : error?.message || "Não foi possível validar a evidência.";
    message = prefix + description;
    if (model.canPaint(root)) paint();
  }
  function params() {
    const p = new URLSearchParams({ id: study.id });
    if (chosen) p.set("accounts", chosen.join(","));
    p.set("objectives", objectives.join(","));
    return p;
  }
  async function selectStudy(s, keep = false, afterImport = false) {
    controller.abort();
    controller = new AbortController();
    const ticket = ++revision;
    const reviewTicket = review?.begin({
      accounts: keep ? chosen : null,
      objectives,
    });
    actionError = false;
    if (!keep) reviewStep = 1;
    study = s;
    analysis = null;
    analysisState = "ANALYSIS_PENDING";
    busy = true;
    message = afterImport
      ? "Importação concluída. Validando pack e derivando métricas…"
      : "Validando pack e derivando métricas…";
    if (!keep) {
      chosen = null;
      focus = "";
      availableAccounts = [];
    }
    paint();
    try {
      const result = await json("/api/lab/analysis?" + params());
      if (ticket !== revision || !model.canPaint(root)) return;
      if (review && !review.commit(reviewTicket, s, result)) return;
      analysis = result;
      if (!result.rows.some((r) => r.account_id === focus))
        focus = result.rows[0]?.account_id || "";
      analysisState = "ANALYSIS_SUCCESS";
      if (!keep) availableAccounts = result.accounts.map((a) => a.account_id);
      message =
        "Integridade validada · proveniência declarada, sem autenticação de autoria.";
    } catch (error) {
      // This operation owns its revision. The import button's earlier ticket
      // must not swallow a current analysis failure after selectStudy increments it.
      if (ticket === revision && error?.name !== "AbortError") {
        review?.fail(reviewTicket, error);
        analysis = null;
        analysisState =
          error?.reason === "DATA_UNAVAILABLE"
            ? "DATA_UNAVAILABLE"
            : "ANALYSIS_FAILURE";
        showError(error, afterImport ? "Importação concluída. " : "");
      }
    } finally {
      if (ticket === revision) {
        busy = false;
        if (model.canPaint(root)) paint();
      }
    }
  }
  async function refresh() {
    // Catalog capabilities have a page lifecycle independent of study selection.
    const target = root,
      ticket = ++catalogRevision;
    catalogController.abort();
    catalogController = new AbortController();
    const data = await json(
      "/api/lab/library",
      undefined,
      catalogController.signal,
    );
    if (
      ticket !== catalogRevision ||
      root !== target ||
      !model.canPaint(target)
    )
      return;
    studies = data.studies;
    const currentStudy = studies.find((s) => s.id === study?.id);
    if (study && currentStudy?.integrity !== "VALIDATED") {
      controller.abort();
      controller = new AbortController();
      revision++;
      review?.invalidate();
      review?.fail(
        review.generation,
        currentStudy
          ? { status: 422, reason: "INTEGRITY_MISMATCH" }
          : { reason: "DATA_UNAVAILABLE" },
      );
      busy = false;
      analysis = null;
      study = null;
      reviewStep = 1;
      analysisState = "DATA_UNAVAILABLE";
      message =
        "Estudo indisponível ou inválido. Escolha uma evidência válida.";
    }
    capabilities.persistence = data.persistence_enabled === true;
    capabilities.archiveAdapter = data.archive_adapter;
    Object.assign(context, capabilities);
    paint();
  }
  async function download(url, filename) {
    const ticket = revision,
      binding = review?.identity;
    review?.action("export", "RUNNING", binding);
    try {
      const blob = await (await request(url)).blob();
      if (ticket !== revision || !model.canPaint(root)) return;
      saveBlob(blob, filename);
      review?.action("export", "COMPLETED", binding);
    } catch (error) {
      if (ticket === revision) review?.action("export", "FAILED", binding);
      throw error;
    }
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
      context.persistence == null
        ? "Consultando a disponibilidade de persistência da biblioteca…"
        : context.persistence
          ? "A prévia não persiste arquivos. Confirme explicitamente a cópia local após validar os metadados."
          : "Prévia em memória disponível. Para persistir, inicie com --lab-dir apontando para uma pasta nova ou exclusiva do laboratório.",
    );
    const file = node("input");
    file.id = "review-import-file";
    file.type = "file";
    file.accept = ".gbpack,.zip";
    const pin = node("input");
    pin.id = "review-import-pin";
    pin.type = "text";
    pin.maxLength = 64;
    pin.placeholder = "Opcional · fornecido por outra fonte";
    box.append(
      field("Evidence Pack local · limite 2 MiB", file),
      field("SHA-256 externo opcional", pin),
    );
    box.append(
      button(
        "Validar prévia do arquivo",
        async () => {
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
        },
        "action",
        "review-validate-preview",
      ),
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
        const ticket = ++revision,
          token = preview.preview_token;
        controller.abort();
        controller = new AbortController();
        review?.invalidate();
        study = null;
        busy = true;
        importState = "IMPORT_PENDING";
        analysisState = "DATA_UNAVAILABLE";
        analysis = null;
        message = "Confirmando a persistência da cópia local…";
        paint();
        let imported;
        try {
          imported = await post("/api/lab/confirm", {
            preview_token: token,
            confirmed: true,
          });
        } catch (error) {
          if (ticket === revision) importState = "IMPORT_FAILURE";
          throw error;
        }
        if (ticket !== revision || !model.canPaint(root)) return;
        importState = "IMPORT_SUCCESS";
        preview = null;
        try {
          await refresh();
        } catch (error) {
          if (ticket === revision && error?.name !== "AbortError")
            showError(
              error,
              "Importação concluída. Não foi possível atualizar a biblioteca. ",
            );
          return;
        }
        if (ticket !== revision || !model.canPaint(root)) return;
        await selectStudy(imported, false, true);
      });
      action.disabled = busy || context.persistence !== true;
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
    search.id = "review-library-search";
    search.type = "search";
    search.value = query;
    const type = node("select");
    type.id = "review-library-source";
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
    order.id = "review-library-order";
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
        const b = button(
          "Analisar " + s.title,
          () => selectStudy(s),
          "action",
          "review-study-" + s.id,
        );
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
                  review?.invalidate();
                  reviewStep = 1;
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
    selectionControls(summary);
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
    select.id = "review-account-focus";
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
      const riskStatus = node(
        "p",
        `${risk.status} · distância para referência 20%: `,
        "lab-risk-status",
      );
      riskStatus.append(
        present(
          risk.distance_to_20_pp,
          2,
          "Valor de origem antes da formatação: ",
        ),
        node(
          "span",
          ` pp · ${risk.violates_20_percent === true ? "EXCEDEU 20% observados" : "Sem violação demonstrada neste recorte"}`,
        ),
      );
      evidence.append(riskStatus);
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
    analysisCharts(parent);
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
    analysisActions(parent);
  }
  function selectionControls(parent) {
    if (!analysis.accounts.length) return;
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
      button(
        "Aplicar seleção analítica",
        () => {
          if (!newChosen.size || !nextObjectives.size)
            throw new Error("Selecione ao menos uma conta e um objetivo.");
          chosen = [...newChosen].sort();
          objectives = [...nextObjectives].sort();
          return selectStudy(study, true);
        },
        "action",
        "review-apply-selection",
      ),
    );
    parent.append(controls);
    const current =
      analysis.rows.find((r) => r.account_id === focus) || analysis.rows[0];
    if (
      current?.benchmark &&
      availableAccounts.includes(current.benchmark) &&
      !analysis.rows.some((r) => r.account_id === current.benchmark)
    ) {
      parent.append(
        button(
          "Incluir benchmark declarado na seleção",
          () => {
            chosen = [
              ...new Set([...(chosen || availableAccounts), current.benchmark]),
            ].sort();
            return selectStudy(study, true);
          },
          "secondary",
          "review-include-benchmark",
        ),
      );
    }
  }
  function analysisCharts(parent, fields = ["nav", "drawdown"]) {
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
      for (const graphField of fields.filter((f) =>
        ["nav", "btc"].includes(f),
      )) {
        GridCharts.lineChart(parent, {
          accounts: converted,
          field: graphField,
          unit: graphField === "nav" ? "USDT" : "BTC",
          title:
            graphField === "nav"
              ? "Marcas validadas · NAV em USDT"
              : "Marcas validadas · BTC físico",
          selected: focus,
          labels: Object.create(null),
          context: chartContext,
        });
      }
      const riskAccounts = converted.filter((a) =>
        a.series.every((p) => p.drawdown != null),
      );
      if (fields.includes("drawdown") && riskAccounts.length)
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
  }
  async function replayCurrent(manifest) {
    const ticket = revision,
      binding = review?.identity;
    review?.action("replay", "RUNNING", binding);
    paint();
    try {
      const result = await post("/api/lab/replay", { id: study.id, manifest });
      if (ticket !== revision || !model.canPaint(root)) return;
      if (
        result.status !== "EQUIVALENT" ||
        result.result_sha256 !==
          analysis.analysis_manifest.expected_result_sha256
      )
        throw new Error("Replay não equivalente à seleção atual.");
      review?.action("replay", "EQUIVALENT", binding);
      message = "Replay EQUIVALENT · nenhuma estratégia executada";
    } catch (error) {
      if (ticket === revision) review?.action("replay", "FAILED", binding);
      throw error;
    } finally {
      if (ticket === revision && model.canPaint(root)) paint();
    }
  }
  function analysisActions(
    parent,
    { replay = true, download: showDownload = true } = {},
  ) {
    const exports = panel(
      "Reprodução e exportação",
      "Mesmos dados e código; direitos continuam controlados pelo servidor.",
    );
    if (showDownload) {
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
          [
            "VERIFIED_PUBLIC_LICENSE",
            "Licença pública verificada fora do pack",
          ],
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
          button(
            "Autorizar exportação nesta sessão",
            async () => {
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
            },
            "action",
            "review-authorize-export",
          ),
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
      exportButton.id = "review-export";
      exportButton.disabled = busy || !analysis.export_scope;
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
      manifestButton.disabled = busy || !analysis.export_scope;
      exports.append(exportButton, manifestButton);
    }
    if (replay) {
      const run = button(
        "Conferir reprodução determinística",
        () => replayCurrent(analysis.analysis_manifest),
        "secondary",
      );
      run.id = "review-replay";
      run.disabled = busy || review?.replay === "RUNNING";
      exports.append(run);
      const replayFile = node("input");
      replayFile.id = "review-replay-file";
      replayFile.type = "file";
      replayFile.accept = ".json";
      exports.append(
        field("Manifesto de outra sessão para reproduzir", replayFile),
      );
      const validate = button(
        "Validar manifesto escolhido",
        async () => {
          const ticket = revision,
            identity = study.id,
            binding = review?.identity;
          try {
            const f = replayFile.files?.[0];
            if (!f || f.size > 16000)
              throw new Error("Escolha um manifesto JSON de até 16 KB.");
            review?.action("replay", "RUNNING", binding);
            paint();
            const manifest = JSON.parse(await f.text());
            if (ticket !== revision || !model.canPaint(root)) return;
            await replayCurrent(manifest);
          } catch (error) {
            if (ticket === revision && study?.id === identity)
              review?.action("replay", "FAILED", binding);
            throw error;
          }
        },
        "secondary",
        "review-validate-manifest",
      );
      validate.disabled = busy || review?.replay === "RUNNING";
      exports.append(validate);
    }
    exports.append(details(analysis.analysis_manifest));
    parent.append(exports);
  }
  function paint() {
    if (!model.canPaint(root)) return;
    const ownsFocus = root.contains(document.activeElement);
    const activeReviewControl = ownsFocus ? document.activeElement?.id : "";
    const restoreFocus = () => {
      // Restore only within the subtree being replaced, never steal focus from
      // another panel when an asynchronous response finishes.
      if (!ownsFocus) return;
      const target = /^review-[a-z0-9-]+$/.test(activeReviewControl || "")
        ? root.querySelector("#" + activeReviewControl)
        : null;
      (target && !target.disabled
        ? target
        : root.querySelector("#review-step-heading") ||
          root.querySelector("#review-mode-detailed")
      )?.focus();
    };
    const renderStarted = performance.now();
    GridCharts.dispose(root);
    root.replaceChildren();
    root.setAttribute("aria-busy", String(busy));
    root.dataset.analysisState = analysisState;
    root.dataset.importState = importState;
    const status = node(
      "p",
      message || "Pesquisa offline · escolha uma evidência",
      "status",
    );
    status.setAttribute(
      "role",
      actionError ||
        analysisState === "ANALYSIS_FAILURE" ||
        importState === "IMPORT_FAILURE"
        ? "alert"
        : "status",
    );
    root.append(status);
    if (guideModel && global.GridReviewView) {
      const modes = node("div", null, "review-mode");
      for (const [mode, label] of [
        ["guided", "Revisão Guiada de Evidências"],
        ["detailed", "Modo detalhado"],
      ]) {
        const b = node("button", label, "secondary");
        b.id = "review-mode-" + mode;
        b.type = "button";
        b.setAttribute("aria-pressed", String(reviewMode === mode));
        b.addEventListener("click", () => {
          reviewMode = mode;
          reviewPreference();
          paint();
        });
        modes.append(b);
      }
      root.append(modes);
      if (reviewMode === "guided") {
        global.GridReviewView.render(
          root,
          { study, analysis, focus, step: reviewStep, state: review },
          {
            go: goReview,
            focus(id) {
              focus = id;
              paint();
            },
            detailed() {
              reviewMode = "detailed";
              reviewPreference();
              paint();
            },
            selection: selectionControls,
            charts: analysisCharts,
            scatter,
            actions: analysisActions,
          },
          { node, panel, field, table, present },
        );
        if (reviewStep === 1) {
          library(root);
          imports(root);
        }
        restoreFocus();
        root.dataset.labRenderMs = String(performance.now() - renderStarted);
        return;
      }
    }
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
    restoreFocus();
    root.dataset.labRenderMs = String(performance.now() - renderStarted);
  }
  global.GridLab = {
    deactivate() {
      controller.abort();
      catalogController.abort();
      catalogRevision++;
      revision++;
      review?.invalidate();
      if (analysisState === "ANALYSIS_PENDING") {
        analysisState = "DATA_UNAVAILABLE";
        message =
          "Análise interrompida ao navegar. Selecione o estudo para tentar novamente.";
      }
      if (importState === "IMPORT_PENDING") {
        importState = "IMPORT_UNCONFIRMED";
        message =
          "Confirmação interrompida; verifique a biblioteca antes de tentar novamente. A cópia pode ter sido persistida.";
      }
      root = null;
      busy = false;
    },
    render(target, options) {
      if (controller.signal.aborted) controller = new AbortController();
      root = target;
      context = { ...options, ...capabilities };
      paint();
      const targetRoot = root;
      const returningStudy = study,
        returningRevision = revision;
      const pendingCatalog = refresh(),
        ticket = catalogRevision;
      if (returningStudy && analysis) {
        analysis = null;
        analysisState = "ANALYSIS_PENDING";
        review?.begin({ accounts: chosen, objectives });
        busy = true;
        actionError = false;
        message = "Revalidando esta evidência ao voltar ao Lab…";
        paint();
        pendingCatalog
          .then(() => {
            if (
              returningRevision === revision &&
              root === targetRoot &&
              study?.id === returningStudy.id &&
              model.canPaint(root)
            )
              return selectStudy(study, true);
          })
          .catch(() => {});
      }
      pendingCatalog.catch((error) => {
        if (
          ticket === catalogRevision &&
          targetRoot === root &&
          model.canPaint(root) &&
          error?.name !== "AbortError"
        ) {
          if (!analysis) {
            analysisState = "ANALYSIS_FAILURE";
            review?.fail(review.generation, error);
          }
          showError(error, "Não foi possível consultar a biblioteca. ");
        }
      });
    },
  };
})(typeof window !== "undefined" ? window : globalThis);
