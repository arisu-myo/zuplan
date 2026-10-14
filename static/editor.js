const INIT = window.INIT;  // サーバがページに埋め込む(図の一覧と先頭ページ)
const NS = "http://www.w3.org/2000/svg";
const svg = document.getElementById("svg"), wrap = document.getElementById("wrap");
const ed = document.getElementById("ed"), side = document.getElementById("side"), issuesEl = document.getElementById("issues");
const PALETTE = [
  ["フロー", [["start","開始","処理の入口(1ページに1つ)"],["end","終了","処理の出口"],["proc","処理","計算・代入・実行する処理"],
    ["if","判断","条件で分岐。出る矢印にYes/Noなどのラベルを付ける"],["io","入出力","画面表示・入力・ファイル読み書き"],
    ["loop","ループ","繰り返し。出る矢印は「次」「完了」"],["call","呼出","別ページ(関数)の呼び出し"],["screen","画面","画面・ウィンドウ(画面遷移用)"]]],
  ["データ・補足", [["data","データ","データ・書類(実行順には入らない)"],["db","DB","データベース(実行順には入らない)"],
    ["note","メモ","補足メモ(実装しない)"]]]];
const TYPES = PALETTE.flatMap(g => g[1].map(([v, t]) => [v, t]));
const DEFTXT = {start:"開始", end:"終了", proc:"処理", if:"条件?", io:"入出力", loop:"繰り返し", call:"呼出", screen:"画面", data:"データ", db:"DB", note:"メモ"};
const SIDE = new Set(["data", "db", "note"]);
// ページは pid で区別する(名前を変えても変わらない)。最初は一覧(名前・版番号)だけを持ち、
// 中身(nodes/edges)は開いたときにサーバから読む。大きなプロジェクトでも開くのが速く、保存も変わったページだけで済む
let graphs = INIT.pages.map(p => ({pid: p.pid, name: p.name, rev: p.rev, count: p.nodes, loaded: false}));
let cur = 0, sel = null, mode = null, from = null, linkTmp = null;
if (INIT.first) Object.assign(graphs[0], INIT.first, {loaded: true});
let view = {x: -300, y: -60, w: 900, h: 600};
// 図1つ = 1セッション。URL /s/<id> で開き、保存先もこのURLの下
const BASE = "/s/" + INIT.id;
const pageData = g => ({name: g.name,
  nodes: g.nodes.map(n => ({id: n.id, type: n.type, text: n.text, memo: n.memo || "", x: n.x, y: n.y})),
  edges: g.edges.map(e => ({from: e.from, to: e.to, label: e.label || "", memo: e.memo || ""}))});
const pageJson = g => JSON.stringify(pageData(g));
// 最後に保存した状態。保存のときはこれと比べて、変わったページ・並び順だけを送る
const saved = new Map();                                     // pid → 中身のJSON(読み込んだページのみ)
const savedRev = new Map(graphs.map(g => [g.pid, g.rev]));   // pid → 版番号(別の画面での変更を見分ける)
let savedOrder = graphs.map(g => g.pid);
if (INIT.first) saved.set(graphs[0].pid, pageJson(graphs[0]));
const newPid = () => Array.from(crypto.getRandomValues(new Uint8Array(10)), b => "abcdefghijklmnopqrstuvwxyz0123456789"[b % 36]).join("");
function ensureLoaded(g) {
  if (!g || g.loaded || g.missing) return Promise.resolve();
  return g.loading || (g.loading = fetch(BASE + "/page/" + g.pid)
    .then(r => r.status === 404 ? (g.missing = true, null) : r.ok ? r.json() : Promise.reject(r.status))
    .then(p => {
      if (!p) return toast("このページはサーバにありません(別の画面で削除された可能性があります)");
      Object.assign(g, {name: p.name, nodes: p.nodes, edges: p.edges, rev: p.rev, loaded: true});
      saved.set(g.pid, pageJson(g)); savedRev.set(g.pid, p.rev);
    })
    .catch(() => toast("ページを読み込めませんでした。サーバを確認してください"))
    .finally(() => { g.loading = null; }));
}
document.getElementById("path").textContent = INIT.name;
document.getElementById("path").title = "このページのURLを共有すると、同じ図を開けます";

const G = () => graphs[cur];
const node = id => G().nodes.find(n => n.id === id);
// 自動保存(オン/オフを切り替え可能。オンなら変更後に少し待って保存する)
// 設定はサーバのDB(図ごと)に保存するので、どのブラウザで開いても同じになる
let dirty = false, asT = null, autoOn = (INIT.settings || {}).autosave !== false, editSeq = 0;
function setDirty(v, label, color) {
  dirty = v; if (v) editSeq++;
  const d = document.getElementById("dirty");
  d.textContent = label || (v ? (autoOn ? "● 保存待ち" : "● 未保存") : "✓ 保存済み"); d.style.color = color || (v ? "#a15c00" : "#1f7a3a");
  if (v && autoOn) { clearTimeout(asT); asT = setTimeout(() => doSave(true), 1200); }
}
window.addEventListener("beforeunload", e => { if (dirty) { e.preventDefault(); e.returnValue = ""; } });
// 元に戻す: ページの中身の変更はそのページだけ、ページの追加・削除・並べ替えは並び(参照の配列)だけを覚える
// (全ページを丸ごと覚えると、大きなプロジェクトでは1操作ごとに数MBになるため)
const undoStack = [];
function pushUndo(e) { setDirty(true); undoStack.push(e); if (undoStack.length > 100) undoStack.shift(); }
function snapshot(g = G()) { pushUndo({kind: "page", g, data: pageJson(g)}); }
function snapStruct() { pushUndo({kind: "struct", list: graphs.slice(), cur: G()}); }
function undo() {
  const e = undoStack.pop(); if (!e) return;
  setDirty(true); sel = null;
  if (e.kind === "page") {
    Object.assign(e.g, JSON.parse(e.data));
    const i = graphs.indexOf(e.g);
    if (i >= 0 && i !== cur) return switchPage(i);
    return renderAll();
  }
  graphs = e.list;
  const i = graphs.indexOf(e.cur);
  switchPage(i >= 0 ? i : Math.min(cur, graphs.length - 1));
}
let toastT;
function toast(t) {
  const e = document.getElementById("toast"); e.textContent = t; e.classList.add("show");
  clearTimeout(toastT); toastT = setTimeout(() => e.classList.remove("show"), 2600);
}

