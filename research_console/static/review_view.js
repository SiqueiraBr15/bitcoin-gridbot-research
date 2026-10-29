(function (root) {
  "use strict";
  const model =
    typeof module !== "undefined" && module.exports
      ? require("./review_model.js")
      : root.GridGuidedReview;
  const numbers =
    typeof module !== "undefined" && module.exports
      ? require("./numbers.js")
      : root.GridNumbers;
  function render(parent, input, hooks, ui) {
    const { node, panel, field, table } = ui;
    const { study, analysis, focus, step, state } = input;
    const v = model.view(study, analysis, focus),
      row = v.row,
      m = row?.metrics,
      risk = m?.risk;
    const frame = panel(
      "Revisão Guiada de Evidências",
      "Investigue dados existentes, sem recomendação de investimento ou nova execução de estratégias.",
    );
    frame.classList.add("guided-review");
    frame.dataset.reviewState = state.availability;
    const nav = node("nav", null, "review-steps");
    nav.setAttribute("aria-label", "Etapas da revisão");
    model.steps.forEach((title, index) => {
      const b = node("button", `${index + 1}. ${title}`);
      b.type = "button";
      b.setAttribute("aria-current", step === index + 1 ? "step" : "false");
      b.addEventListener("click", () => hooks.go(index + 1));
      nav.append(b);
    });
    frame.append(nav);
    if (study)
      frame.append(
        node(
          "p",
          `${study.title} · ${study.source_kind} · ${analysis?.rows.length ?? 0} contas na seleção`,
          "review-context",
        ),
      );
    const heading = node(
      "h3",
      `${step}. ${model.steps[step - 1]}`,
      "review-step-title",
    );
    heading.tabIndex = -1;
    heading.id = "review-step-heading";
    frame.append(heading);
    if (analysis && row) {
      const select = node("select");
      select.id = "review-account-focus";
      analysis.rows.forEach((r) => {
        const o = node(
          "option",
          `${r.account_id} · ${r.policy} · ${r.window_id} · ${r.cost_scenario}`,
        );
        o.value = r.account_id;
        select.append(o);
      });
      select.value = row.account_id;
      select.addEventListener("change", () => hooks.focus(select.value));
      frame.append(field("Conta em foco nesta seleção", select));
      const selected = node(
        "p",
        `Conta selecionada: ${row.account_id}`,
        "review-context",
      );
      selected.id = "review-selected-account";
      // The select already exposes the complete identity to assistive technology.
      selected.setAttribute("aria-hidden", "true");
      frame.append(selected);
      frame.append(
        node(
          "p",
          `${row.start} → ${row.end} · ${row.cost_scenario} · benchmark declarado: ${row.benchmark || "não declarado"}`,
          "review-context",
        ),
      );
    }
    const exactDetails = (label, get) => {
      const d = node("details"),
        p = node("pre", null, "lab-json");
      d.append(node("summary", label), p);
      let built = false;
      d.addEventListener("toggle", () => {
        if (d.open && !built) {
          p.textContent = JSON.stringify(get(), null, 2);
          built = true;
        }
      });
      return d;
    };
    const metric = (label, value, unit, places = 8, factor = 1) => {
      const card = node("article", null, "review-metric");
      card.append(node("h4", label));
      const amount = node(
        "p",
        value == null
          ? "Indisponível"
          : numbers.formatDecimal(value, places, factor),
        "review-amount",
      );
      amount.dataset.metric = label;
      if (value != null)
        amount.title = `Origem: ${String(value).slice(0, 240)}${String(value).length > 240 ? "… (consulte a evidência exata)" : ""}`;
      card.append(amount, node("span", unit, "explain"));
      return card;
    };
    const metrics = (...cards) => {
      const grid = node("div", null, "review-metrics");
      grid.append(...cards);
      frame.append(grid);
    };
    const note = (text) => frame.append(node("p", text, "explain"));
    const binding = () =>
      exactDetails("Inspecionar a origem destes valores", () => ({
        account: row?.account_id,
        policy: row?.policy,
        window: row?.window_id,
        source: row?.evidence,
        exact: m?.exact,
        mark: v.last,
        analysis_manifest: analysis?.analysis_manifest,
      }));
    const enough = !!analysis;
    if (step === 1) {
      note(
        "Escolha um estudo na biblioteca abaixo. Políticas, janelas e custos identificam contas existentes; não são novos parâmetros de estratégia.",
      );
      if (study)
        frame.append(
          exactDetails("Identidade, fonte e restrições do estudo", () => study),
        );
      if (analysis) hooks.selection(frame);
    } else if (!enough) {
      note(
        state.availability === "LOADING"
          ? "Carregando esta seleção. Nenhum valor anterior está sendo apresentado."
          : "Dados indisponíveis para esta etapa. Escolha uma evidência válida; falhas não são substituídas por números.",
      );
      const b = node("button", "Escolher evidência");
      b.type = "button";
      b.addEventListener("click", () => hooks.go(1));
      frame.append(b);
    } else if (!row && step >= 2 && step <= 5) {
      note(
        "AGGREGATE_ONLY_NO_CURVES · este estudo contém somente contagens declaradas. NAV, BTC, episódios e Pareto de séries estão indisponíveis.",
      );
      table(
        frame,
        ["Política", "Custo", "Observações", "Perdas", "Violações"],
        analysis.aggregates.map((a) => [
          a.policy,
          a.cost_scenario,
          a.observations,
          a.losses,
          a.violations,
        ]),
      );
    } else if (step === 2) {
      note(
        "NAV é o patrimônio marcado em USDT. Custos declarados já estão refletidos nos saldos; não são descontados novamente.",
      );
      metrics(
        metric("NAV inicial", m.exact.nav_initial, "USDT", 2),
        metric("NAV final", m.exact.nav_final, "USDT", 2),
        metric("Retorno absoluto", m.exact.return_usdt, "USDT", 2),
        metric("Retorno percentual", m.exact.return_ratio, "%", 6, 100),
        metric("Caixa", m.exact.cash_usdt, "USDT", 2),
        metric("Custos declarados", m.exact.fees_usdt, "USDT", 2),
      );
      if (v.comparison.status === "COMPARABLE")
        metrics(
          metric(
            "Diferença de NAV contra benchmark",
            v.comparison.delta_nav,
            "USDT · precisão decimal do backend",
            2,
          ),
        );
      else
        note(
          "Benchmark indisponível: referência não selecionada ou não declarada. Nenhuma diferença foi preenchida com zero.",
        );
      frame.append(binding());
      hooks.charts(frame, ["nav"]);
    } else if (step === 3) {
      note(
        "BTC físico é a quantidade mantida no modelo. BTC equivalente mede poder de compra: não é custódia adicional e não deve ser somado ao inventário.",
      );
      metrics(
        metric("BTC físico", m.exact.btc_physical, "BTC"),
        metric("BTC equivalente", m.exact.btc_equivalent, "BTC equivalente"),
        metric("Variação de BTC físico", m.exact.btc_change, "BTC"),
        metric("Caixa USDT", m.exact.cash_usdt, "USDT", 2),
      );
      if (v.comparison.status === "COMPARABLE")
        metrics(
          metric(
            "Diferença física contra benchmark",
            v.comparison.delta_btc,
            "BTC · precisão decimal do backend",
          ),
        );
      note(
        "Mais BTC isoladamente não determina melhor resultado global. Reservas não adicionam patrimônio. O pack v1 não comprova separação CORE, passivos ou fees em terceiro ativo.",
      );
      frame.append(binding());
      hooks.charts(frame, ["btc"]);
    } else if (step === 4) {
      note(
        "20% é referência indicativa, sem stop-loss, garantia futura ou proteção intradiária. Lacunas não são interpoladas.",
      );
      metrics(
        metric(
          "Drawdown máximo da janela",
          m.exact.max_drawdown,
          "% · somente com evidência completa",
          6,
          100,
        ),
        metric(
          "Máximo nos segmentos observados",
          risk.max_drawdown_fraction,
          "% · alcance limitado aos segmentos",
          6,
          100,
        ),
      );
      frame.append(
        node(
          "p",
          `${risk.status} · ${risk.risk_complete ? "cadência completa nas marcas fornecidas" : "evidência de risco incompleta"} · ${risk.violates_20_percent === true ? "excedeu 20% observados" : risk.violates_20_percent === false ? "referência não excedida nas marcas observadas" : "violação indisponível"}`,
          "review-risk-state",
        ),
      );
      const choice = node("select"),
        episode = node("div");
      risk.episodes.forEach((e, i) => {
        const o = node("option", `${i + 1}. ${e.peak_at} → ${e.observed_end}`);
        o.value = String(i);
        choice.append(o);
      });
      const show = () => {
        episode.replaceChildren();
        const e = risk.episodes[Number(choice.value) || 0];
        if (!e) {
          episode.append(
            node(
              "p",
              "Sem episódio disponível; isso não comprova ausência universal de risco.",
            ),
          );
          return;
        }
        table(
          episode,
          ["Propriedade", "Valor observado"],
          [
            ["Pico", e.peak_at],
            ["Vale", e.trough_at],
            ["Recuperação", e.recovery_at ?? "Não observada"],
            ["Fim observado", e.observed_end],
            ["Duração observada · s", e.observed_seconds],
            ["Censurado", e.censored ? "Sim" : "Não"],
            ["Motivo", e.reason],
          ],
        );
        episode.append(exactDetails("Inspecionar episódio exato", () => e));
      };
      choice.addEventListener("change", show);
      choice.disabled = !risk.episodes.length;
      frame.append(field("Episódio de drawdown", choice), episode);
      show();
      frame.append(
        exactDetails("Lacunas e cadência", () => ({
          gaps: risk.gaps,
          sampling_seconds: risk.sampling_seconds,
        })),
      );
      hooks.charts(frame, ["drawdown"]);
    } else if (step === 5) {
      note(
        "Pareto não é recomendação: os objetivos escolhidos usam somente grupos equivalentes. Empates podem permanecer não dominados.",
      );
      hooks.selection(frame);
      if (v.groups.length > 1)
        note(
          "Múltiplos grupos: comparações globais bloqueadas. As tabelas abaixo estão separadas por grupo; nenhuma fronteira global é calculada.",
        );
      for (const group of v.groups) {
        const box = panel(
          "Grupo de comparabilidade",
          "Identidade de condições, não prova de autoria ou retorno futuro.",
        );
        box.append(node("p", group, "review-context"));
        table(
          box,
          [
            "Conta",
            "Política",
            "Benchmark",
            "NAV · USDT",
            "BTC físico",
            "DD · razão",
            "Fees · USDT",
            "Pareto neste grupo",
          ],
          analysis.rows
            .filter((r) => r.group_id === group)
            .map((r) => {
              const eligibility = model.view(
                study,
                analysis,
                r.account_id,
              ).eligibility;
              return [
                r.account_id,
                r.policy,
                r.benchmark,
                ui.present(r.metrics.exact.nav_final, 2),
                ui.present(r.metrics.exact.btc_physical),
                ui.present(r.metrics.exact.max_drawdown, 6),
                ui.present(r.metrics.exact.fees_usdt),
                eligibility === "INSUFFICIENT_OBJECTIVE_DATA"
                  ? "Inelegível: métrica indisponível"
                  : eligibility === "NON_DOMINATED_IN_GROUP"
                    ? "Não dominada neste grupo"
                    : "Dominada neste grupo",
              ];
            }),
        );
        frame.append(box);
      }
      if (v.groups.length === 1) hooks.scatter(frame, analysis.rows);
    } else if (step === 6) {
      note(
        "Hashes demonstram identidade/integridade, não autoria. Replay reproduz a análise desses dados e código; não executa estratégias.",
      );
      frame.append(
        exactDetails("Pack, manifesto, seleção e versões", () => ({
          pack: analysis.pack_sha256,
          manifest: analysis.manifest_sha256,
          source_kind: analysis.source_kind,
          numeric_contract: analysis.numeric_contract,
          analysis_manifest: analysis.analysis_manifest,
        })),
      );
      if (row) frame.append(binding());
      frame.append(
        node(
          "p",
          `Replay desta seleção: ${state.replay}`,
          "review-replay-state",
        ),
      );
      hooks.actions(frame, { replay: true, download: false });
    } else if (step === 7) {
      note(
        "Resumo da seleção vigente, sem recomendação de compra/venda ou previsão. Valores e estados abaixo são projeções do backend.",
      );
      note(
        `${analysis.source_kind} · ${analysis.data_nature} · proveniência declarada, não autenticada. ${v.groups.length} grupo(s); janelas independentes não são concatenadas.`,
      );
      table(
        frame,
        [
          "Conta/política",
          "Período/custo",
          "Benchmark",
          "NAV · USDT",
          "BTC físico",
          "BTC equivalente",
          "DD · razão",
          "Risco",
        ],
        analysis.rows.map((r) => [
          r.account_id + " / " + r.policy,
          r.start + " → " + r.end + " / " + r.cost_scenario,
          (r.benchmark || "Não declarado") +
            " · " +
            r.benchmark_comparison.status,
          ui.present(r.metrics.exact.nav_final, 2),
          ui.present(r.metrics.exact.btc_physical),
          ui.present(r.metrics.exact.btc_equivalent),
          ui.present(r.metrics.exact.max_drawdown, 6),
          r.metrics.risk.risk_complete
            ? "Completo nas marcas fornecidas"
            : "Incompleto",
        ]),
      );
      if (!analysis.rows.length)
        note(
          "Somente agregados: composição patrimonial e curvas indisponíveis.",
        );
      const limits = node("ul");
      analysis.limitations.forEach((text) => limits.append(node("li", text)));
      frame.append(limits);
      note(
        "Dados não demonstram retorno futuro, proteção de 20%, autenticidade do produtor ou direitos por si. Fees de terceiro ativo e fluxos externos não integram o schema v1.",
      );
      frame.append(
        node(
          "p",
          `Exportação: ${state.export === "FAILED" ? "FALHOU · reveja sessão/direitos" : analysis.export_scope || "BLOQUEADA"} · declaração ${analysis.redistribution}. Autoridade continua no servidor.`,
          "review-export-state",
        ),
      );
      hooks.actions(frame, { replay: false, download: true });
    }
    const controls = node("div", null, "review-navigation");
    for (const [label, target] of [
      ["Anterior", step - 1],
      ["Próxima", step + 1],
    ]) {
      const b = node("button", label);
      b.type = "button";
      b.disabled = target < 1 || target > 7;
      b.addEventListener("click", () => hooks.go(target));
      controls.append(b);
    }
    const exit = node("button", "Abrir modo detalhado", "secondary");
    exit.id = "review-open-detailed";
    exit.type = "button";
    exit.addEventListener("click", hooks.detailed);
    controls.append(exit);
    frame.append(controls);
    parent.append(frame);
    return heading;
  }
  const api = { render };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.GridReviewView = api;
})(typeof window !== "undefined" ? window : globalThis);
