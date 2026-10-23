(function (root) {
  "use strict";
  const colors = [
    "#8bb6ff",
    "#d4b9ff",
    "#edcc8d",
    "#b4c2d6",
    "#69e4be",
    "#ff96a2",
  ];
  const dashes = ["", "9 4", "3 3", "12 3 2 3", "7 3 2 3", "2 4"];
  function domain(values, field, zoom = false) {
    if (!values.length) return null;
    if (values.some((v) => !Number.isFinite(v)))
      throw new Error("Série não finita");
    let lo = Math.min(...values),
      hi = Math.max(...values);
    if (field === "drawdown") {
      if (hi > 0) throw new Error("Drawdown positivo inválido");
      return [Math.min(lo, -0.2) * 1.07, 0];
    }
    if (field === "exposure" && lo >= 0 && hi <= 1) return [0, 1];
    if (lo >= 0 && (field !== "nav" || !zoom))
      return [0, hi > 0 ? hi * 1.07 : field.includes("btc") ? 1e-8 : 1];
    const span = hi - lo || Math.max(Math.abs(hi) * 0.02, 1e-8),
      pad = span * 0.07;
    return [lo >= 0 ? Math.max(0, lo - pad) : lo - pad, hi + pad];
  }
  function nearest(points, target) {
    let left = 0,
      right = points.length - 1;
    if (right < 0) return null;
    while (left < right) {
      const mid = Math.floor((left + right) / 2);
      if (Date.parse(points[mid].time) < target) left = mid + 1;
      else right = mid;
    }
    return left > 0 &&
      Math.abs(Date.parse(points[left - 1].time) - target) <=
        Math.abs(Date.parse(points[left].time) - target)
      ? points[left - 1]
      : points[left];
  }
  function lineChart(
    container,
    { accounts, field, unit, title, selected, labels, zoom = false },
  ) {
    const ns = "http://www.w3.org/2000/svg",
      box = document.createElement("section");
    box.className = "panel chart-panel";
    const head = document.createElement("div");
    head.className = "panel-head";
    const h = document.createElement("h2");
    h.textContent = title;
    head.append(h);
    const exportButton = document.createElement("button");
    exportButton.className = "secondary";
    exportButton.type = "button";
    exportButton.textContent = "Baixar SVG";
    exportButton.setAttribute("aria-label", "Baixar SVG: " + title);
    exportButton.addEventListener("click", () => {
      const original = box.querySelector("svg");
      if (!original) return;
      const copy = original.cloneNode(true);
      copy.setAttribute("xmlns", ns);
      const source = [original, ...original.querySelectorAll("*")],
        target = [copy, ...copy.querySelectorAll("*")];
      source.forEach((item, i) => {
        const style = getComputedStyle(item);
        for (const prop of [
          "fill",
          "stroke",
          "stroke-width",
          "stroke-dasharray",
          "font-size",
          "font-family",
        ]) {
          target[i].setAttribute(prop, style.getPropertyValue(prop));
        }
      });
      const desc = document.createElementNS(ns, "desc");
      desc.textContent = accounts
        .map(
          (a) =>
            `${a.summary.classification}; ${a.summary.policy}; ${a.summary.start} / ${a.summary.end}; ${a.summary.cost}; unidade ${unit}`,
        )
        .join(" | ");
      copy.prepend(desc);
      const dimensions = original.viewBox.baseVal,
        headerHeight = 48 + accounts.length * 20;
      const group = document.createElementNS(ns, "g");
      while (copy.firstChild) group.append(copy.firstChild);
      group.setAttribute("transform", `translate(0,${headerHeight})`);
      copy.setAttribute(
        "viewBox",
        `0 0 ${dimensions.width} ${dimensions.height + headerHeight}`,
      );
      const background = document.createElementNS(ns, "rect");
      background.setAttribute("width", "100%");
      background.setAttribute("height", "100%");
      background.setAttribute("fill", "#131e2e");
      copy.append(background);
      function label(text, y, color) {
        const textNode = document.createElementNS(ns, "text");
        textNode.setAttribute("x", 12);
        textNode.setAttribute("y", y);
        textNode.setAttribute("fill", color);
        textNode.setAttribute("font-size", "13");
        textNode.setAttribute("font-family", "system-ui");
        textNode.textContent = text;
        copy.append(textNode);
      }
      label(
        `GridBot · ${unit} · ${accounts[0].summary.classification === "SYNTHETIC_DEMO" ? "SYNTHETIC_DEMO" : "ARCHIVED_RESEARCH_RESULT"}`,
        22,
        "#edf2fa",
      );
      accounts.forEach((a, i) =>
        label(
          `${i + 1}. ${labels[a.summary.policy] || a.summary.policy}`,
          44 + i * 20,
          colors[i % 6],
        ),
      );
      copy.append(group);
      const blob = new Blob([new XMLSerializer().serializeToString(copy)], {
        type: "image/svg+xml",
      });
      const url = URL.createObjectURL(blob),
        a = document.createElement("a");
      a.href = url;
      a.download = "gridbot-chart.svg";
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    head.append(exportButton);
    box.append(head);
    const legend = document.createElement("div");
    legend.className = "legend";
    box.append(legend);
    accounts.forEach((a, i) => {
      const e = document.createElement("span");
      e.className = "series-label c" + i;
      e.textContent = `${i + 1}. ${labels[a.summary.policy] || a.summary.policy}${a.summary.policy === selected ? " · selecionada" : ""}`;
      legend.append(e);
    });
    const plot = document.createElement("div");
    plot.className = "chart";
    box.append(plot);
    const note = document.createElement("p");
    note.className = "chart-note";
    box.append(note);
    const readout = document.createElement("div");
    readout.className = "readout";
    readout.setAttribute("role", "status");
    readout.textContent =
      "Cursor, toque ou setas do teclado: consultar marcas observadas.";
    box.append(readout);
    container.append(box);
    if (!accounts.length || !accounts.some((a) => a.series.length)) {
      plot.textContent = "Dados indisponíveis";
      return;
    }
    const values = accounts.flatMap((a) =>
        a.series.map((p) => Number(p[field])),
      ),
      bounds = domain(values, field, zoom);
    if (!bounds) return;
    const [low, high] = bounds,
      times = accounts.flatMap((a) => a.series.map((p) => Date.parse(p.time))),
      min = Math.min(...times),
      max = Math.max(...times);
    const f = (v) =>
      Number(v).toLocaleString("pt-BR", {
        maximumFractionDigits: unit === "BTC" ? 8 : 2,
        minimumFractionDigits: unit === "BTC" ? 5 : 2,
      });
    note.textContent = `Eixo Y: ${f(unit === "%" ? low * 100 : low)} a ${f(unit === "%" ? high * 100 : high)} ${unit}. ${zoom ? "Domínio ajustado explicitamente; consulte a escala." : "Domínio absoluto com zero de referência."} Sem interpolar lacunas acima de um dia.`;
    let current = 0;
    function draw() {
      plot.replaceChildren();
      const width = Math.max(plot.clientWidth, 280),
        height = 310,
        left = width < 500 ? 78 : 96,
        right = width - 20,
        bottom = 263,
        top = 20;
      const svg = document.createElementNS(ns, "svg");
      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      svg.setAttribute("role", "img");
      svg.setAttribute("aria-label", title);
      svg.setAttribute("tabindex", "0");
      svg.dataset.yMin = String(low);
      svg.dataset.yMax = String(high);
      const xx = (t) =>
          left + ((Date.parse(t) - min) / (max - min || 1)) * (right - left),
        yy = (v) => bottom - ((v - low) / (high - low)) * (bottom - top);
      function shape(tag, attrs, text) {
        const e = document.createElementNS(ns, tag);
        Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, String(v)));
        if (text != null) e.textContent = text;
        svg.append(e);
        return e;
      }
      for (let i = 0; i <= 4; i++) {
        const v = low + ((high - low) * i) / 4,
          y = yy(v);
        shape("line", { x1: left, x2: right, y1: y, y2: y, class: "gridline" });
        shape(
          "text",
          { x: left - 10, y: y + 4, "text-anchor": "end" },
          f(unit === "%" ? v * 100 : v) + (unit === "%" ? "%" : ""),
        );
      }
      if (field === "drawdown") {
        shape("line", {
          x1: left,
          x2: right,
          y1: yy(-0.2),
          y2: yy(-0.2),
          class: "limit-line",
        });
        shape(
          "text",
          { x: left + 8, y: yy(-0.2) - 8, class: "limit-label" },
          "−20% · referência analítica",
        );
      }
      accounts.forEach((a, i) => {
        let path = "";
        a.series.forEach((p, j) => {
          const gap =
            !j ||
            Date.parse(p.time) - Date.parse(a.series[j - 1].time) > 86400000;
          path += `${gap ? "M" : "L"}${xx(p.time)} ${yy(Number(p[field]))} `;
          if (a.series.length === 1)
            shape("circle", {
              cx: xx(p.time),
              cy: yy(Number(p[field])),
              r: 4,
              fill: colors[i % 6],
            });
        });
        shape("path", {
          d: path,
          fill: "none",
          stroke: colors[i % 6],
          "stroke-width": a.summary.policy === selected ? 3.4 : 1.8,
          "stroke-dasharray": dashes[i % 6],
          "data-policy": a.summary.policy,
        });
      });
      const intraday = max - min < 86400000,
        dt = (t) =>
          new Date(t)
            .toISOString()
            .slice(intraday ? 11 : 0, intraday ? 19 : 10) +
          (intraday ? " UTC" : "");
      shape("text", { x: left, y: 293 }, dt(min));
      shape("text", { x: right, y: 293, "text-anchor": "end" }, dt(max));
      const cursor = shape("line", {
        x1: left,
        x2: left,
        y1: top,
        y2: bottom,
        class: "cursor-line",
      });
      const active =
        accounts.find((a) => a.summary.policy === selected) || accounts[0];
      function show(point) {
        if (!point) return;
        cursor.setAttribute("x1", xx(point.time));
        cursor.setAttribute("x2", xx(point.time));
        readout.replaceChildren();
        const stamp = document.createElement("strong");
        stamp.textContent = point.time;
        readout.append(stamp);
        accounts.forEach((a, i) => {
          const p = a.series.find((p) => p.time === point.time),
            entry = document.createElement("span");
          entry.textContent = `${i + 1}. ${labels[a.summary.policy] || a.summary.policy}: ${p ? f(unit === "%" ? Number(p[field]) * 100 : p[field]) + " " + unit : "sem marca nesse instante"}`;
          readout.append(entry);
        });
      }
      svg.addEventListener("pointermove", (event) => {
        const rect = svg.getBoundingClientRect(),
          x = ((event.clientX - rect.left) / rect.width) * width;
        show(
          nearest(
            active.series,
            min + ((x - left) / (right - left)) * (max - min),
          ),
        );
      });
      svg.addEventListener("keydown", (e) => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
        e.preventDefault();
        current =
          e.key === "Home"
            ? 0
            : e.key === "End"
              ? active.series.length - 1
              : Math.max(
                  0,
                  Math.min(
                    active.series.length - 1,
                    current + (e.key === "ArrowRight" ? 1 : -1),
                  ),
                );
        show(active.series[current]);
      });
      plot.append(svg);
    }
    draw();
    const observer = new ResizeObserver(() => {
      if (box.isConnected) draw();
      else observer.disconnect();
    });
    observer.observe(plot);
  }
  function histogram(container, bins, title) {
    const section = document.createElement("section");
    section.className = "panel";
    const h = document.createElement("h3");
    h.textContent = title + " · SYNTHETIC_DEMO";
    section.append(h);
    const ns = "http://www.w3.org/2000/svg",
      svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 600 170");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", title + " · contagens sintéticas");
    const max = Math.max(1, ...bins.map((b) => b.count));
    bins.forEach((bin, i) => {
      const rect = document.createElementNS(ns, "rect");
      rect.setAttribute("x", 30 + i * 92);
      rect.setAttribute("y", 140 - (bin.count / max) * 110);
      rect.setAttribute("width", 70);
      rect.setAttribute("height", (bin.count / max) * 110);
      rect.setAttribute("fill", "#69e4be");
      const tooltip = document.createElementNS(ns, "title");
      tooltip.textContent = `${Number(bin.low) * 100}% a ${Number(bin.high) * 100}%: ${bin.count} cenários`;
      rect.append(tooltip);
      svg.append(rect);
      const label = document.createElementNS(ns, "text");
      label.setAttribute("x", 65 + i * 92);
      label.setAttribute("y", 160);
      label.setAttribute("text-anchor", "middle");
      label.setAttribute("fill", "#b3c0d5");
      label.textContent = String(bin.count);
      svg.append(label);
    });
    section.append(svg);
    container.append(section);
  }
  const api = { domain, nearest, lineChart, histogram };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.GridCharts = api;
})(typeof window !== "undefined" ? window : globalThis);