// ---- サイズ(全角は2文字分で折り返し) ----
const cw = ch => (ch.charCodeAt(0) > 255 ? 2 : 1);
function wrapText(t, max) {
  const lines = []; let line = "", w = 0;
  for (const ch of t) { if (w + cw(ch) > max) { lines.push(line); line = ""; w = 0; } line += ch; w += cw(ch); }
  lines.push(line); return lines;
}
function fit(n) {
  const dia = n.type === "if" || n.type === "loop";
  n.lines = wrapText(n.text || " ", n.type === "if" ? 20 : 26);
  const widest = Math.max(...n.lines.map(l => [...l].reduce((a, c) => a + cw(c), 0)));
  n.w = Math.max(dia ? 150 : 120, widest * 7.5 + (n.type === "if" ? 80 : 40));
  n.h = Math.max(n.type === "if" ? 80 : 44, n.lines.length * 17 + (n.type === "if" ? 56 : n.type === "db" ? 40 : 24));
}

// ---- 描画 ----
function el(tag, attrs, parent) {
  const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (parent) parent.append(e);
  return e;
}
function edgePath(a, b) {
  const forward = b.y - b.h / 2 > a.y + a.h / 2 + 8;
  if (forward) {
    const sx = a.x, sy = a.y + a.h / 2, tx = b.x, ty = b.y - b.h / 2, d = (ty - sy) / 2;
    return {d: `M${sx},${sy} C${sx},${sy + d} ${tx},${ty - d} ${tx},${ty}`, lx: (sx + tx) / 2, ly: (sy + ty) / 2};
  }
  const sx = a.x + a.w / 2, sy = a.y, tx = b.x + b.w / 2, ty = b.y, o = Math.max(sx, tx) + 70;
  return {d: `M${sx},${sy} C${o},${sy} ${o},${ty} ${tx},${ty}`, lx: (sx + 6 * o + tx) / 8, ly: (sy + ty) / 2};
}
const FILL = {start:"#d9f2df", end:"#fbdcdc", proc:"#ffffff", if:"#fff1c4", io:"#dce8fb", loop:"#ebdcf8",
  call:"#ffffff", screen:"#dff1ff", data:"#fff6d6", db:"#e3e9ee", note:"#fff9b8"};
