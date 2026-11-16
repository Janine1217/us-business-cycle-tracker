/* 美國景氣循環儀表板：前端互動 */
(function () {
  "use strict";
  const D = window.DASHBOARD;
  const $ = (s, el) => (el || document).querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const STAGES = ["全部", "復甦期", "成長期", "榮景期", "衰退期"];
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* 無痕模式等 */ } },
  };

  if (!D) { $("#meta").textContent = "資料載入失敗"; return; }

  // ── 頁首與分頁 ───────────────────────────────
  $("#meta").textContent = `資料更新：${D.last_run || "—"}（台灣時間）｜頁面產生：${D.generated}`;
  const tabs = document.querySelectorAll(".tabs button");
  function showTab(name) {
    tabs.forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === name));
    document.querySelectorAll(".panel").forEach((p) => (p.hidden = p.id !== name));
    store.set("tab", name);
    if (name === "charts") observeCharts();
  }
  tabs.forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));

  // ── 總覽：資料狀態 ───────────────────────────
  const failedRows = D.table.filter((r) => r.failed.length);
  $("#health").innerHTML =
    `<div class="health-row"><span>追蹤指標</span><span>${D.table.length} 項</span></div>` +
    `<div class="health-row"><span>最近一次更新失敗</span><span>${failedRows.length
      ? failedRows.map((r) => `<span class="badge fail">✕ #${esc(r.id)} ${esc(r.name)}</span>`).join(" ")
      : '<span class="badge ok">✓ 全部成功</span>'}</span></div>`;

  // ── 指標總表 ───────────────────────────────
  const fmt = (v) => (v == null ? "—" : Math.abs(v) >= 1000 ? v.toLocaleString("zh-TW", { maximumFractionDigits: 0 }) : (+v).toFixed(2));
  function renderTable(stage) {
    const rows = D.table.filter((r) => stage === "全部" || r.stages.includes(stage));
    $("#indicator-list").innerHTML = rows.map((r) => {
      const dir = r.chg == null ? "" : r.chg > 0 ? "up" : r.chg < 0 ? "down" : "flat";
      const chg = r.chg == null ? "—" : `${r.chg > 0 ? "+" : ""}${fmt(r.chg)} ${r.chg_unit}`;
      const fail = r.failed.map((f) => `<span class="badge fail">✕ ${esc(f.id)} 最近一次更新失敗，最後成功：${esc(f.last_success || "無")}</span>`).join("");
      return `<article class="ind" data-goto="${esc(r.id)}" tabindex="0">
        <div class="ind-head"><span class="ind-name"><span class="ind-no">#${esc(r.id)}</span>${esc(r.name)}</span></div>
        <div class="ind-metric">${esc(r.metric)}</div>
        <div class="ind-value">${fmt(r.value)}<small>${esc(r.unit)}</small></div>
        <div class="ind-sub"><span class="${dir}">變化 ${chg}</span><span>前值 ${fmt(r.prev)}</span><span>資料期間 ${esc(r.date.slice(0, 7))}</span></div>
        <div class="ind-tags">${r.stages.map((s) => `<span class="badge stage">${esc(s)}</span>`).join("")}${fail}</div>
      </article>`;
    }).join("");
    store.set("stage", stage);
  }
  function chips(el, onPick, key) {
    const cur = store.get(key) || "全部";
    el.innerHTML = STAGES.map((s) => `<button aria-pressed="${s === cur}">${s}</button>`).join("");
    el.addEventListener("click", (e) => {
      const b = e.target.closest("button"); if (!b) return;
      el.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b));
      onPick(b.textContent);
    });
    onPick(cur);
  }
  chips($("#stage-filter"), renderTable, "stage");
  $("#indicator-list").addEventListener("click", (e) => {
    const a = e.target.closest("[data-goto]"); if (!a) return;
    showTab("charts");
    const card = document.getElementById("chart-" + a.dataset.goto);
    if (card) { card.hidden = false; card.scrollIntoView({ behavior: "smooth" }); }
  });

  // ── 趨勢圖 ─────────────────────────────────
  const RANGES = [["1 年", 1], ["5 年", 5], ["10 年", 10], ["1985 至今", 0]];
  const list = $("#chart-list");
  list.innerHTML = D.charts.map((c) => {
    const views = c.views.length > 1
      ? `<div class="seg" data-role="view">${c.views.map((v, i) => `<button aria-pressed="${i === 0}" data-i="${i}">${esc(v.name)}</button>`).join("")}</div>` : "";
    const ranges = `<div class="seg" data-role="range">${RANGES.map(([n, y]) => `<button aria-pressed="${y === 0}" data-y="${y}">${n}</button>`).join("")}</div>`;
    const log = c.views.some((v) => v.log_ok) ? `<div class="seg" data-role="log"><button aria-pressed="false">對數刻度</button></div>` : "";
    const src = c.sources.map((s) =>
      `${esc(s.org)}｜<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.id)}</a> ${esc(s.name)}` +
      (s.failed ? ` <span class="fail">✕ 最近一次更新失敗，最後成功：${esc(s.last_success || "無")}</span>` : "")).join("<br>");
    return `<section class="chart-card" id="chart-${esc(c.id)}" data-stages="${esc(c.stages.join(","))}">
      <h3><span class="ind-no">#${esc(c.id)}</span>${esc(c.title)}</h3>
      <div class="chart-controls">${views}${ranges}${log}</div>
      <div class="plot" data-chart="${esc(c.id)}"></div>
      ${c.notes.length ? `<ul class="chart-notes">${c.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
      <div class="chart-src">來源：${src}</div>
    </section>`;
  }).join("");

  const state = {}; // 每張圖目前的 view / range / log
  D.charts.forEach((c) => (state[c.id] = { view: 0, years: 0, log: false, drawn: false }));

  function yRange(traces, axis, x0, log) {
    let lo = Infinity, hi = -Infinity;
    traces.filter((t) => t.axis === axis).forEach((t) => {
      t.x.forEach((x, i) => { if (x >= x0) { const v = t.y[i]; if (v < lo) lo = v; if (v > hi) hi = v; } });
    });
    if (!isFinite(lo)) return undefined;
    if (log) { if (lo <= 0) return undefined; lo = Math.log10(lo); hi = Math.log10(hi); }
    const pad = (hi - lo) * 0.06 || Math.abs(hi) * 0.1 || 1;
    return [lo - pad, hi + pad];
  }

  function draw(id) {
    const c = D.charts.find((x) => x.id === id);
    const st = state[id];
    const v = c.views[st.view];
    const el = list.querySelector(`[data-chart="${CSS.escape(id)}"]`);
    const colors = [css("--s1"), css("--s2"), css("--s3"), css("--s4")];
    const lastX = v.traces.reduce((m, t) => (t.x[t.x.length - 1] > m ? t.x[t.x.length - 1] : m), "");
    let x0 = D.start;
    if (st.years) { const d = new Date(lastX); d.setFullYear(d.getFullYear() - st.years); x0 = d.toISOString().slice(0, 10); }
    const log = st.log && v.log_ok;
    const hasY2 = v.traces.some((t) => t.axis === "y2");

    const traces = v.traces.map((t, i) => ({
      type: "scatter", mode: "lines", name: t.name, x: t.x, y: t.y,
      yaxis: t.axis === "y2" ? "y2" : "y",
      line: { color: colors[i % colors.length], width: 2, dash: t.dash ? "dot" : "solid" },
      hovertemplate: `%{y:,.2f} ${t.unit}<extra>${t.name}</extra>`,
    }));
    const shapes = D.recessions.map(([a, b]) => ({
      type: "rect", xref: "x", yref: "paper", x0: a, x1: b || lastX, y0: 0, y1: 1,
      fillcolor: css("--recession"), line: { width: 0 }, layer: "below",
    }));
    v.hlines.forEach((h) => shapes.push({
      type: "line", xref: "paper", x0: 0, x1: 1, yref: "y", y0: h.y, y1: h.y,
      line: { color: css("--axis"), width: 1, dash: h.y === 0 ? "solid" : "dash" },
    }));
    const annotations = v.hlines.filter((h) => h.label).map((h) => ({
      xref: "paper", x: 0, yref: "y", y: h.y, text: h.label, showarrow: false,
      xanchor: "left", yanchor: "bottom", font: { size: 11, color: css("--muted") },
    }));
    (v.vlines || []).forEach((l) => {
      shapes.push({ type: "line", xref: "x", x0: l.x, x1: l.x, yref: "paper", y0: 0, y1: 1, line: { color: css("--s4"), width: 1, dash: "dot" } });
    });
    const axis = { gridcolor: css("--grid"), linecolor: css("--axis"), zerolinecolor: css("--axis"), tickfont: { color: css("--muted"), size: 11 } };
    const layout = {
      paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
      font: { family: getComputedStyle(document.body).fontFamily, color: css("--ink-2"), size: 12 },
      margin: { l: 52, r: hasY2 ? 56 : 12, t: 8, b: 28 },
      hovermode: "x unified", hoverlabel: { bgcolor: css("--surface"), bordercolor: css("--border"), font: { color: css("--ink") } },
      showlegend: v.traces.length > 1,
      legend: { orientation: "h", x: 0, y: -0.14, font: { size: 12 } },
      xaxis: { ...axis, type: "date", range: [x0, lastX], showgrid: false },
      yaxis: { ...axis, title: { text: v.y_title, font: { size: 11 } }, type: log ? "log" : "linear", range: yRange(v.traces, "y", x0, log) },
      shapes, annotations,
    };
    if (hasY2) layout.yaxis2 = { ...axis, title: { text: v.y2_title, font: { size: 11 } }, overlaying: "y", side: "right", showgrid: false,
      type: log ? "log" : "linear", range: yRange(v.traces, "y2", x0, log) };
    if (v.traces.length > 1) layout.margin.b = 64;
    Plotly.react(el, traces, layout, { responsive: true, displayModeBar: false, locale: "zh-TW" });
    st.drawn = true;
  }

  list.addEventListener("click", (e) => {
    const b = e.target.closest(".seg button"); if (!b) return;
    const card = b.closest(".chart-card"); const id = card.id.slice(6); const st = state[id];
    const role = b.parentElement.dataset.role;
    if (role === "log") { st.log = !st.log; b.setAttribute("aria-pressed", st.log); }
    else {
      b.parentElement.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b));
      if (role === "view") st.view = +b.dataset.i;
      if (role === "range") st.years = +b.dataset.y;
    }
    draw(id);
  });

  // 只在圖表捲入畫面時才繪製，手機比較順
  let io;
  function observeCharts() {
    if (io || !window.Plotly) return;
    io = new IntersectionObserver((ents) => ents.forEach((en) => {
      if (en.isIntersecting) { const id = en.target.dataset.chart; if (!state[id].drawn) draw(id); }
    }), { rootMargin: "300px" });
    list.querySelectorAll(".plot").forEach((p) => io.observe(p));
  }
  chips($("#chart-filter"), (stage) => {
    list.querySelectorAll(".chart-card").forEach((card) => {
      card.hidden = !(stage === "全部" || card.dataset.stages.split(",").includes(stage));
    });
  }, "chartStage");

  // 深淺色切換時重畫
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    Object.keys(state).forEach((id) => state[id].drawn && draw(id));
  });

  showTab(store.get("tab") || "overview");
})();
