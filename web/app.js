/* 美國景氣循環儀表板：前端互動 */
(function () {
  "use strict";
  const D = window.DASHBOARD;
  const $ = (s, el) => (el || document).querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const STAGES = ["全部", "復甦期", "成長期", "榮景期", "衰退期", "額外參考"];
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* 無痕模式等 */ } },
  };

  if (!D) { $("#meta").textContent = "資料載入失敗"; return; }
  const fmt = (v) => (v == null ? "—" : Math.abs(v) >= 1000 ? v.toLocaleString("zh-TW", { maximumFractionDigits: 0 }) : (+v).toFixed(2));

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

  // ── 總覽：景氣階段 ───────────────────────────
  const G = D.stage;
  const STAGE_KEY = { "復甦期": "recovery", "成長期": "growth", "榮景期": "boom", "衰退期": "recession" };
  const LV = { watch: "🟡 觀察", warn: "🟠 警示", confirm: "🔴 確認" };
  const today = new Date((D.generated || "").slice(0, 10) || Date.now());
  const daysSince = (ym) => Math.max(0, Math.round((today - new Date(ym + "-01")) / 864e5));
  if (G) {
    const s = G.stage;
    const nameEl = $("#stage-name");
    nameEl.textContent = s.name;
    nameEl.dataset.stage = s.key;
    $("#stage-reason").textContent = s.reason;
    $("#stage-since").textContent = `自 ${s.since} 起，已持續 ${s.months} 個月｜判斷基準月：${G.asof}`;
    document.querySelectorAll(".cycle-pt").forEach((g) => g.classList.toggle("on", g.dataset.stage === s.key));
    if (G.caveat) { const c = $("#caveat-card"); c.hidden = false; c.innerHTML = `<strong>⚠️ 注意</strong><p class="small">${esc(G.caveat)}</p>`; }

    // 轉折訊號
    const sig = G.signals.length
      ? G.signals.map((x) => `<div class="sig sig-${x.level}">
          <div class="sig-head"><span class="lvl lvl-${x.level}">${esc(x.level_zh)}</span><strong>${esc(x.name)}</strong></div>
          <div class="small muted">成立 ${x.met} / ${x.avail} 項｜自 ${esc(x.since)} 起，已持續約 ${daysSince(x.since)} 天</div>
          ${x.met_labels.length ? `<div class="small">成立的依據：${x.met_labels.map(esc).join("、")}</div>` : ""}
        </div>`).join("")
      : `<p class="muted">目前沒有轉折訊號。</p>`;
    const watching = G.pending.map((p) => `<li>${esc(p.name)}：${p.met} / ${p.avail} 項成立</li>`).join("");
    let extraHtml = "";
    const u = G.special.u_shape || {};
    if (s.key === "boom" && u.extend && u.extend_to) extraHtml += `<p class="small">📌 初領失業救濟金在 ${esc(u.low_date)} 創下本輪新低（${fmt(u.low)} 人），U 型結構尚未形成，榮景期預計至少延續到 ${esc(u.extend_to)}。</p>`;
    if (u.jolts_reversal) extraHtml += `<p class="small">📌 新開職缺同步高點反轉，衰退訊號更強。</p>`;
    $("#signals").innerHTML = sig + extraHtml + `<p class="small muted" style="margin-top:8px">目前監看：</p><ul class="small watch">${watching}</ul>`;

    // 判斷依據
    const icon = (it) => it.met == null ? "—" : it.met || it.recent ? "✓" : it.near ? "△" : "✕";
    const cls = (it) => it.met == null ? "na" : it.met || it.recent ? "met" : it.near ? "near" : "no";
    $("#groups").innerHTML = G.groups.map((g) => {
      const fed = g.key === "recovery" && G.special.fed && G.special.fed.cycle ? (() => {
        const f = G.special.fed;
        return `<p class="small fed">本輪降息起點：${esc(f.start)}（降息前 ${fmt(f.peak)}%）｜累計降息 ${fmt(f.total)} 個百分點（${f.count} 次）｜距離最近一次降息 ${f.hold} 個月</p>`;
      })() : "";
      return `<details class="grp">
        <summary><span class="grp-name">${esc(g.label)}</span>
          <span class="grp-count">${g.met} / ${g.avail} 項成立${g.level_zh ? ` <span class="lvl lvl-${g.level}">${esc(g.level_zh)}</span>` : ""}</span></summary>
        ${g.why && g.why.length ? `<p class="small">目前狀況：${g.why.map(esc).join("、")}</p>` : ""}
        ${g.excluded.length ? `<p class="small muted">資料缺漏、從分母扣除：${g.excluded.map(esc).join("、")}</p>` : ""}
        ${fed}
        <ul class="items">${g.items.map((it) => `<li class="it-${cls(it)}">
          <div><span class="it-icon">${icon(it)}</span><strong>${esc(it.no)}</strong> ${esc(it.label)}${it.manual ? ' <span class="badge">人工登記</span>' : ""}${it.partial ? ' <span class="badge">部分資料缺漏</span>' : ""}${it.recent ? ' <span class="badge">近幾個月內曾成立</span>' : ""}
            <span class="ind-no">指標 ${it.indicators.map((i) => "#" + esc(i)).join(" ")}</span></div>
          <div class="small muted">${esc(it.method)}</div>
          <div class="parts">${it.parts.map((p) => `<span class="part it-${cls(p)}">${icon(p)} ${esc(p.label)}：${esc(p.value)}${p.date ? `（${esc(p.date.slice(0, 7))}）` : ""}｜${esc(p.rule)}</span>`).join("")}</div>
        </li>`).join("")}</ul>
      </details>`;
    }).join("");

    // 投資方向
    $("#invest-title").textContent = `投資方向：${s.name}`;
    $("#invest").innerHTML = (s.boom_year ? `<p><strong>進入榮景期第 ${s.boom_year} 年，建議持股比例下限 ${s.equity_floor}%</strong></p>` : "") +
      `<ol class="invest">${s.invest.map((t) => `<li>${esc(t)}</li>`).join("")}</ol>`;

    // 時間軸
    const t0 = new Date(D.start), t1 = new Date(G.asof + "-28");
    const pos = (d) => ((new Date(d) - t0) / (t1 - t0)) * 100;
    const segs = G.timeline.map(([a, b, n]) => {
      const l = pos(a + "-01"), r = pos((b || G.asof) + "-01");
      return `<div class="tl-seg st-${STAGE_KEY[n]}" style="left:${l}%;width:${Math.max(r - l, 0.3)}%" title="${esc(n)}：${esc(a)} – ${esc(b || "至今")}"></div>`;
    }).join("");
    const recs = D.recessions.map(([a, b]) => `<div class="tl-rec" style="left:${pos(a)}%;width:${Math.max(pos(b || G.asof + "-01") - pos(a), 0.3)}%" title="NBER 衰退：${esc(a)} – ${esc(b || "")}"></div>`).join("");
    const years = []; for (let y = +D.start.slice(0, 4); y <= +G.asof.slice(0, 4); y += 5) years.push(`<span style="left:${pos(y + "-01-01")}%">${y}</span>`);
    $("#timeline").innerHTML = `<div class="tl"><div class="tl-row">${segs}</div><div class="tl-row tl-nber">${recs}</div><div class="tl-axis">${years.join("")}</div></div>
      <div class="tl-legend">${["復甦期", "成長期", "榮景期", "衰退期"].map((n) => `<span><i class="sw st-${STAGE_KEY[n]}"></i>${n}</span>`).join("")}<span><i class="sw tl-rec-sw"></i>NBER 衰退期間</span></div>
      <ul class="small tl-list">${G.timeline.map(([a, b, n]) => `<li>${esc(a)} – ${esc(b || "至今")}：${esc(n)}</li>`).join("")}</ul>`;
    const ev = G.events.slice().reverse().slice(0, 200);
    $("#events").innerHTML = `<p class="small muted">回測產生的歷史（逐月推算，未考慮資料發布延遲與修正），最新的在上，最多顯示 200 筆。</p><ul class="small ev">${ev.map((e) =>
      `<li><span class="ev-date">${esc(e.date)}</span>${e.type === "stage" ? `<strong>階段：${e.from ? esc(e.from) + " → " : ""}${esc(e.to)}</strong>（${esc(e.text)}）`
        : `${esc(e.name)}：${esc(e.from || "無")} → ${esc(e.to || "解除")}${e.text && e.to ? `｜${esc(e.text)}` : ""}`}</li>`).join("")}</ul>`;
  }

  // ── 總覽：股市多轉空風險 ───────────────────────
  const MR = D.market_risk;
  if (MR) {
    const card = $("#risk-card"); card.hidden = false;
    const L = MR.levels;
    const lvl = MR.bear ? `<span class="lvl lvl-confirm">空頭進行中</span>` : MR.level ? `<span class="lvl lvl-${MR.level}">${esc(MR.level_zh)}</span>` : `<span class="lvl lvl-low">低</span>`;
    const pos = Math.max(0, Math.min(100, MR.score ?? 0));
    const ic = (c) => c.met == null ? "—" : c.met ? "✓" : "✕";
    const grp = (t, name) => `<div class="risk-grp"><div class="small muted">${name}</div><ul class="items">${MR.components.filter((c) => c.type === t).map((c) =>
      `<li class="it-${c.met == null ? "na" : c.met ? "met" : "no"}"><div><span class="it-icon">${ic(c)}</span><strong>${esc(c.name)}</strong></div>
        <div class="small muted">${esc(c.rule)}</div><div class="small">${esc(c.value)}</div></li>`).join("")}</ul></div>`;
    card.innerHTML = `<h2>股市多轉空風險</h2>
      <div class="risk-top"><div class="risk-score">${MR.score ?? "—"}<small>／100</small></div>${lvl}
        <span class="small muted">判斷月：${esc(MR.asof)}｜${MR.smooth} 個月平均（本月 ${MR.raw ?? "—"}）｜S&P 500 距高點 ${MR.dd ?? "—"}%</span></div>
      <div class="risk-bar" role="img" aria-label="風險分數 ${MR.score}">
        <i style="left:${L.watch}%"></i><i style="left:${L.warn}%"></i><i style="left:${L.confirm}%"></i><b style="left:${pos}%"></b></div>
      <div class="risk-scale small muted"><span>0</span><span style="left:${L.watch}%" title="${L.watch}">觀察</span><span style="left:${L.warn}%" title="${L.warn}">警示</span><span style="left:${L.confirm}%" title="${L.confirm}">確認</span></div>
      <p class="small">和景氣階段分開計算。回測（1985 年起）：分數 ≥ ${L.confirm} 時，之後 ${MR.backtest.forward_months} 個月 S&P 500 跌 ≥ ${MR.backtest.forward_drop}% 的比例約 ${MR.backtest.buckets[3].hit ?? "—"}%（所有月份平均 ${MR.backtest.base}%）。多數在高點前後 0–3 個月才升高，偏向「早期確認」。</p>
      <details class="grp"><summary><span class="grp-name">各條件明細</span><span class="grp-count">${MR.components.filter((c) => c.met).length} / ${MR.components.filter((c) => c.met != null).length} 項成立</span></summary>
        ${grp("lead", "領先型（通常在股市高點前出現）")}${grp("confirm", "確認型（高點前後才出現）")}
        <p class="small muted">歷史走勢見趨勢圖 #R；回測見「回測」分頁。僅供參考，非投資建議。</p></details>`;
  }

  // ── 回測 ───────────────────────────────────
  const B = D.backtest;
  function strip(timeline, asof) {
    const t0 = new Date(D.start), t1 = new Date(asof + "-28");
    const pos = (d) => ((new Date(d) - t0) / (t1 - t0)) * 100;
    const segs = timeline.map(([a, b, n]) => {
      const l = pos(a + "-01"), r = pos((b || asof) + "-01");
      return `<div class="tl-seg st-${STAGE_KEY[n]}" style="left:${l}%;width:${Math.max(r - l, 0.3)}%" title="${esc(n)}：${esc(a)} – ${esc(b || "至今")}"></div>`;
    }).join("");
    return `<div class="tl-row">${segs}</div>`;
  }
  if (B && G) {
    const asof = G.asof;
    const cell = (d, v) => d ? `${esc(d)}<br><span class="${Math.abs(v) <= 3 ? "lag-ok" : "lag-bad"}">${v > 0 ? "+" : ""}${v} 個月</span>` : `<span class="lag-bad">沒抓到</span>`;
    const sum = (x, name) => `<div class="bt-sum"><div class="bt-name">${name}</div>
      <div class="bt-nums"><span><b>${x.caught}/${B.turns.length}</b> 次衰退抓到</span><span><b>${x.recovered}/${B.turns.length}</b> 次復甦抓到</span>
      <span><b>${x.false.length}</b> 次誤判衰退（${x.false_months} 個月）</span></div>
      ${x.false.length ? `<div class="small muted">誤判：${x.false.map(esc).join("、")}</div>` : ""}</div>`;
    const recs = D.recessions.map(([a, b]) => {
      const t0 = new Date(D.start), t1 = new Date(asof + "-28"); const pos = (d) => ((new Date(d) - t0) / (t1 - t0)) * 100;
      return `<div class="tl-rec" style="left:${pos(a)}%;width:${Math.max(pos(b || asof + "-01") - pos(a), 0.3)}%"></div>`;
    }).join("");
    const crit = B.criteria.map((x) => `<tr><td>${esc(x.no)} ${esc(x.label)}</td><td>${esc(x.ref)}</td>${
      x.timing.length ? x.timing.map((v) => `<td class="num">${v == null ? "—" : (v > 0 ? "+" : "") + v}</td>`).join("") : B.turns.map(() => "<td></td>").join("")
    }<td class="num">${x.met_months}</td><td class="num">${x.false_ratio != null ? x.false_ratio + "%" : x.expansion_ratio != null ? "擴張期 " + x.expansion_ratio + "%" : "—"}</td></tr>`).join("");
    const MB = MR && MR.backtest;
    const lead = (d, v) => d ? `${esc(d)}<br><span class="${v <= 0 ? "lag-ok" : "lag-bad"}">${v > 0 ? "+" : ""}${v} 個月</span>` : `<span class="lag-bad">沒有</span>`;
    const riskBt = MB ? `<div class="card"><h2>股市多轉空風險分數回測</h2>
        <p class="small muted">對照 S&P 500（月平均）。所有月份中，之後 ${MB.forward_months} 個月內跌 ≥ ${MB.forward_drop}% 的比例為 ${MB.base}%。完整報告：<a href="https://github.com/Janine1217/us-business-cycle-tracker/blob/main/docs/%E8%82%A1%E5%B8%82%E9%A2%A8%E9%9A%AA%E5%9B%9E%E6%B8%AC.md" target="_blank" rel="noopener">docs/股市風險回測.md</a></p>
        <div class="tbl-wrap"><table class="tbl"><thead><tr><th>等級</th><th>分數</th><th>月數</th><th>${MB.forward_months} 個月內跌 ≥ ${MB.forward_drop}%</th><th>之後 12 個月報酬中位數</th></tr></thead><tbody>
        ${MB.buckets.map((b) => `<tr><td>${esc(b.name)}</td><td>${esc(b.range)}</td><td class="num">${b.months}</td><td class="num">${b.hit ?? "—"}%</td><td class="num">${b.ret12 ?? "—"}%</td></tr>`).join("")}</tbody></table></div>
        <h3 class="small" style="margin-top:12px">各次空頭：第一次達到各等級（負數＝在高點前）</h3>
        <div class="tbl-wrap"><table class="tbl"><thead><tr><th>S&P 500 高點 → 低點</th><th>🟡 觀察</th><th>🟠 警示</th><th>🔴 確認</th></tr></thead><tbody>
        ${MB.bears.map((b) => `<tr><td>${esc(b.peak)} → ${esc(b.trough)}（${b.depth}%）</td><td>${lead(b.watch, b.watch_lead)}</td><td>${lead(b.warn, b.warn_lead)}</td><td>${lead(b.confirm, b.confirm_lead)}</td></tr>`).join("")}</tbody></table></div>
        <p class="small">🟠 警示區段：${MB.episodes.map((e) => `${esc(e.start)}–${esc(e.end)}${e.hit ? "✓" : e.hit === false ? "✕" : "？"}`).join("、")}（✓ 命中、✕ 誤報）</p></div>` : "";
    $("#backtest").innerHTML = `
      ${riskBt}
      <div class="card"><h2>回測結論（1985-01 至今，對照 NBER 衰退期間）</h2>
        <div class="bt-grid">${sum(B.current, "目前設定（第 5 階段調整後）")}${sum(B.spec, "需求文件原始規則")}</div>
        <p class="small muted">⚠️ 使用修正後的資料（不是當時公布的初值），已粗略考慮發布延遲；只有 4 次衰退可供驗證，參數容易過度貼合歷史。
        完整報告：<a href="https://github.com/Janine1217/us-business-cycle-tracker/blob/main/docs/%E5%9B%9E%E6%B8%AC%E5%A0%B1%E5%91%8A.md" target="_blank" rel="noopener">docs/回測報告.md</a></p></div>
      <div class="card"><h2>階段時間軸對照</h2>
        <div class="small muted">目前設定</div><div class="tl">${strip(G.timeline, asof)}</div>
        <div class="small muted">需求文件原始規則</div><div class="tl">${strip(B.spec.timeline, asof)}</div>
        <div class="small muted">NBER 衰退期間</div><div class="tl"><div class="tl-row tl-nber">${recs}</div></div>
        <div class="tl-legend">${["復甦期", "成長期", "榮景期", "衰退期"].map((n) => `<span><i class="sw st-${STAGE_KEY[n]}"></i>${n}</span>`).join("")}<span><i class="sw tl-rec-sw"></i>NBER 衰退期間</span></div></div>
      <div class="card"><h2>各次轉折：系統判定 vs NBER</h2>
        <p class="small muted">提前為負、落後為正。進入衰退對照 NBER 衰退開始月，進入復甦對照谷底月。</p>
        <div class="tbl-wrap"><table class="tbl"><thead><tr><th>NBER 衰退</th><th>目前設定<br>進入衰退</th><th>進入復甦</th><th>原始規則<br>進入衰退</th><th>進入復甦</th></tr></thead><tbody>
        ${B.current.rows.map((a, i) => { const b = B.spec.rows[i]; return `<tr><td>${esc(a.peak)} – ${esc(a.trough)}</td><td>${cell(a.enter, a.enter_lag)}</td><td>${cell(a.recover, a.recover_lag)}</td><td>${cell(b.enter, b.enter_lag)}</td><td>${cell(b.recover, b.recover_lag)}</td></tr>`; }).join("")}
        </tbody></table></div></div>
      <div class="card"><h2>每一項判斷依據的提前／落後（月）</h2>
        <p class="small muted">第一次成立的月份 − NBER 轉折月。窗口外比例：成立的月份中，落在所有轉折窗口之外的比例（愈高代表誤判愈多）。</p>
        <div class="tbl-wrap"><table class="tbl"><thead><tr><th>判斷依據</th><th>對照</th>${B.turns.map((t) => `<th>${esc(t.peak.slice(0, 4))}</th>`).join("")}<th>成立月數</th><th>窗口外比例</th></tr></thead><tbody>${crit}</tbody></table></div></div>`;
  }

  // ── 待調整事項（docs/待調整事項.md）──────────────
  const TD = D.todo;
  if (TD) {
    const md = (t) => esc(t).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    const src = "https://github.com/Janine1217/us-business-cycle-tracker/blob/main/docs/%E5%BE%85%E8%AA%BF%E6%95%B4%E4%BA%8B%E9%A0%85.md";
    const tab = document.querySelector('[data-tab="todo"]');
    if (tab && TD.open) tab.innerHTML = `待調整 <span class="tab-count">${TD.open}</span>`;
    const item = (x) => `<li class="todo-item${x.done ? " done" : ""}">
        <div class="todo-head"><span class="todo-id">${esc(x.id)}</span><strong class="todo-title">${md(x.title)}</strong>
          <span class="badge ${x.done ? "ok" : "todo-open"}">${md(x.status)}</span></div>
        ${x.now ? `<div class="small"><span class="muted">目前狀況：</span>${md(x.now)}</div>` : ""}
        ${x.idea && !x.done ? `<div class="small"><span class="muted">可能方向（未驗證）：</span>${md(x.idea)}</div>` : ""}
        ${x.config && x.config !== "—" ? `<div class="small muted">相關設定：${md(x.config)}</div>` : ""}
      </li>`;
    const log = TD.log.length ? `<div class="card"><h2>調整紀錄</h2><div class="tbl-wrap"><table class="tbl"><thead><tr>${Object.keys(TD.log[0]).map((k) => `<th>${esc(k)}</th>`).join("")}</tr></thead><tbody>${
      TD.log.map((r) => `<tr>${Object.values(r).map((v) => `<td>${md(v)}</td>`).join("")}</tr>`).join("")}</tbody></table></div></div>` : "";
    $("#todo").innerHTML = `<div class="card"><h2>待調整事項</h2>
        <p><strong>${TD.open}</strong> 項待處理｜<strong>${TD.done}</strong> 項已解決${TD.updated ? `<span class="small muted">（最後整理 ${esc(TD.updated)}）</span>` : ""}</p>
        <p class="small muted">已知、但暫時找不到更好指標或依據的問題。內容來自 <a href="${src}" target="_blank" rel="noopener">docs/待調整事項.md</a>；解決後把該列「狀態」改成「✅ 已解決 日期」，這裡會自動劃線並移到最後。</p></div>` +
      TD.sections.map((s) => `<div class="card"><h2>${esc(s.title)}</h2><ul class="todo-list">${s.items.map(item).join("")}</ul></div>`).join("") + log;
  }

  // ── 總覽：資料狀態 ───────────────────────────
  const failedRows = D.table.filter((r) => r.failed.length);
  $("#health").innerHTML =
    `<div class="health-row"><span>追蹤指標</span><span>${D.table.length} 項</span></div>` +
    `<div class="health-row"><span>最近一次更新失敗</span><span>${failedRows.length
      ? failedRows.map((r) => `<span class="badge fail">✕ #${esc(r.id)} ${esc(r.name)}</span>`).join(" ")
      : '<span class="badge ok">✓ 全部成功</span>'}</span></div>`;

  // ── 指標總表 ───────────────────────────────
  const RULE_ZH = { T1: "下滑", T2: "谷底", T3: "高峰", T4: "落底反彈", T5: "高點反轉", T6: "上揚" };
  const STATE_ZH = { met: "條件成立", near: "接近條件" };
  function renderTable(stage) {
    const rows = D.table.filter((r) => stage === "全部" || r.stages.includes(stage));
    $("#indicator-list").innerHTML = rows.map((r) => {
      const dir = r.chg == null ? "" : r.chg > 0 ? "up" : r.chg < 0 ? "down" : "flat";
      const chg = r.chg == null ? "—" : `${r.chg > 0 ? "+" : ""}${fmt(r.chg)} ${r.chg_unit}`;
      const fail = r.failed.map((f) => `<span class="badge fail">✕ ${esc(f.id)} 最近一次更新失敗，最後成功：${esc(f.last_success || "無")}</span>`).join("");
      const tr = r.trend ? Object.entries(r.trend.rules).filter(([, v]) => v)
        .map(([k, v]) => `<span class="badge rule rule-${v}" title="${v === "met" ? "成立" : "接近（還差 1 期或接近門檻）"}">${k} ${RULE_ZH[k]}${v === "near" ? "（接近）" : ""}</span>`).join("") : "";
      const trLine = r.trend ? `<div class="ind-trend"><span class="small muted">趨勢（${esc(r.trend.basis)}）：</span>${tr || '<span class="small muted">T1–T6 都未成立</span>'}</div>` : "";
      return `<article class="ind${r.state ? " ind-" + r.state : ""}" data-goto="${esc(r.id)}" tabindex="0">
        <div class="ind-head"><span class="ind-name"><span class="ind-no">#${esc(r.id)}</span>${esc(r.name)}</span>${r.state ? `<span class="badge st-badge-${r.state}">${STATE_ZH[r.state]}</span>` : ""}</div>
        <div class="ind-metric">${esc(r.metric)}</div>
        <div class="ind-value">${fmt(r.value)}<small>${esc(r.unit)}</small></div>
        <div class="ind-sub"><span class="${dir}">變化 ${chg}</span><span>前值 ${fmt(r.prev)}</span><span>資料期間 ${esc(r.date.slice(0, 7))}</span></div>
        ${trLine}
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
    const log = c.views.some((v) => v.log_ok) ? `<div class="seg" data-role="log"><button aria-pressed="${!!c.default_log}">對數刻度</button></div>` : "";
    const toggle = c.toggle ? `<div class="seg seg-multi" data-role="toggle" aria-label="開關各條線">${c.views[0].traces.map((t, i) =>
      `<button aria-pressed="true" data-i="${i}"><i class="sw-line" style="background:var(--s${(i % 4) + 1})"></i>${esc(t.name)}</button>`).join("")}</div>` : "";
    const src = c.sources.map((s) =>
      `${esc(s.org)}｜<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.id)}</a> ${esc(s.name)}` +
      (s.failed ? ` <span class="fail">✕ 最近一次更新失敗，最後成功：${esc(s.last_success || "無")}</span>` : "")).join("<br>");
    return `<section class="chart-card" id="chart-${esc(c.id)}" data-stages="${esc(c.stages.join(","))}">
      <h3><span class="ind-no">#${esc(c.id)}</span>${esc(c.title)}</h3>
      <div class="chart-controls">${toggle}${views}${ranges}${log}</div>
      <div class="plot" data-chart="${esc(c.id)}"></div>
      ${c.notes.length ? `<ul class="chart-notes">${c.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
      <div class="chart-src">來源：${src}</div>
    </section>`;
  }).join("");

  const state = {}; // 每張圖目前的 view / range / log
  D.charts.forEach((c) => (state[c.id] = { view: 0, years: 0, log: !!c.default_log, drawn: false, hidden: new Set() }));

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

    const shown = v.traces.filter((t, i) => !st.hidden.has(i));
    const traces = v.traces.map((t, i) => ({
      type: "scatter", mode: "lines", name: t.name, x: t.x, y: t.y, visible: st.hidden.has(i) ? "legendonly" : true,
      yaxis: t.axis === "y2" ? "y2" : "y",
      line: { color: colors[i % colors.length], width: 2, dash: t.dash ? "dot" : "solid" },
      hovertemplate: `%{y:,.2f} ${t.unit}<extra>${t.name}</extra>`,
    }));
    const stageBg = (G ? G.timeline : []).map(([a, b, n]) => ({
      type: "rect", xref: "x", yref: "paper", x0: a + "-01", x1: b ? b + "-01" : lastX, y0: 0, y1: 1,
      fillcolor: css("--st-" + STAGE_KEY[n]), line: { width: 0 }, layer: "below",
    }));
    const shapes = stageBg.concat(D.recessions.map(([a, b]) => ({
      type: "rect", xref: "x", yref: "paper", x0: a, x1: b || lastX, y0: 0, y1: 1,
      fillcolor: css("--recession"), line: { width: 0 }, layer: "below",
    })));
    v.hlines.forEach((h) => shapes.push({
      type: "line", xref: "paper", x0: 0, x1: 1, yref: "y", y0: h.y, y1: h.y,
      line: { color: css("--axis"), width: 1, dash: h.y === 0 ? "solid" : "dash" },
    }));
    const annotations = v.hlines.filter((h) => h.label).map((h) => ({
      xref: "paper", x: 0, yref: "y", y: h.y, text: h.label, showarrow: false,
      xanchor: "left", yanchor: "bottom", font: { size: 11, color: css("--muted") },
    }));
    (v.marks || []).forEach((m) => annotations.push({
      x: m.x, y: log ? Math.log10(m.y) : m.y, xref: "x", yref: "y", text: m.text, showarrow: true, arrowhead: 0,
      arrowcolor: css("--ink-2"), ax: 0, ay: -30,
      font: { size: 11, color: css("--ink") }, bgcolor: css("--surface"), bordercolor: css("--border"), borderpad: 2,
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
      yaxis: { ...axis, title: { text: v.y_title, font: { size: 11 } }, type: log ? "log" : "linear", range: yRange(shown.length ? shown : v.traces, "y", x0, log) },
      shapes, annotations,
    };
    if (hasY2) layout.yaxis2 = { ...axis, title: { text: v.y2_title, font: { size: 11 } }, overlaying: "y", side: "right", showgrid: false,
      type: log ? "log" : "linear", range: yRange(v.traces, "y2", x0, log) };
    if (v.traces.length > 1) layout.margin.b = 64;
    Plotly.react(el, traces, layout, { responsive: true, displayModeBar: false, locale: "zh-TW" });
    if (c.toggle && !el._toggleBound) { // 點圖例也同步開關按鈕
      el._toggleBound = true;
      el.on("plotly_legendclick", (ev) => { setHidden(id, ev.curveNumber); return false; });
    }
    st.drawn = true;
  }

  function setHidden(id, i) {
    const st = state[id];
    st.hidden.has(i) ? st.hidden.delete(i) : st.hidden.add(i);
    const btn = list.querySelector(`#chart-${CSS.escape(id)} [data-role="toggle"] [data-i="${i}"]`);
    if (btn) btn.setAttribute("aria-pressed", !st.hidden.has(i));
    draw(id);
  }

  list.addEventListener("click", (e) => {
    const b = e.target.closest(".seg button"); if (!b) return;
    const card = b.closest(".chart-card"); const id = card.id.slice(6); const st = state[id];
    const role = b.parentElement.dataset.role;
    if (role === "toggle") { setHidden(id, +b.dataset.i); return; }
    if (role === "log") { st.log = !st.log; b.setAttribute("aria-pressed", st.log); }
    else {
      b.parentElement.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b));
      if (role === "view") st.view = +b.dataset.i;
      if (role === "range") st.years = +b.dataset.y;
    }
    draw(id);
  });

  $("#stage-legend").innerHTML = `<span class="small muted">圖表背景：</span>` +
    ["復甦期", "成長期", "榮景期", "衰退期"].map((n) => `<span><i class="sw st-${STAGE_KEY[n]}"></i>系統判定${n}</span>`).join("") +
    `<span><i class="sw tl-rec-sw"></i>NBER 衰退期間</span>`;

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