function shapeEl(n, g, stroke, sw) {
  const w = n.w / 2, h = n.h / 2, a = {fill: FILL[n.type], stroke, "stroke-width": sw}, t = n.type;
  if (t === "if") return el("polygon", {...a, points: `0,${-h} ${w},0 0,${h} ${-w},0`}, g);
  if (t === "io") return el("polygon", {...a, points: `${-w + 16},${-h} ${w},${-h} ${w - 16},${h} ${-w},${h}`}, g);
  if (t === "loop") return el("polygon", {...a, points: `${-w + 20},${-h} ${w - 20},${-h} ${w},0 ${w - 20},${h} ${-w + 20},${h} ${-w},0`}, g);
  if (t === "data") return el("path", {...a, d: `M${-w},${-h} H${w} V${h - 8} Q${w / 2},${h + 8} 0,${h - 8} T${-w},${h - 8} Z`}, g);
  if (t === "db") {
    el("path", {...a, d: `M${-w},${-h + 10} A${w},10 0 0 1 ${w},${-h + 10} V${h - 10} A${w},10 0 0 1 ${-w},${h - 10} Z`}, g);
    return el("path", {...a, fill: "none", d: `M${-w},${-h + 10} A${w},10 0 0 0 ${w},${-h + 10}`}, g);
  }
  const r = el("rect", {...a, x: -w, y: -h, width: n.w, height: n.h,
    rx: t === "start" || t === "end" ? h : t === "screen" ? 6 : 0}, g);
  if (t === "note") r.setAttribute("stroke-dasharray", "5 3");
  if (t === "call") for (const x of [-w + 10, w - 10]) el("line", {x1: x, x2: x, y1: -h, y2: h, stroke, "stroke-width": sw}, g);
  if (t === "screen") el("line", {x1: -w, x2: w, y1: -h + 12, y2: -h + 12, stroke, "stroke-width": sw}, g);
  return r;
}
function render() {
  svg.innerHTML = "";
  const g = G(); if (!g) return;
  if (!g.loaded) {  // 中身をサーバから読んでいる途中(または削除済み)
    document.getElementById("empty").style.display = "none";
    svg.setAttribute("viewBox", "-300 -150 600 300");
    const t = el("text", {"text-anchor": "middle", "font-size": 16, fill: "#6b7280", "font-family": "sans-serif"}, svg);
    t.textContent = g.missing ? "このページはサーバにありません" : "読み込み中…";
    return;
  }
  g.nodes.forEach(fit);
  document.getElementById("empty").style.display = g.nodes.length <= 1 ? "flex" : "none";
  const defs = el("defs", {}, svg);
  for (const [id, col] of [["ar", "#444"], ["as", "#2f6bd8"]]) {
    const m = el("marker", {id, viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 8, markerHeight: 8, orient: "auto-start-reverse"}, defs);
    el("path", {d: "M0,0 L10,5 L0,10 z", fill: col}, m);
  }
  svg.setAttribute("viewBox", `${view.x} ${view.y} ${view.w} ${view.h}`);
  const layer = el("g", {id: "content"}, svg);
  g.edges.forEach((e, i) => {
    const a = node(e.from), b = node(e.to); if (!a || !b) return;
    const p = edgePath(a, b), on = sel && sel.type === "edge" && sel.i === i;
    const gg = el("g", {"data-edge": i, style: "cursor:pointer"}, layer);
    const line = el("path", {d: p.d, fill: "none", stroke: on ? "#2f6bd8" : "#444", "stroke-width": on ? 2.5 : 1.5,
      "marker-end": `url(#${on ? "as" : "ar"})`}, gg);
    if (SIDE.has(a.type) || SIDE.has(b.type)) line.setAttribute("stroke-dasharray", "6 4");
    el("path", {d: p.d, fill: "none", stroke: "transparent", "stroke-width": 14}, gg);
    if (e.label) {
      const t = el("text", {x: p.lx + 6, y: p.ly - 4, "font-size": 12, fill: "#333", "font-family": "sans-serif",
        stroke: "#fbfcfe", "stroke-width": 3, "paint-order": "stroke"}, gg);
      t.textContent = e.label;
    }
    if (e.memo) { const t = el("text", {x: p.lx - 14, y: p.ly + 4, "font-size": 12}, gg); t.textContent = "📝"; }
  });
  g.nodes.forEach(n => {
    const on = (sel && sel.type === "node" && sel.id === n.id) || from === n.id;
    const gg = el("g", {"data-node": n.id, transform: `translate(${n.x},${n.y})`, style: "cursor:move"}, layer);
    shapeEl(n, gg, on ? "#2f6bd8" : "#555", on ? 3 : 1.5);
    const t = el("text", {"text-anchor": "middle", "font-size": 13, "font-family": "sans-serif", fill: "#222"}, gg);
    n.lines.forEach((l, i) => {
      const s = el("tspan", {x: 0, y: (i - (n.lines.length - 1) / 2) * 17 + 5 + (n.type === "screen" ? 6 : 0)}, t); s.textContent = l;
    });
    if (n.memo && n.type !== "note") { const m = el("text", {x: n.w / 2 - 6, y: -n.h / 2 + 6, "font-size": 13}, gg); m.textContent = "📝"; }
    const tp = targetPage(n);
    if (tp >= 0) {  // 詳細ページへ移動するバッジ
      const bd = el("g", {"data-jump": tp, transform: `translate(${-n.w / 2 + 4},${-n.h / 2 - 8})`, style: "cursor:pointer"}, gg);
      el("rect", {width: 46, height: 16, rx: 8, fill: "#2f6bd8"}, bd);
      const bt = el("text", {x: 23, y: 12, "text-anchor": "middle", "font-size": 10, fill: "#fff", "font-family": "sans-serif"}, bd);
      bt.textContent = "詳細 ↗";
    }
    if (sel && sel.type === "node" && sel.id === n.id && !drag) {  // つなぎ用ハンドル
      el("line", {x1: 0, y1: n.h / 2, x2: 0, y2: n.h / 2 + 12, stroke: "#2f6bd8", "stroke-width": 2}, gg);
      const hd = el("g", {"data-handle": n.id, transform: `translate(0,${n.h / 2 + 20})`, style: "cursor:crosshair"}, gg);
      el("circle", {r: 8, fill: "#2f6bd8", stroke: "#fff", "stroke-width": 2}, hd);
      el("path", {d: "M-3,-2 L0,3 L3,-2", fill: "none", stroke: "#fff", "stroke-width": 1.6}, hd);
    }
  });
  clearTimeout(thT); thT = setTimeout(refreshThumb, 120);
  if (linkTmp) el("line", {x1: linkTmp.x1, y1: linkTmp.y1, x2: linkTmp.x2, y2: linkTmp.y2, stroke: "#2f6bd8", "stroke-width": 2,
    "stroke-dasharray": "5 4", "pointer-events": "none"}, layer);
}
// ---- ページのサムネイル ----
function thumb(g) {
  const s = document.createElementNS(NS, "svg");
  if (!g.loaded || !g.nodes.length) return s;
  g.nodes.forEach(fit);
  const x0 = Math.min(...g.nodes.map(n => n.x - n.w / 2)) - 24, x1 = Math.max(...g.nodes.map(n => n.x + n.w / 2)) + 24;
  const y0 = Math.min(...g.nodes.map(n => n.y - n.h / 2)) - 24, y1 = Math.max(...g.nodes.map(n => n.y + n.h / 2)) + 24;
  s.setAttribute("viewBox", `${x0} ${y0} ${x1 - x0} ${y1 - y0}`);
  const sw = Math.max(x1 - x0, y1 - y0) / 50, by = Object.fromEntries(g.nodes.map(n => [n.id, n]));
  const L = el("g", {}, s);
  for (const e of g.edges) {
    const a = by[e.from], b = by[e.to]; if (!a || !b) continue;
    el("line", {x1: a.x, y1: a.y, x2: b.x, y2: b.y, stroke: "#9aa3b5", "stroke-width": sw}, L);
  }
  for (const n of g.nodes) { const gg = el("g", {transform: `translate(${n.x},${n.y})`}, L); shapeEl(n, gg, "#6b7280", sw); }
  return s;
}
function uniqueName(name, except) {
  name = (name || "").trim() || "page";
  const taken = new Set(graphs.filter((g, i) => i !== except).map(g => g.name));
  let out = name, k = 2;
  while (taken.has(out)) out = name + " " + k++;
  return out;
}
async function switchPage(i) {
  const g = graphs[i]; if (!g) return renderAll();
  cur = i; sel = null; from = null;
  if (!g.loaded) { renderAll(); await ensureLoaded(g); if (graphs[cur] !== g) return; }
  fitView(); renderAll();
}
// 呼出図形 → 詳細ページ(テキストにページ名を含むものを探す。名前の長い方を優先)
const navStack = [];
function targetPage(n) {
  if (n.type !== "call") return -1;
  let best = -1, len = 0;
  graphs.forEach((g, i) => {
    const nm = g.name.replace(/\(\)$/, "");
    if (i !== cur && nm && n.text.includes(nm) && nm.length > len) { best = i; len = nm.length; }
  });
  return best;
}
function jump(i) {
  navStack.push(G()); switchPage(i); toast("詳細ページを開きました。「← 戻る」で全体像に戻れます");
}
function back() {
  while (navStack.length) { const i = graphs.indexOf(navStack.pop()); if (i >= 0) { switchPage(i); return; } }
  toast("戻る先がありません");
}
function addPage(at) {
  snapStruct();
  const g = {pid: newPid(), name: uniqueName("page" + (graphs.length + 1), -1), rev: null, loaded: true,
    nodes: [{id: "N1", type: "start", text: "開始", memo: "", x: 0, y: 0}], edges: []};
  graphs.splice(at, 0, g); switchPage(at);
}
async function dupPage(i) {
  const src = graphs[i]; await ensureLoaded(src); if (!src.loaded) return;
  snapStruct();
  const g = {...JSON.parse(pageJson(src)), pid: newPid(), rev: null, loaded: true};
  g.name = uniqueName(src.name + " のコピー", -1);
  const at = graphs.indexOf(src) + 1;
  graphs.splice(at, 0, g); switchPage(at);
}
function movePage(i, to) {
  if (to < 0 || to >= graphs.length || to === i) return;
  const now = G();
  snapStruct(); const [g] = graphs.splice(i, 1); graphs.splice(to, 0, g); cur = graphs.indexOf(now); renderTabs();
}
async function delPage(i) {
  if (graphs.length < 2) return toast("最後のページは削除できません");
  const g = graphs[i]; await ensureLoaded(g);  // 元に戻したときに中身を復元できるよう、読み込んでから消す
  const at = graphs.indexOf(g); if (at < 0) return;
  snapStruct(); graphs.splice(at, 1); switchPage(Math.min(at, graphs.length - 1));
  toast("ページを削除しました(元に戻すで復元できます)");
}
function renamePage(i) {
  const g = graphs[i], card = cards.get(g.pid), nm = card && card.querySelector(".nm"); if (!nm) return;
  const inp = document.createElement("input"); inp.value = g.name; inp.className = "nmin";
  nm.replaceWith(inp); inp.focus(); inp.select();
  let done = false;
  const fin = async ok => {
    if (done) return; done = true;
    const v = inp.value.trim();
    if (ok && v && v !== g.name) {
      await ensureLoaded(g);  // 名前の変更もページの保存として送るので、中身が必要
      if (g.loaded) { snapshot(g); g.name = uniqueName(v, graphs.indexOf(g)); }
    }
    tabsKey = ""; renderAll();
  };
  inp.onkeydown = e => { e.stopPropagation(); if (e.key === "Enter") fin(true); if (e.key === "Escape") fin(false); };
  inp.onblur = () => fin(true);
  inp.onmousedown = e => e.stopPropagation();
}

