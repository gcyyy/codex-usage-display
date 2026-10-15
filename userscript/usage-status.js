// Codex++ user script: 今日模型用量 · API 等价估算
// Pair locally with `codex-usage-collector pair`. No credentials/model API calls.
(() => {
  "use strict";
  const KEY = "codex-usage-status";
  window.__codexUsageStatus?.destroy();
  const config = /*__PAIRING_CONFIG__*/null;
  const scriptKey = window.__codexPlusUserScripts?.currentKey || KEY;
  let destroyed = false, opened = false, latest = null, offline = false, busy = false;
  let failure = null, requestStartedAt = 0, anchorControl = null, drag = null;
  let connectionLogged = false;
  const POSITION_KEY = `${KEY}-titlebar-offset-v1`;
  let offset = {x:0, y:0};
  try {
    const saved = JSON.parse(localStorage.getItem(POSITION_KEY));
    if (saved && Number.isFinite(saved.x) && Number.isFinite(saved.y)) offset = {x:Math.min(0, Math.max(-10000, saved.x)), y:Math.max(-32, Math.min(32, saved.y))};
  } catch {}
  let timer = null, mountTimer = null, requestTimer = null, controller = null;
  let includeInternal = false, includeCLI = false, includeOther = false, sort = "tokens";
  const host = document.createElement("div");
  host.id = KEY;
  host.setAttribute("data-codex-plus-ext", scriptKey);
  const shadow = host.attachShadow({ mode: "open" });
  const style = document.createElement("style");
  style.textContent = `
    :host { --bg:#fff; --fg:#21252b; --muted:#606973; --line:#e3e7eb; --surface:#f5f7f9; --accent:#387a66;
      --warn:#956317; display:block; margin:0; color:var(--fg); font:12px/1.5 "Segoe UI",system-ui,sans-serif;
      color-scheme:light; font-variant-numeric:tabular-nums; }
    :host([data-dark]) { --bg:#222529; --fg:#f0f2f4; --muted:#a4adb6; --line:#3c4147; --surface:#2b3035;
      --accent:#86c4ac; --warn:#e9bd70; color-scheme:dark; }
    * { box-sizing:border-box; } button,select,input { font:inherit; color:inherit; } button { cursor:pointer; }
    button:focus-visible,select:focus-visible,summary:focus-visible,a:focus-visible { outline:2px solid var(--accent); outline-offset:3px; }
    button { border:1px solid var(--line); background:var(--bg); border-radius:8px; padding:6px 9px; }
    .dock { display:flex; align-items:center; border:1px solid var(--line); border-radius:7px; background:var(--surface); max-width:260px; min-width:0; -webkit-app-region:no-drag; app-region:no-drag; }
    .dock:hover { border-color:var(--accent); }
    #entry { min-width:0; max-width:240px; padding:3px 7px 3px 3px; border:0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; text-align:center; background:transparent; font-size:11px; line-height:18px; -webkit-app-region:no-drag; app-region:no-drag; }
    #move { flex:none; width:17px; align-self:stretch; padding:0; border:0; background:transparent; color:var(--muted); cursor:grab; touch-action:none; -webkit-app-region:no-drag; app-region:no-drag; }
    #move:active { cursor:grabbing; }
    #card { position:fixed; z-index:10001; width:min(390px,calc(100vw - 24px)); max-height:calc(100vh - 48px);
      overflow:auto; padding:18px; background:var(--bg); border:1px solid var(--line); border-radius:14px;
      box-shadow:0 8px 38px #0003; }
    [hidden] { display:none !important; } h2 { font-size:16px; margin:0; font-weight:650; }
    .head,.row,.bottom { display:flex; align-items:center; justify-content:space-between; gap:10px; }
    .muted { color:var(--muted); } .small { font-size:11px; } .warning { color:var(--warn); }
    .scope { margin:3px 0 14px; } .stats { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin:12px 0; }
    .stat { padding:12px; background:var(--surface); border-radius:10px; } .value { display:block; font-size:23px; font-weight:650; letter-spacing:-.5px; }
    .label { color:var(--muted); font-size:11px; } .status { padding:9px; background:var(--surface); border-radius:8px; margin:8px 0; }
    .tools { display:flex; justify-content:space-between; align-items:center; gap:8px; margin:16px 0 8px; }
    select { border:1px solid var(--line); border-radius:6px; padding:3px 5px; background:var(--bg); max-width:140px; }
    details.model { border-bottom:1px solid var(--line); padding:9px 0; }
    summary { cursor:pointer; list-style:none; } summary::-webkit-details-marker { display:none; }
    .name { min-width:0; overflow-wrap:anywhere; font-weight:600; } .numbers { flex-shrink:0; text-align:right; }
    .bar { display:flex; height:8px; border-radius:4px; background:var(--line); margin:7px 0 0; overflow:hidden; }
    .bar span { display:block; height:100%; flex:none; }
    .token-legend { display:flex; flex-wrap:wrap; gap:4px 12px; margin:8px 0; }
    .token-key { display:inline-flex; align-items:center; gap:5px; }
    .token-dot { display:inline-block; width:8px; height:8px; border-radius:2px; flex:none; }
    .breakdown { margin:10px 0 2px; } .breakdown .row { margin:3px 0; } .breakdown span:first-child { color:var(--muted); }
    .reason { margin:8px 0 0; color:var(--warn); font-size:11px; } .empty { text-align:center; padding:24px 8px; color:var(--muted); }
    .bottom { margin-top:16px; padding-top:12px; border-top:1px solid var(--line); flex-wrap:wrap; }
    .options label { display:block; margin:6px 0; } input { accent-color:var(--accent); }
    .disclaimer { margin:10px 0 0; color:var(--muted); font-size:11px; }
    .pricing { margin-top:12px; } .pricing p { margin:7px 0; } a { color:var(--accent); }
    .pricing > summary { display:flex; align-items:center; justify-content:space-between; padding:9px 11px;
      border:1px solid var(--accent); border-radius:8px; background:var(--surface); color:var(--accent); font-weight:600; }
    .pricing > summary:hover { background:var(--line); }
    .pricing > summary::after { content:"＋"; font-size:15px; }
    .pricing[open] > summary::after { content:"−"; }
    .internal { margin-top:12px; } ul { padding-left:18px; } li { margin:4px 0; }
    @media(prefers-reduced-motion:no-preference) { #entry { transition:border-color .15s; } }
  `;
  shadow.append(style);
  const entry = document.createElement("button");
  entry.id = "entry";
  entry.type = "button";
  entry.textContent = "今日用量 · 连接中…";
  entry.setAttribute("aria-expanded", "false");
  entry.setAttribute("aria-controls", "card");
  entry.setAttribute("aria-haspopup", "dialog");
  const card = document.createElement("section");
  card.id = "card";
  card.hidden = true;
  card.tabIndex = -1;
  card.setAttribute("role", "dialog");
  card.setAttribute("aria-label", "今日模型用量与 API 等价估算");
  const dock = document.createElement("div");
  dock.className = "dock";
  const move = document.createElement("button");
  move.id = "move";
  move.type = "button";
  move.textContent = "⠿";
  move.setAttribute("aria-label", "移动用量入口");
  move.title = "拖动调整位置；方向键微调；双击或 Home 键恢复右上角";
  dock.append(move, entry);
  shadow.append(dock, card);
  // Inline host geometry also wins over broad host-app styles outside the shadow root.
  for (const [key,value] of Object.entries({position:"fixed",display:"block",margin:"0",left:"auto",bottom:"auto",right:"146px",top:"3px",width:"max-content","z-index":"2147483000","-webkit-app-region":"no-drag","app-region":"no-drag"})) host.style.setProperty(key,value,"important");

  const el = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = String(text);
    if (className) node.className = className;
    return node;
  };
  const tokens = n => n == null ? "—" : n >= 1e6 ? `${(n / 1e6).toFixed(2)}M` : n >= 1000 ? `${(n / 1000).toFixed(1)}K` : String(n);
  const exact = n => n == null ? "未知" : Number(n).toLocaleString("zh-CN");
  const dollars = s => s == null ? "—" : Number(s) > 0 && Number(s) < .01 ? "<$0.01" : `$${Number(s).toLocaleString("en-US", {minimumFractionDigits:2,maximumFractionDigits:2})}`;
  const localTime = s => s ? new Date(s).toLocaleTimeString("zh-CN", {hour12:false}) : "尚未完成扫描";
  const button = (text, action) => {
    const node = el("button", text);
    node.type = "button";
    node.addEventListener("click", action);
    return node;
  };
  function theme() {
    const root = document.documentElement;
    const explicit = root.getAttribute("data-theme") || root.getAttribute("data-color-mode");
    const isDark = explicit ? explicit === "dark" : root.classList.contains("dark") || getComputedStyle(root).colorScheme === "dark" || media.matches;
    host.toggleAttribute("data-dark", isDark);
  }
  function mount() {
    if (destroyed || host.isConnected) return;
    document.body?.append(host);
    placeEntry();
    position();
  }
  const CONTROL_SELECTOR = '[aria-label="Minimize" i],[aria-label="Minimize window" i],[aria-label="最小化"],[title="Minimize" i],[title="最小化"],[data-testid="window-minimize"],[data-testid="minimize-button"],[data-tauri-action="minimize"]';
  function captionArea() {
    if (!anchorControl?.isConnected) anchorControl = null;
    const candidates = [...new Set([anchorControl, ...document.querySelectorAll(CONTROL_SELECTOR)].filter(Boolean))];
    for (const candidate of candidates) {
      const control = candidate.closest('button,[role="button"]') || candidate;
      const rect = control.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0 && rect.top >= 0 && rect.top < 64 && rect.left > window.innerWidth / 2) {
        anchorControl = control;
        return {end:rect.left, top:rect.top, height:rect.height};
      }
    }
    const area = navigator.windowControlsOverlay?.visible && navigator.windowControlsOverlay.getTitlebarAreaRect();
    if (area?.width > 0 && area.height > 0) return {end:area.x + area.width, top:area.y, height:area.height};
    // Native caption controls may be outside the DOM. Reserve all three Windows buttons.
    const reserved = Number.isFinite(config?.captionButtonsWidth) ? Math.max(120, config.captionButtonsWidth) : 138;
    return {end:Math.max(94, window.innerWidth - reserved), top:0, height:32};
  }
  function hostZoom() {
    return host.offsetWidth ? host.getBoundingClientRect().width / host.offsetWidth || 1 : 1;
  }
  function setHostStyle(key, value) {
    if (host.style.getPropertyValue(key) !== value) host.style.setProperty(key,value,"important");
  }
  function placeEntry() {
    if (destroyed || !host.isConnected) return;
    const area = captionArea(), zoom = hostZoom();
    setHostStyle("max-width", `${Math.max(70, area.end - 16) / zoom}px`);
    dock.style.maxWidth = `${Math.min(260, Math.max(70, area.end - 16) / zoom)}px`;
    const box = dock.getBoundingClientRect();
    const gap = 8;
    const naturalRight = window.innerWidth - area.end + gap;
    const maxLeftShift = Math.max(0, area.end - gap - box.width - 8);
    const right = naturalRight + Math.min(maxLeftShift, Math.max(0, -offset.x));
    const naturalTop = area.top + Math.max(0, (area.height - box.height) / 2);
    const top = Math.max(area.top, Math.min(area.top + Math.max(0, area.height - box.height), naturalTop + offset.y));
    setHostStyle("right", `${right / zoom}px`);
    setHostStyle("top", `${top / zoom}px`);
  }
  function savePosition() {
    try { localStorage.setItem(POSITION_KEY, JSON.stringify(offset)); } catch {}
  }
  function resetPosition() {
    offset = {x:0,y:0};
    try { localStorage.removeItem(POSITION_KEY); } catch {}
    placeEntry(); position();
  }
  function startDrag(e) {
    if (e.button !== 0 || destroyed) return;
    e.preventDefault();
    drag = {id:e.pointerId, x:e.clientX, y:e.clientY, start:{...offset}};
    move.setPointerCapture(e.pointerId);
  }
  function dragMove(e) {
    if (!drag || drag.id !== e.pointerId) return;
    offset = {x:Math.min(0, drag.start.x + e.clientX - drag.x),y:drag.start.y + e.clientY - drag.y};
    placeEntry(); position();
  }
  function endDrag(e) {
    if (!drag || drag.id !== e.pointerId) return;
    if (move.hasPointerCapture(e.pointerId)) move.releasePointerCapture(e.pointerId);
    drag = null; savePosition();
  }
  function moveKey(e) {
    if (e.key === "Home") { e.preventDefault(); resetPosition(); return; }
    const delta = {ArrowLeft:[-8,0],ArrowRight:[8,0],ArrowUp:[0,-2],ArrowDown:[0,2]}[e.key];
    if (!delta) return;
    e.preventDefault(); offset.x = Math.min(0, offset.x + delta[0]); offset.y += delta[1];
    savePosition(); placeEntry(); position();
  }
  function position() {
    if (!opened || destroyed) return;
    const rect = entry.getBoundingClientRect();
    const zoom = hostZoom(), width = Math.min(390, window.innerWidth - 24);
    const availableHeight = Math.max(80, window.innerHeight - rect.bottom - 20);
    card.style.width = `${width / zoom}px`;
    card.style.maxHeight = `${availableHeight / zoom}px`;
    card.style.left = `${Math.max(12, Math.min(rect.right - width, window.innerWidth - width - 12)) / zoom}px`;
    const height = Math.min(card.scrollHeight * zoom + 2, availableHeight);
    card.style.top = `${Math.max(12, Math.min(rect.bottom + 8, window.innerHeight - height - 12)) / zoom}px`;
  }
  function setOpen(next, restoreFocus = true) {
    if (destroyed) return;
    opened = next;
    entry.setAttribute("aria-expanded", String(next));
    card.hidden = !next;
    if (next) { render(); position(); card.focus(); refresh(); }
    else { if (restoreFocus) entry.focus(); schedule(); }
  }
  function stats(label, value) {
    const block = el("div", null, "stat");
    block.append(el("span", label, "label"), el("span", value, "value"));
    return block;
  }
  const tokenTypes = {
    uncached: ["未命中缓存输入", "#448de0"],
    cacheRead: ["缓存命中", "#37a879"],
    cacheWrite: ["缓存写入", "#d99a32"],
    output: ["非推理输出", "#9b78d5"],
    reasoning: ["推理输出", "#dd779c"],
    unknown: ["分类未知", "#88929e"]
  };
  const validCount = n => Number.isSafeInteger(n) && n >= 0;
  const percent = (n, total) => total > 0 ? `${(n / total * 100).toFixed(1)}%` : "0.0%";
  function tokenParts(model) {
    const t = model.totals, parts = [];
    const add = (key, count) => { if (count > 0) parts.push({key, count}); };
    if (!validCount(t.total)) return parts;
    if (!validCount(t.input) || !validCount(t.output) || t.input + t.output !== t.total) {
      add("unknown", t.total); return parts;
    }
    const read = validCount(t.cacheRead) && t.cacheRead <= t.input ? t.cacheRead : null;
    const writeKnown = validCount(t.cacheWrite) && read !== null && read + t.cacheWrite <= t.input &&
      !model.reasons.some(r => ["unknown_cache_write_semantics", "invalid_subcategory"].includes(r.code));
    if (read !== null) add("cacheRead", read);
    if (writeKnown) {
      add("uncached", t.input - read - t.cacheWrite);
      add("cacheWrite", t.cacheWrite);
    } else add("unknown", t.input - (read ?? 0));
    if (validCount(t.reasoning) && t.reasoning <= t.output) {
      add("output", t.output - t.reasoning);
      add("reasoning", t.reasoning);
    } else add("unknown", t.output);
    return parts;
  }
  function tokenKey(key, label = tokenTypes[key][0]) {
    const item = el("span", null, "token-key");
    const dot = el("span", null, "token-dot");
    dot.style.background = tokenTypes[key][1];
    dot.setAttribute("aria-hidden", "true");
    item.append(dot, document.createTextNode(label));
    return item;
  }
  function modelRow(model, total) {
    const detail = el("details", null, "model");
    detail.dataset.model = model.modelId;
    const summary = el("summary");
    const row = el("div", null, "row");
    row.append(el("span", model.modelId, "name"));
    const numbers = el("span", null, "numbers");
    numbers.append(el("span", tokens(model.totals.total)), el("div", `${model.costUSD == null && model.knownSubtotalUSD != null ? "部分 " : ""}${dollars(model.costUSD ?? model.knownSubtotalUSD)}`, "muted small"));
    row.append(numbers);
    const bar = el("div", null, "bar");
    const parts = tokenParts(model);
    const descriptions = parts.map(({key, count}) => `${tokenTypes[key][0]}：${exact(count)} Token，占该模型 ${percent(count, model.totals.total)}`);
    bar.setAttribute("role", "img");
    bar.setAttribute("aria-label", `${model.modelId} Token 构成；${descriptions.join("；")}`);
    parts.forEach(({key, count}, i) => {
      const fill = el("span");
      fill.dataset.tokenType = key;
      fill.style.width = `${total > 0 ? count / total * 100 : 0}%`;
      fill.style.background = tokenTypes[key][1];
      fill.title = descriptions[i];
      bar.append(fill);
    });
    summary.append(row, bar);
    detail.append(summary);
    const breakdown = el("div", null, "breakdown");
    breakdown.append(el("div", `占今日模型用量 ${percent(model.totals.total, total)}`, "muted small"));
    parts.forEach(({key, count}) => {
      const r = el("div", null, "row small token-part");
      r.append(tokenKey(key), el("span", `${exact(count)} · ${percent(count, model.totals.total)}`));
      breakdown.append(r);
    });
    if (model.rates) {
      breakdown.append(el("p", "美元 / 百万 Token · Standard", "muted small"));
      for (const context of model.rateContexts.length ? model.rateContexts : ["short"]) {
        const rate = context === "long" ? model.rates.long.rates : model.rates.short;
        breakdown.append(el("div", `${context === "long" ? "长上下文" : "短上下文"}：输入 ${rate.uncachedInput ?? "未知"} / 读取 ${rate.cacheReadInput ?? "未知"} / 写入 ${rate.cacheWriteInput ?? "未知"} / 输出 ${rate.output ?? "未知"}`, "small muted"));
      }
      breakdown.append(el("div", `长上下文：输入 > ${exact(model.rates.long.thresholdInputTokens)} Token`, "small muted"));
    }
    model.reasons.forEach(r => breakdown.append(el("div", `${r.message}（${r.count}）`, "reason")));
    detail.append(breakdown);
    return detail;
  }
  function render() {
    if (destroyed) return;
    const focus = shadow.activeElement;
    const focusIndex = focus ? [...card.querySelectorAll("button,select,input,summary,a")].indexOf(focus) : -1;
    const scrollTop = card.scrollTop;
    const expanded = new Set([...card.querySelectorAll("details[open]")].map(n => n.dataset.model || n.dataset.section));
    card.replaceChildren();
    const head = el("div", null, "head");
    head.append(el("h2", "今日用量"), button("关闭", () => setOpen(false)));
    card.append(head);
    if (!config) {
      entry.textContent = "今日用量 · 未配对";
      card.append(el("p", "先运行采集器的 pair 命令，导入本机生成的脚本。", "status"));
      return;
    }
    if (!latest) {
      entry.textContent = offline ? failure === "csp_blocked" ? "今日用量 · 页面连接受限" : "今日用量 · 采集器未连接" : "今日用量 · 连接中…";
      card.append(el("div", offline ? connectionMessage() : "等待首次索引…", "status"), button("重试", refresh));
      if (offline) card.append(el("p", "安装目录 → scripts → Start-Collector.ps1。后台健康正常但仍无法连接时，请记录这里的连接状态。", "muted small"));
      return;
    }
    const data = latest;
    const estimate = data.totalCostUSD ?? data.knownSubtotalUSD;
    const total = data.totals.total;
    const partial = data.totalCostUSD == null;
    const staleDay = data.date !== new Intl.DateTimeFormat("en-CA", { timeZone:data.timezone, year:"numeric",month:"2-digit",day:"2-digit" }).format(new Date());
    entry.textContent = `${offline || staleDay ? "旧数据" : data.dataStatus === "indexing" ? "统计中" : data.dataStatus !== "complete" ? "部分记录" : "今日"} ${tokens(total)} · ${partial && estimate != null ? "部分 " : ""}${estimate != null ? "≈" : ""}${dollars(estimate)}`;
    card.append(el("div", `${data.date} · ${data.timezone} · 本机 ${data.sourceScope.homes} 个 home`, "muted small scope"));
    const top = el("div", null, "stats");
    top.append(stats("总 Token", tokens(total)), stats(partial && estimate != null ? "已定价部分估算" : "API 等价估算", dollars(estimate)));
    card.append(top);
    if (offline || staleDay) card.append(el("div", `${offline ? connectionMessage() : "日期已变化，等待当日数据。"} · 旧数据 ${data.generatedAt}`, "status warning"));
    if (data.dataStatus !== "complete") card.append(el("div", {indexing:"正在索引历史日志，当前数值尚不完整。",partial:"部分记录 · 存在待核验或无法读取的日志。",unavailable:"会话目录不可用，当前没有可靠统计。"}[data.dataStatus] || "统计状态未知", "status warning"));
    if (data.priceStatus !== "complete") card.append(el("div", estimate == null ? `暂无匹配价格 · 未定价 ${tokens(data.unpricedTokens)} Token` : `未定价 ${tokens(data.unpricedTokens)} Token · 完整金额未知`, "status warning"));
    if (data.diagnostics.some(d => d.code === "price_table_stale" || d.code === "invalid_price_table")) card.append(el("div", "价格表过旧或更新无效，请查看价格口径。", "status warning"));
    const tools = el("div", null, "tools");
    tools.append(el("span", "按模型 · 今日 Token 占比", "muted small"));
    const select = el("select");
    select.setAttribute("aria-label", "模型排序");
    [["tokens", "Token 排序"], ["cost", "估算金额排序"]].forEach(([value, label]) => {
      const option = el("option", label); option.value = value; option.selected = value === sort; select.append(option);
    });
    select.addEventListener("change", () => { sort = select.value; render(); card.querySelector("select")?.focus(); });
    tools.append(select);
    card.append(tools);
    const legend = el("div", null, "token-legend small muted");
    Object.keys(tokenTypes).forEach(key => legend.append(tokenKey(key)));
    legend.title = "条长为模型占比，颜色为 Token 构成";
    card.append(legend);
    const models = [...data.models].sort((a,b) => sort === "cost" ? Number(b.knownSubtotalUSD ?? -1) - Number(a.knownSubtotalUSD ?? -1) : b.totals.total - a.totals.total);
    if (!models.length) card.append(el("div", data.dataStatus === "complete" ? "今天暂无用量" : "尚未读取到可统计用量", "empty"));
    models.forEach(m => card.append(modelRow(m, total)));
    if (data.internalModels.length) {
      const group = el("details", null, "internal"); group.dataset.section = "internal";
      group.append(el("summary", "内部活动（未计入主合计）"));
      data.internalModels.forEach(m => group.append(modelRow(m, data.internalModels.reduce((n,m) => n + m.totals.total,0))));
      card.append(group);
    }
    const options = el("details", null, "options pricing"); options.dataset.section = "options";
    options.append(el("summary", "统计范围"));
    [["包含内部活动", includeInternal, n => includeInternal = n], ["包含 CLI", includeCLI, n => includeCLI = n], ["包含 IDE / 未知来源", includeOther, n => includeOther = n]].forEach(([text, checked, change]) => {
      const label = el("label"); const input = el("input"); input.type = "checkbox"; input.checked = checked;
      input.addEventListener("change", () => { change(input.checked); refresh(); });
      label.append(input, document.createTextNode(` ${text}`)); options.append(label);
    });
    options.append(el("p", "仅统计本机日志，可能包含多个账号。", "muted small"));
    card.append(options);
    const bottom = el("div", null, "bottom");
    const update = button(busy ? "刷新中…" : "刷新", refresh); update.disabled = busy;
    bottom.append(el("span", `最后扫描 ${localTime(data.lastSuccessfulScanAt)}`, "muted small"), update);
    card.append(bottom);
    const pricing = el("details", null, "pricing"); pricing.dataset.section = "pricing";
    pricing.append(el("summary", "价格口径与覆盖情况"));
    pricing.append(el("p", "按 Standard API 单价估算，非订阅实际扣费。", "disclaimer"));
    pricing.append(el("p", "图片计入输入，暂无独立占比。", "disclaimer"));
    pricing.append(el("p", `按价格表 ${data.pricing.verifiedAt || "未知"} 估算 · ${data.pricing.priceVersion || "无有效价格表"}`, "muted small"));
    pricing.append(el("p", `已定价 ${tokens(data.pricedTokens)} / 未定价 ${tokens(data.unpricedTokens)} Token`, "muted small"));
    pricing.append(el("p", "仅估算 Token 费用，不含工具、独立媒体生成及其他费用。", "disclaimer"));
    const link = el("a", "官方 API 定价"); link.href = "https://developers.openai.com/api/docs/pricing"; link.target = "_blank"; link.rel = "noopener noreferrer"; pricing.append(link);
    if (data.diagnostics.length) {
      const list = el("ul", null, "small"); data.diagnostics.forEach(d => list.append(el("li", `${d.message}（${d.count}）`))); pricing.append(list);
    }
    card.append(pricing);
    card.querySelectorAll("details").forEach(n => n.open = expanded.has(n.dataset.model || n.dataset.section));
    card.scrollTop = scrollTop;
    if (focusIndex >= 0 && focus?.isConnected === false) card.querySelectorAll("button,select,input,summary,a")[focusIndex]?.focus({preventScroll:true});
    position();
  }
  function schedule() {
    clearTimeout(timer);
    if (!destroyed && config) timer = setTimeout(refresh, opened ? 5000 : 30000);
  }
  function connectionMessage() {
    return {
      csp_blocked:"宿主页面的 connect-src 安全策略阻止访问本地采集器。需要宿主提供受控连接接口，重新启动采集器不能解除此限制。",
      authorization_failed:"采集器已响应，但配对令牌或页面来源未通过校验。请检查本机配对脚本与允许来源。",
      bridge_unavailable:"宿主用量桥接未连通，请确认已安装版本公开支持该接口。",
      bridge_not_paired:"宿主尚未启用本地用量桥接，请运行桥接配对安装程序。",
      bridge_timeout:"用量采集器响应超时，稍后重试。",
      bad_response:"采集器返回的汇总格式不受支持，请更新采集器与用户脚本。",
      network_unreachable:"无法连接本地采集器。请先启动已安装的采集器，再点击重试；也可能是页面来源或网络策略限制。"
    }[failure] || "本地采集器未连接，请检查后台运行状态。";
  }
  async function refresh() {
    if (destroyed || busy || !config) return;
    clearTimeout(timer);
    busy = true;
    failure = null;
    requestStartedAt = performance.now();
    controller = new AbortController();
    requestTimer = setTimeout(() => controller?.abort(), 6000);
    try {
      let result;
      const options = {includeInternal, includeCLI, includeOther};
      if (config.transport === "bridge") {
        // Public, explicitly allowlisted read-only bridge. Pairing token stays in the backend.
        try { result = await window.codexPlus.call("/usage-status/today", options, {timeout:6000}); }
        catch (error) {
          const code = String(error?.message || "").match(/^USAGE_[A-Z_]+/)?.[0];
          failure = ({USAGE_NOT_PAIRED:"bridge_not_paired",USAGE_DISABLED:"bridge_not_paired",USAGE_PAIRING_INVALID:"bridge_not_paired",
            USAGE_AUTH_FAILED:"authorization_failed",USAGE_TIMEOUT:"bridge_timeout",USAGE_OFFLINE:"network_unreachable",
            USAGE_BAD_RESPONSE:"bad_response",USAGE_RESPONSE_TOO_LARGE:"bad_response"})[code] || "bridge_unavailable";
          throw new Error("bridge_failed");
        }
      } else {
        const endpoint = new URL(config.endpoint);
        if (endpoint.protocol !== "http:" || endpoint.hostname !== "127.0.0.1" || endpoint.username || endpoint.password) throw new Error("Invalid local endpoint");
        const query = new URLSearchParams(Object.entries(options).map(([k,v]) => [k,String(v)]));
        const response = await fetch(`${endpoint.origin}/v1/today?${query}`, {headers:{Authorization:`Bearer ${config.token}`},signal:controller.signal,cache:"no-store",credentials:"omit",redirect:"error"});
        if (!response.ok) { failure = response.status === 403 ? "authorization_failed" : "network_unreachable"; throw new Error("Collector unavailable"); }
        result = await response.json();
      }
      if (destroyed) return;
      if (result?.schemaVersion !== "1" || !Array.isArray(result.models) || !result.totals || !Array.isArray(result.internalModels)) { failure = "bad_response"; throw new Error("Unsupported schema"); }
      latest = result;
      offline = false;
      if (!connectionLogged && config.transport === "bridge") {
        connectionLogged = true;
        // One fixed diagnostic marker lets installation verify real renderer -> backend connectivity.
        window.codexPlus.call("/diagnostics/log", {event:"usage_status_connected",transport:"bridge",schemaVersion:"1"}).catch(() => {});
      }
    } catch {
      if (!destroyed) { offline = true; failure ||= "network_unreachable"; }
    } finally {
      clearTimeout(requestTimer);
      controller = null;
      busy = false;
      if (!destroyed) { render(); placeEntry(); position(); schedule(); }
    }
  }
  const onEntry = () => setOpen(!opened);
  const onPointer = e => { if (opened && !e.composedPath().includes(host)) setOpen(false, false); };
  const onKey = e => { if (opened && e.key === "Escape") { e.preventDefault(); setOpen(false); } };
  const onResize = () => { placeEntry(); position(); };
  const onOnline = () => refresh();
  const onCsp = e => {
    if (destroyed || !config || config.transport === "bridge" || !String(e.effectiveDirective || e.violatedDirective).startsWith("connect-src")) return;
    if (!busy && (!offline || performance.now() - requestStartedAt > 1500)) return;
    try {
      if (new URL(e.blockedURI).origin !== new URL(config.endpoint).origin) return;
    } catch { return; }
    failure = "csp_blocked";
    if (!busy) { render(); placeEntry(); position(); }
  };
  entry.addEventListener("click", onEntry);
  document.addEventListener("pointerdown", onPointer, true);
  document.addEventListener("keydown", onKey, true);
  window.addEventListener("resize", onResize);
  window.addEventListener("online", onOnline);
  document.addEventListener("securitypolicyviolation", onCsp);
  move.addEventListener("pointerdown", startDrag);
  move.addEventListener("pointermove", dragMove);
  move.addEventListener("pointerup", endDrag);
  move.addEventListener("pointercancel", endDrag);
  move.addEventListener("lostpointercapture", endDrag);
  move.addEventListener("dblclick", resetPosition);
  move.addEventListener("keydown", moveKey);
  const overlay = navigator.windowControlsOverlay;
  overlay?.addEventListener("geometrychange", onResize);
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  media.addEventListener("change", theme);
  const observer = new MutationObserver(records => {
    if (destroyed) return;
    theme();
    if (!host.isConnected && mountTimer == null) mountTimer = setTimeout(() => { mountTimer = null; mount(); }, 100);
    const captionChanged = records.some(r => r.target === document.documentElement || r.target === document.body || r.target === anchorControl ||
      [...r.addedNodes, ...r.removedNodes].some(n => n.nodeType === 1 && n !== host && (n.matches(CONTROL_SELECTOR) || n.querySelector(CONTROL_SELECTOR))));
    if (captionChanged) { placeEntry(); position(); }
  });
  observer.observe(document.documentElement, {childList:true,subtree:true,attributes:true,attributeFilter:["class","data-theme","data-color-mode","style"]});
  function destroy() {
    if (destroyed) return;
    destroyed = true;
    clearTimeout(timer); clearTimeout(mountTimer); clearTimeout(requestTimer);
    controller?.abort(); observer.disconnect();
    if (drag && move.hasPointerCapture(drag.id)) move.releasePointerCapture(drag.id);
    drag = null;
    document.removeEventListener("pointerdown", onPointer, true);
    document.removeEventListener("keydown", onKey, true);
    window.removeEventListener("resize", onResize);
    window.removeEventListener("online", onOnline);
    document.removeEventListener("securitypolicyviolation", onCsp);
    overlay?.removeEventListener("geometrychange", onResize);
    move.removeEventListener("pointerdown", startDrag);
    move.removeEventListener("pointermove", dragMove);
    move.removeEventListener("pointerup", endDrag);
    move.removeEventListener("pointercancel", endDrag);
    move.removeEventListener("lostpointercapture", endDrag);
    move.removeEventListener("dblclick", resetPosition);
    move.removeEventListener("keydown", moveKey);
    media.removeEventListener("change", theme);
    entry.removeEventListener("click", onEntry);
    card.replaceChildren(); shadow.replaceChildren(); host.remove();
    if (window.__codexUsageStatus?.destroy === destroy) delete window.__codexUsageStatus;
  }
  window.__codexUsageStatus = {destroy};
  window.__codexPlusUserScripts?.registerCleanup?.(destroy);
  theme(); mount(); render(); placeEntry(); refresh();
})();