// ---- ページ一覧(検索 + サムネイル付きカード) ----
// カードは絞り込んだ分だけ作り、サムネイルは画面に見えたカードだけ描く(見えたページの中身はそのとき読む)
const tabsEl = document.getElementById("tabs"), pq = document.getElementById("pq");
let tabsKey = "", cards = new Map(), shownPid = null;
const keyOf = q => q + "\u0002" + graphs.map(g => g.pid + "\u0001" + g.name).join("\u0002");
const thumbQ = []; let thumbBusy = 0;
const thumbObs = new IntersectionObserver(es => {
  for (const e of es) if (e.isIntersecting) { thumbObs.unobserve(e.target); queueThumb(e.target); }
}, {root: tabsEl, rootMargin: "0px 400px"});
function drawThumb(c) { const th = c.querySelector(".th"); th.innerHTML = ""; th.append(thumb(c._g)); }
function queueThumb(c) { if (c._g.loaded) return drawThumb(c); thumbQ.push(c); pumpThumbs(); }
function pumpThumbs() {
  while (thumbBusy < 4 && thumbQ.length) {
    const c = thumbQ.shift(); if (!c.isConnected) continue;
    thumbBusy++;
    ensureLoaded(c._g).then(() => { if (c.isConnected) drawThumb(c); }).finally(() => { thumbBusy--; pumpThumbs(); });
  }
}
function buildTabs(q) {
  thumbObs.disconnect(); thumbQ.length = 0; tabsEl.innerHTML = ""; cards = new Map(); shownPid = null;
  let shown = 0;
  graphs.forEach((g, i) => {
    if (q && !g.name.toLowerCase().includes(q)) return;
    shown++;
    const c = document.createElement("div"); c.className = "pg"; c.dataset.i = i; c.draggable = true; c._g = g;
    const th = document.createElement("div"); th.className = "th"; c.append(th);
    const nm = document.createElement("div"); nm.className = "nm"; nm.textContent = g.name; nm.title = g.name; c.append(nm);
    c.onclick = () => { if (i !== cur) switchPage(i); };
    c.ondblclick = () => renamePage(i);
    c.ondragstart = e => { e.dataTransfer.setData("text/x-page", String(i)); e.dataTransfer.effectAllowed = "move"; };
    c.ondragover = e => { if (e.dataTransfer.types.includes("text/x-page")) { e.preventDefault(); c.classList.add("over"); } };
    c.ondragleave = () => c.classList.remove("over");
    c.ondrop = e => { e.preventDefault(); c.classList.remove("over"); const f = e.dataTransfer.getData("text/x-page"); if (f !== "") movePage(+f, i); };
    tabsEl.append(c); cards.set(g.pid, c); thumbObs.observe(c);
  });
  if (!q) {
    const add = document.createElement("div"); add.className = "pg add"; add.innerHTML = "<b>＋</b><span>ページ追加</span>";
    add.onclick = () => addPage(graphs.length); tabsEl.append(add);
  }
  document.getElementById("pcount").textContent = q ? `${shown} / ${graphs.length} ページ` : `${graphs.length} ページ`;
}
function renderTabs() {
  const q = pq.value.trim().toLowerCase(), key = keyOf(q);
  if (key !== tabsKey) { tabsKey = key; buildTabs(q); }
  const g = G();
  for (const [pid, c] of cards) c.classList.toggle("on", !!g && pid === g.pid);
  if (g && g.pid !== shownPid) {  // 開いたページが変わったときだけ、そのカードが見える位置まで動かす
    shownPid = g.pid; const c = cards.get(g.pid); if (c) c.scrollIntoView({block: "nearest", inline: "nearest"});
  }
}
function updateCardName(g) {  // 名前の入力中は、カード全体を作り直さずに文字だけ直す
  const c = cards.get(g.pid), nm = c && c.querySelector(".nm");
  if (nm) { nm.textContent = g.name; nm.title = g.name; }
  tabsKey = keyOf(pq.value.trim().toLowerCase());
}
let pqT;
pq.addEventListener("input", () => { clearTimeout(pqT); pqT = setTimeout(renderTabs, 150); });
pq.addEventListener("keydown", e => {
  if (e.key === "Enter") { const c = tabsEl.querySelector(".pg:not(.add)"); if (c) switchPage(+c.dataset.i); }
  if (e.key === "Escape") { pq.value = ""; renderTabs(); }
});
let thT;
function refreshThumb() { const g = G(), c = g && cards.get(g.pid); if (c && g.loaded) drawThumb(c); }
tabsEl.addEventListener("contextmenu", ev => {
  ev.preventDefault();
  if (ed.style.display === "block") commitEdit();
  const c = ev.target.closest(".pg");
  if (c && !c.classList.contains("add")) {
    const i = +c.dataset.i;
    openCtx(ev, [
      {label: "名前を変更", run: () => renamePage(i)},
      {label: "複製", run: () => dupPage(i)},
      {label: "新しいページを右に追加", run: () => addPage(i + 1)},
      "-",
      {label: "左へ移動", run: () => movePage(i, i - 1)},
      {label: "右へ移動", run: () => movePage(i, i + 1)},
      "-",
      {label: "削除", danger: true, run: () => delPage(i)}]);
  } else {
    openCtx(ev, [{label: "ページを追加", run: () => addPage(graphs.length)}]);
  }
});

// ---- 左パレット(実物と同じ見た目のサンプル) ----
function renderPalette() {
  const pal = document.getElementById("pal"); pal.innerHTML = "";
  for (const [title, items] of PALETTE) {
    const h = document.createElement("h4"); h.textContent = title; pal.append(h);
    const grid = document.createElement("div"); grid.className = "grid"; pal.append(grid);
    for (const [type, name, tip] of items) {
      const d = document.createElement("div"); d.className = "item"; d.title = tip + "\nクリックで追加 / ドラッグで好きな場所へ";
      d.draggable = true;
      const s = document.createElementNS(NS, "svg"); s.setAttribute("viewBox", "-38 -22 76 44");
      const g = el("g", {}, s);
      shapeEl({type, w: type === "if" || type === "loop" ? 62 : 58, h: type === "if" ? 38 : type === "db" ? 34 : 28}, g, "#555", 1.3);
      d.append(s);
      const sp = document.createElement("span"); sp.textContent = name; d.append(sp);
      d.onclick = () => addNode(type);
      d.ondragstart = e => { e.dataTransfer.setData("text/plain", type); e.dataTransfer.effectAllowed = "copy"; };
      grid.append(d);
    }
  }
  const p = document.createElement("p");
  p.innerHTML = "<b>つなぎ方</b><br>図形を選ぶと下に <b style='color:#2f6bd8'>●</b> が出ます。そこから別の図形へドラッグ。何もない所で離すと、新しい図形ができて自動でつながります。";
  pal.append(p);
}
wrap.addEventListener("dragover", e => e.preventDefault());
wrap.addEventListener("drop", e => {
  e.preventDefault();
  const t = e.dataTransfer.getData("text/plain"); if (!DEFTXT[t]) return;
  const p = toSvg(e); addNode(t, Math.round(p.x / 10) * 10, Math.round(p.y / 10) * 10);
});

// ---- 右パネル(種別・文字・メモ) ----
function field(label, input) {
  const l = document.createElement("label"); l.textContent = label; side.append(l, input); return input;
}
function bind(input, get, set) {
  let snapped = false;
  input.value = get();
  input.addEventListener("input", () => { if (!snapped) { snapshot(); snapped = true; } set(input.value); render(); });
  input.addEventListener("blur", () => { snapped = false; });
}
function renderSide() {
  side.innerHTML = "";
  const g = G(); if (!g || !g.loaded) return;
  const mk = tag => document.createElement(tag);
  const head = t => { const h = mk("h3"); h.textContent = t; side.append(h); };
  if (sel && sel.type === "node") {
    const n = node(sel.id); if (!n) return;
    head("図形の設定");
    const s = mk("select");
    TYPES.forEach(([v, t]) => { const o = mk("option"); o.value = v; o.textContent = t; s.append(o); });
    bind(field("種別", s), () => n.type, v => { n.type = v; });
    bind(field("テキスト", mk("input")), () => n.text, v => { n.text = v.replace(/\n/g, " "); });
    bind(field("メモ(実装時の注意など。AIにも渡ります)", mk("textarea")), () => n.memo || "", v => { n.memo = v; });
    const idl = mk("label"); idl.textContent = "id: " + n.id; side.append(idl);
  } else if (sel && sel.type === "edge") {
    const e = g.edges[sel.i]; if (!e) return;
    head("矢印の設定");
    bind(field("ラベル(条件など)", mk("input")), () => e.label, v => { e.label = v; });
    bind(field("メモ", mk("textarea")), () => e.memo || "", v => { e.memo = v; });
    const idl = mk("label"); idl.textContent = e.from + " → " + e.to; side.append(idl);
  } else {
    head("ページの設定");
    const i = mk("input");
    bind(field("ページ名(関数・処理の単位)", i), () => g.name, v => { g.name = v; updateCardName(g); });
    i.addEventListener("blur", () => { g.name = uniqueName(g.name, cur); i.value = g.name; updateCardName(g); });
    const tip = mk("div"); tip.className = "tip"; tip.style.marginTop = ".8rem";
    tip.innerHTML = "・図形をクリックで設定を編集<br>・ダブルクリックで文字を直接編集<br>・背景ドラッグで画面移動、ホイールで拡大縮小<br>・Ctrl+クリック: 選択中の図形から矢印";
    side.append(tip);
    const b = mk("button"); b.textContent = "このページを削除"; b.style.marginTop = "auto";
    b.onclick = () => delPage(cur);
    side.append(b);
  }
}
function renderAll() { renderTabs(); render(); renderSide(); }
function fitView() {
  const g = G(); if (!g || !g.loaded || !g.nodes.length) return;
  g.nodes.forEach(fit);
  const x0 = Math.min(...g.nodes.map(n => n.x - n.w / 2)) - 80, x1 = Math.max(...g.nodes.map(n => n.x + n.w / 2)) + 140;
  const y0 = Math.min(...g.nodes.map(n => n.y - n.h / 2)) - 70, y1 = Math.max(...g.nodes.map(n => n.y + n.h / 2)) + 60;
  if (!wrap.clientWidth || !wrap.clientHeight) return;
  const r = wrap.clientWidth / wrap.clientHeight;
  let w = x1 - x0, h = y1 - y0;
  if (w / h < r) w = h * r; else h = w / r;
  view = {x: (x0 + x1) / 2 - w / 2, y: y0, w, h};
}
function toSvg(ev) {
  const pt = svg.createSVGPoint(); pt.x = ev.clientX; pt.y = ev.clientY;
  return pt.matrixTransform(svg.getScreenCTM().inverse());
}
function select(s) { sel = s; render(); renderSide(); }
function zoom(f, cx, cy) {
  cx = cx ?? view.x + view.w / 2; cy = cy ?? view.y + view.h / 2;
  view = {x: cx - (cx - view.x) * f, y: cy - (cy - view.y) * f, w: view.w * f, h: view.h * f};
  svg.setAttribute("viewBox", `${view.x} ${view.y} ${view.w} ${view.h}`);
}

// ---- 操作 ----
let drag = null;
svg.addEventListener("mousedown", ev => {
  if (ev.button !== 0) return;
  if (ed.style.display === "block") commitEdit();
  const jp = ev.target.closest("[data-jump]");
  if (jp) { jump(+jp.dataset.jump); return; }
  const hd = ev.target.closest("[data-handle]");
  if (hd) {
    const n = node(hd.dataset.handle), p = toSvg(ev);
    drag = {kind: "link", id: n.id, moved: false};
    linkTmp = {x1: n.x, y1: n.y + n.h / 2, x2: p.x, y2: p.y}; render(); return;
  }
  const ng = ev.target.closest("[data-node]"), eg = ev.target.closest("[data-edge]");
  if (ng) {
    const id = ng.dataset.node;
    if (mode === "connect" || ev.ctrlKey) {
      const start = mode === "connect" ? from : (sel && sel.type === "node" ? sel.id : null);
      if (start && start !== id) {
        snapshot(); G().edges.push({from: start, to: id, label: "", memo: ""}); from = null;
        select({type: "edge", i: G().edges.length - 1});
      } else { from = id; render(); }
      return;
    }
    const p = toSvg(ev), n = node(id);
    drag = {kind: "node", id, dx: p.x - n.x, dy: p.y - n.y, moved: false};
    select({type: "node", id});
  } else if (eg) {
    select({type: "edge", i: +eg.dataset.edge});
  } else {
    from = null; drag = {kind: "pan", sx: ev.clientX, sy: ev.clientY, vx: view.x, vy: view.y};
    select(null);
  }
});
window.addEventListener("mousemove", ev => {
  if (!drag) return;
  if (drag.kind === "link") {
    const p = toSvg(ev); linkTmp.x2 = p.x; linkTmp.y2 = p.y; drag.moved = true; render();
  } else if (drag.kind === "node") {
    if (!drag.moved) { snapshot(); drag.moved = true; }
    const p = toSvg(ev), n = node(drag.id);
    n.x = Math.round((p.x - drag.dx) / 10) * 10; n.y = Math.round((p.y - drag.dy) / 10) * 10; render();
  } else {
    const k = view.w / svg.clientWidth;
    view.x = drag.vx - (ev.clientX - drag.sx) * k; view.y = drag.vy - (ev.clientY - drag.sy) * k;
    svg.setAttribute("viewBox", `${view.x} ${view.y} ${view.w} ${view.h}`);
  }
});
window.addEventListener("mouseup", ev => {
  const d = drag; drag = null;
  if (d && d.kind === "link") {
    linkTmp = null;
    const under = document.elementFromPoint(ev.clientX, ev.clientY), tg = under && under.closest("[data-node]");
    if (d.moved && tg && tg.dataset.node !== d.id) {
      snapshot(); G().edges.push({from: d.id, to: tg.dataset.node, label: "", memo: ""});
      select({type: "edge", i: G().edges.length - 1});
    } else if (d.moved && under && wrap.contains(under) && !tg) {  // 何もない所で離す → 新しい処理を作ってつなぐ
      const p = toSvg(ev), n = {id: nextId(), type: "proc", text: "処理", memo: "", x: Math.round(p.x / 10) * 10, y: Math.round(p.y / 10) * 10};
      snapshot(); G().nodes.push(n); G().edges.push({from: d.id, to: n.id, label: "", memo: ""});
      select({type: "node", id: n.id});
    } else render();
  } else if (d) render();
});
svg.addEventListener("wheel", ev => {
  ev.preventDefault();
  const p = toSvg(ev); zoom(ev.deltaY > 0 ? 1.12 : 1 / 1.12, p.x, p.y);
}, {passive: false});

// ---- 文字編集(ダブルクリック) ----
let editing = null;
svg.addEventListener("dblclick", ev => {
  const ng = ev.target.closest("[data-node]"), eg = ev.target.closest("[data-edge]");
  if (ng) startEdit({type: "node", id: ng.dataset.node}, ng.getBoundingClientRect());
  else if (eg) startEdit({type: "edge", i: +eg.dataset.edge}, {left: ev.clientX - 60, top: ev.clientY - 14, width: 120, height: 28});
});
function startEdit(target, r) {
  const wr = wrap.getBoundingClientRect();
  editing = target;
  ed.value = target.type === "node" ? node(target.id).text : G().edges[target.i].label;
  ed.style.cssText = `display:block;left:${r.left - wr.left}px;top:${r.top - wr.top}px;width:${Math.max(r.width, 120)}px;height:${Math.max(r.height, 30)}px`;
  ed.focus(); ed.select();
}
function commitEdit() {
  if (!editing) return;
  const v = ed.value.replace(/\n/g, " ").trim(), t = editing;
  editing = null; ed.style.display = "none";
  snapshot();
  if (t.type === "node") node(t.id).text = v; else G().edges[t.i].label = v;
  render(); renderSide();
}
ed.addEventListener("keydown", ev => {
  if (ev.key === "Enter") { ev.preventDefault(); commitEdit(); }
  if (ev.key === "Escape") { editing = null; ed.style.display = "none"; }
});
ed.addEventListener("blur", () => { if (editing) commitEdit(); });

// ---- 追加・削除・ツール ----
function nextId() {
  let m = 0;
  for (const n of G().nodes) { const k = /^N(\d+)$/.exec(n.id); if (k) m = Math.max(m, +k[1]); }
  return "N" + (m + 1);
}
function addNode(type, x, y) {
  if (!G() || !G().loaded) return;
  snapshot();
  const n = {id: nextId(), type, text: DEFTXT[type], memo: "",
    x: x ?? Math.round((view.x + view.w / 2) / 10) * 10, y: y ?? Math.round((view.y + view.h / 2) / 10) * 10};
  G().nodes.push(n); select({type: "node", id: n.id});
}
function del() {
  if (!sel) return; snapshot();
  if (sel.type === "node") { G().nodes = G().nodes.filter(n => n.id !== sel.id); G().edges = G().edges.filter(e => e.from !== sel.id && e.to !== sel.id); }
  else G().edges.splice(sel.i, 1);
  select(null);
}
function setMode(m) {
  mode = m; from = null;
  document.getElementById("tsel").classList.toggle("on", !m);
  document.getElementById("conn").classList.toggle("on", !!m); render();
}
document.getElementById("del").onclick = del;
document.getElementById("undo").onclick = undo;
document.getElementById("back").onclick = back;
document.getElementById("fit").onclick = () => { fitView(); render(); };
document.getElementById("zin").onclick = () => zoom(1 / 1.25);
document.getElementById("zout").onclick = () => zoom(1.25);
document.getElementById("tsel").onclick = () => setMode(null);
document.getElementById("conn").onclick = () => setMode(mode ? null : "connect");
window.addEventListener("keydown", ev => {
  const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(ev.target.tagName);
  if (ev.ctrlKey && ev.key.toLowerCase() === "s") { ev.preventDefault(); doSave(false); return; }
  if (typing) return;
  if (ev.key === "Delete" || ev.key === "Backspace") del();
  if (ev.key === "Escape") setMode(null);
  if (ev.ctrlKey && ev.key.toLowerCase() === "z") { ev.preventDefault(); undo(); }
});

// ---- 右クリックメニュー ----
const ctx = document.getElementById("ctx");
function closeCtx() { ctx.style.display = "none"; }
function buildMenu(parent, items, flip) {
  for (const it of items) {
    if (it === "-") { parent.append(document.createElement("hr")); continue; }
    if (it.head) { const h = document.createElement("div"); h.className = "hd"; h.textContent = it.head; parent.append(h); continue; }
    const d = document.createElement("div"); d.className = "mi" + (it.danger ? " danger" : "");
    const l = document.createElement("span"); l.textContent = it.label; d.append(l);
    if (it.sub) {
      const a = document.createElement("span"); a.textContent = "▸"; d.append(a);
      const s = document.createElement("div"); s.className = "sub" + (flip ? " flip" : ""); buildMenu(s, it.sub, flip); d.append(s);
      d.addEventListener("mouseenter", () => {
        s.style.display = "block"; s.style.top = "";
        const over = s.getBoundingClientRect().bottom - innerHeight + 8;
        if (over > 0) s.style.top = `calc(-.35rem - ${over}px)`;
      });
      d.addEventListener("mouseleave", () => { s.style.display = ""; });
    } else d.onclick = e => { e.stopPropagation(); closeCtx(); it.run(); };
    parent.append(d);
  }
}
function openCtx(ev, items) {
  ctx.innerHTML = ""; ctx.style.display = "block";
  const flip = ev.clientX > innerWidth - 420;
  buildMenu(ctx, items, flip);
  const r = ctx.getBoundingClientRect();
  ctx.style.left = Math.max(4, Math.min(ev.clientX, innerWidth - r.width - 4)) + "px";
  ctx.style.top = Math.max(4, Math.min(ev.clientY, innerHeight - r.height - 4)) + "px";
}
function focusMemo() { const t = side.querySelector("textarea"); if (t) { t.focus(); } }
svg.addEventListener("contextmenu", ev => {
  ev.preventDefault();
  if (ed.style.display === "block") commitEdit();
  const ng = ev.target.closest("[data-node]"), eg = ev.target.closest("[data-edge]");
  if (ng) {
    const id = ng.dataset.node, n = node(id); select({type: "node", id});
    const tp = targetPage(n);
    openCtx(ev, [
      ...(tp >= 0 ? [{label: "詳細ページを開く: " + graphs[tp].name, run: () => jump(tp)}, "-"] : []),
      {label: "文字を編集", run: () => startEdit({type: "node", id}, svg.querySelector(`[data-node="${id}"]`).getBoundingClientRect())},
      {label: "メモを編集", run: focusMemo},
      {label: "種別を変更", sub: TYPES.map(([v, t]) => ({label: (v === n.type ? "✓ " : "") + t,
        run: () => { snapshot(); n.type = v; renderAll(); }}))},
      "-",
      {label: "ここから矢印を引く", run: () => { setMode("connect"); from = id; render(); toast("つなぎたい図形をクリックしてください"); }},
      {label: "複製", run: () => {
        snapshot(); const c = {...n, id: nextId(), x: n.x + 30, y: n.y + 30}; delete c.lines; delete c.w; delete c.h;
        G().nodes.push(c); select({type: "node", id: c.id}); }},
      "-",
      {label: "削除", danger: true, run: del}]);
  } else if (eg) {
    const i = +eg.dataset.edge, e = G().edges[i]; select({type: "edge", i});
    openCtx(ev, [
      {label: "ラベルを編集", run: () => startEdit({type: "edge", i}, {left: ev.clientX - 60, top: ev.clientY - 14, width: 120, height: 28})},
      {label: "メモを編集", run: focusMemo},
      {label: "向きを反転", run: () => { snapshot(); [e.from, e.to] = [e.to, e.from]; renderAll(); }},
      "-",
      {label: "削除", danger: true, run: del}]);
  } else {
    select(null);
    const p = toSvg(ev), x = Math.round(p.x / 10) * 10, y = Math.round(p.y / 10) * 10;
    openCtx(ev, [
      {label: "図形をここに追加", sub: TYPES.map(([v, t]) => ({label: t, run: () => addNode(v, x, y)}))},
      "-",
      {label: "全体表示", run: () => { fitView(); render(); }},
      {label: "元に戻す", run: undo}]);
  }
});
window.addEventListener("mousedown", e => { if (!ctx.contains(e.target)) closeCtx(); });
window.addEventListener("keydown", e => { if (e.key === "Escape") closeCtx(); });
wrap.addEventListener("wheel", closeCtx, {passive: true});

// ---- 保存 ----
// 最後に保存した状態と比べて、変わったページ(put)・消したページ(del)・並び順が変わったページ(move)だけを送る
function buildOps() {
  const ops = [], sent = [], here = new Set(graphs.map(g => g.pid));
  for (const pid of savedOrder) if (!here.has(pid)) ops.push({op: "del", pid, rev: savedRev.get(pid)});
  const before = new Map(savedOrder.map((p, k) => [p, k ? savedOrder[k - 1] : null]));
  let prev = null;
  for (const g of graphs) {
    if (!savedRev.has(g.pid)) {  // 新しいページ(または、保存済みの削除を元に戻したページ)
      const j = pageJson(g); ops.push({op: "put", pid: g.pid, rev: null, after: prev, ...JSON.parse(j)}); sent.push([g.pid, j]);
    } else {
      if (g.loaded) {
        const j = pageJson(g);
        if (j !== saved.get(g.pid)) { ops.push({op: "put", pid: g.pid, rev: savedRev.get(g.pid), ...JSON.parse(j)}); sent.push([g.pid, j]); }
      }
      if (before.get(g.pid) !== prev) ops.push({op: "move", pid: g.pid, after: prev});
    }
    prev = g.pid;
  }
  return {ops, sent};
}
function showIssues(list, head) {
  issuesEl.innerHTML = "";
  const h = document.createElement("div"); h.className = list.some(i => i.level === "error") ? "error" : "ok"; h.textContent = head;
  issuesEl.append(h);
  for (const i of list) {
    const d = document.createElement("div"); d.className = i.level;
    d.textContent = (i.level === "error" ? "✖ " : "▲ ") + i.page + (i.node ? " / " + i.node : "") + ": " + i.msg;
    d.onclick = async () => {
      const gi = graphs.findIndex(g => g.name === i.page); if (gi < 0) return;
      await switchPage(gi); select(i.node ? {type: "node", id: i.node} : null);
    };
    issuesEl.append(d);
  }
}
function showChanges(changes) {
  if (!changes || !changes.length) return;
  const h = document.createElement("div"); h.style.cssText = "margin-top:.3rem;font-weight:600;cursor:default"; h.textContent = "今回の変更点(";
  const a = document.createElement("a"); a.href = BASE + "/log"; a.target = "_blank"; a.textContent = "変更履歴";
  h.append(a, "にも記録)");
  issuesEl.append(h);
  for (const c of changes) {
    const d = document.createElement("div"); d.style.cursor = "default";
    d.className = c[0] === "+" ? "ok" : c[0] === "-" ? "error" : "warn"; d.textContent = c; issuesEl.append(d);
  }
}
function saveFailed(why, conflict) {
  dirty = true;  // 未保存のまま。画面を閉じるときの警告も残す
  const dl = document.getElementById("dirty"); dl.textContent = "✖ 保存できません"; dl.style.color = "#c0242d";
  issuesEl.innerHTML = "";
  const d = document.createElement("div"); d.className = "error";
  clearTimeout(asT);
  if (conflict) {  // 再試行しても直らない。新しい内容を読み直してもらう(この画面の編集で上書きしない)
    d.textContent = "✖ 保存できません(" + why + ")。ページを再読み込みすると最新の内容が開きます。この画面の編集は反映されません。";
    return issuesEl.append(d);
  }
  d.textContent = "✖ 保存に失敗しました(" + why + ")。編集内容はこの画面に残っています。サーバが復帰すると自動で保存を再試行します。";
  issuesEl.append(d);
  if (autoOn) asT = setTimeout(() => doSave(true), 5000);
}
// 保存は1つずつ順番に行う(自動保存とCtrl+Sが重なると、古い版番号で送って衝突扱いになるため)
let saveChain = Promise.resolve();
function doSave(auto) { return saveChain = saveChain.then(() => saveNow(auto)); }
async function saveNow(auto) {
  const {ops, sent} = buildOps(), order = graphs.map(g => g.pid), seq = editSeq;
  const now = () => new Date().toTimeString().slice(0, 5);
  if (!ops.length && auto) return setDirty(false, "✓ " + now() + " 自動保存");
  let res;
  try {
    // 手動保存(Ctrl+S・保存ボタン)のときは、全ページを検査してもらう
    res = await (await fetch(BASE + "/save", {method: "POST", body: JSON.stringify({ops, check_all: !auto})})).json();
  } catch (e) { return saveFailed("サーバに接続できません"); }
  if (res.error) return saveFailed(res.error, res.conflict);
  for (const o of ops) if (o.op === "del") { saved.delete(o.pid); savedRev.delete(o.pid); }
  const byPid = new Map(graphs.map(g => [g.pid, g]));
  for (const [pid, j] of sent) {
    saved.set(pid, j); savedRev.set(pid, res.revs[pid]);
    const g = byPid.get(pid); if (g) g.rev = res.revs[pid];
  }
  savedOrder = order;
  if (editSeq !== seq) setDirty(true);  // 保存中にさらに編集された。続けて保存する
  else setDirty(false, "✓ " + now() + (auto ? " 自動保存" : " 保存"));
  if (auto) return;
  const errs = res.issues.filter(i => i.level === "error").length;
  showIssues(res.issues, errs ? `エラー${errs}件あります(保存はしました)。AIが読む前に直してください`
    : res.issues.length ? `注意${res.issues.length}件` : "問題は見つかりませんでした");
  showChanges(res.changes);
  toast(errs ? "保存しました(エラーあり)" : "保存しました");
}
document.getElementById("save").onclick = () => doSave(false);

// ---- 書き出し(.fc / SVG) ----
function download(name, text, type) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], {type})); a.download = name; a.click();
}
document.getElementById("sfc").onclick = async () => { if (dirty) await doSave(true); location.href = BASE + "/download.fc"; };
document.getElementById("ssvg").onclick = () => {
  const g = G(); if (!g) return;
  const sv = {...view}, ss = sel; sel = null; fitView(); render();
  const c = svg.cloneNode(true); view = sv; sel = ss; render();
  const vb = c.viewBox.baseVal;
  c.setAttribute("width", 1000); c.setAttribute("height", Math.round(1000 * vb.height / vb.width));
  const bg = document.createElementNS(NS, "rect");
  for (const [k, v] of Object.entries({x: vb.x, y: vb.y, width: vb.width, height: vb.height, fill: "#fff"})) bg.setAttribute(k, v);
  c.insertBefore(bg, c.querySelector("#content"));
  download(g.name.replace(/[^\w.-]/g, "_") + ".svg", new XMLSerializer().serializeToString(c), "image/svg+xml");
};

const autoBox = document.getElementById("auto");
autoBox.checked = autoOn;
autoBox.onchange = () => {
  autoOn = autoBox.checked;
  fetch(BASE + "/settings", {method: "POST", body: JSON.stringify({autosave: autoOn})})
    .then(r => r.json()).then(r => { if (r.error) throw r.error; })
    .catch(() => toast("設定をファイルに保存できませんでした(この画面では切り替わっています)"));
  clearTimeout(asT);
  if (dirty) { if (autoOn) doSave(true); else setDirty(true); }  // オンにした時点で未保存があれば保存する
  toast(autoOn ? "自動保存をオンにしました" : "自動保存をオフにしました。保存は「保存」ボタン(Ctrl+S)で行います");
};
window.addEventListener("resize", () => { fitView(); render(); });
renderPalette(); fitView(); renderAll();
