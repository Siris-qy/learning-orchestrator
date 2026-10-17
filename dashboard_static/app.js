/* Learning Orchestrator dashboard. No framework, no CDN. */
"use strict";

const EDGE_TYPES = ["part_of", "sequence", "prerequisite", "explains",
  "contrasts_with", "tested_by", "fails_as"];
// part_of is not a filterable edge: containment is drawn as boxes/columns.
const FILTERABLE_EDGES = EDGE_TYPES.filter(t => t !== "part_of");
const DEFAULT_EDGES = new Set(["sequence"]);
// Chinese label plus an explicit reading of the arrow direction, so the
// graph legend explains itself: "顺序 · 先学 → 后学" etc.
const EDGE_META = {
  part_of:        { label: "包含", desc: "子节点 → 父节点" },
  sequence:       { label: "顺序", desc: "先学 → 后学" },
  prerequisite:   { label: "前置", desc: "先修 → 依赖它的一方" },
  explains:       { label: "解释", desc: "解释方 → 被解释方" },
  contrasts_with: { label: "对比", desc: "指向对比对象" },
  tested_by:      { label: "检验", desc: "知识点 → 考察它的测试" },
  fails_as:       { label: "异常", desc: "正常路径 → 失败形态" },
};
const TYPE_LABEL = { course: "课程", module: "模块", unit: "章节",
  objective: "知识目标", source: "材料", diagnostic: "诊断" };
const STATUS_COLOR = {
  untouched: "#aeb7c3", in_progress: "#e6a23c",
  struggling: "#d95d56", demonstrated: "#29946d", none: "#7697d8",
};
const STATUS_LABEL = {
  untouched: "未验证", in_progress: "部分通过",
  struggling: "薄弱", demonstrated: "已掌握",
};
const MODE_LABEL = {intro: "首次学习", clarify: "重点澄清", review: "复习"};

let courseId = null;
let courseMetadata = {};
let statuses = {};
let graphData = null;
let selectedNodeId = null;
let suggestedNodeId = null;
let activeEdgeTypes = new Set(DEFAULT_EDGES);
let teachingState = null;
let claimsByNode = {};
let routeView = "tree";
let routeViewUserChosen = false;
// Module second-level page (总览 → 模块页): hash &module=<id>, browsing only,
// never writes cursor/progress. learningTreeData caches the last tree payload
// so entering/leaving a module page re-renders without a network round-trip.
let moduleId = null;
let learningTreeData = null;
let teachingTreeData = null;
// 三个常用入口：学习树 / 知识(目录·关系图) / 项目理解(代码结构·请求主链)。
// 子视图状态与深链恢复；旧图谱渲染整体迁入「知识 → 关系图」。
let kView = "catalog";
let pView = "map";
let knowledgeData = null;
let codeMapData = null;
let selectedKnowledgeId = null;
let knowledgeRequestVersion = 0;
let selectedCompId = null;
// 复习座舱（R1）：基础八股按专题分组 + 项目模块通路 + 题目三档判断。
// cockpitSel 记住详情区正在看的点/模块/题，判断提交后原地重显。
let cockpitData = null;
let cockpitSel = null;
let pendingCockpitSel = null;  // 深链 cp= 在数据加载前先记下，refresh 后落位

function applySubViews() {
  document.querySelectorAll(".k-view-tab").forEach(t =>
    t.classList.toggle("active", t.dataset.view === kView));
  document.querySelectorAll(".p-view-tab").forEach(t =>
    t.classList.toggle("active", t.dataset.view === pView));
  const kc = document.getElementById("knowledge-catalog");
  const gp = document.getElementById("graph-pane");
  if (kc) kc.style.display = kView === "catalog" ? "" : "none";
  if (gp) gp.style.display = kView === "graph" ? "" : "none";
  const cm = document.getElementById("code-map");
  const rc = document.getElementById("request-chain");
  const cn = document.querySelector(".chain-note");
  if (cm) cm.style.display = pView === "map" ? "" : "none";
  if (rc) rc.style.display = pView === "chain" ? "" : "none";
  if (cn) cn.style.display = pView === "chain" ? "" : "none";
}
let refreshVersion = 0;
let detailVersion = 0;
let detailSignature = null;
// Advanced graph viewport state. Kept across the 15s auto-refresh and across
// course switches (per course), so panning/zooming is never yanked away.
let graphView = null;
const graphViewsByCourse = {};
let graphLayoutCache = null;
let graphRenderKey = null;
// Units whose objective list is expanded in the advanced graph, per course.
// The teaching unit is always expanded on top of this (derived, not stored).
const expandedUnitsByCourse = {};

const CLAIM_LABEL = {
  implemented_and_wired: "已接入主链",
  implemented_not_wired: "已实现·未接入",
  interface_or_example: "仅接口/示例",
  planned_upgrade: "候选升级",
  needs_verification: "待核实",
};

async function api(path) {
  const response = await fetch(path, {cache: "no-store"});
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

async function init() {
  const courses = await api("/api/courses");
  if (!courses.length) {
    const main = document.querySelector('main');
    const title = document.createElement('h1'); title.textContent = '工作区已就绪';
    const intro = document.createElement('p'); intro.textContent = '这里尚未建立课程学习计划。已登记的项目、知识与复盘可以从上方入口打开。';
    main.replaceChildren(title, intro);
    return;
  }
  const select = document.getElementById("course-select");
  for (const course of courses) {
    courseMetadata[course.id] = course;
    const option = document.createElement("option");
    option.value = course.id;
    option.textContent = course.display_title || course.title;
    select.appendChild(option);
  }
  // Deep links: #course=…&node=…&graph=open make a view shareable and let the
  // smoke screenshots reach any state without scripting clicks. Read the hash
  // BEFORE the first refresh: refresh auto-opens the teaching node, which
  // rewrites the hash.
  const initialHash = new URLSearchParams(location.hash.slice(1));
  const hashCourse = initialHash.get("course");
  if (hashCourse && courses.some(c => c.id === hashCourse)) {
    select.value = hashCourse;
  }
  if (courses.length) courseId = select.value || courses[0].id;
  moduleId = initialHash.get("module");
  select.onchange = () => {
    knowledgeRequestVersion++;
    courseId = select.value;
    selectedNodeId = null;
    moduleId = null;
    selectedKnowledgeId = null;
    selectedCompId = null;
    cockpitSel = null;
    detailVersion++;
    detailSignature = null;
    routeViewUserChosen = false;
    updateLocationHash();
    document.getElementById("detail").textContent = "正在读取当前课程…";
    refresh().catch(showSyncError);
  };
  buildEdgeFilters();
  buildGraphControls();
  document.querySelectorAll(".route-view-tab").forEach(tab => {
    tab.onclick = () => {
      knowledgeRequestVersion++;
      routeView = tab.dataset.view;
      routeViewUserChosen = true;
      updateLocationHash();
      applyRouteView();
    };
  });
  document.querySelectorAll(".k-view-tab").forEach(tab => {
    tab.onclick = () => { kView = tab.dataset.view; updateLocationHash(); applySubViews(); };
  });
  document.querySelectorAll(".p-view-tab").forEach(tab => {
    tab.onclick = () => { pView = tab.dataset.view; updateLocationHash(); applySubViews(); };
  });
  document.getElementById("continue-button").onclick = () => {
    if (!suggestedNodeId) return;
    showNode(suggestedNodeId);
    document.getElementById("detail").scrollIntoView({behavior: "smooth", block: "start"});
  };
  await refresh();
  applyLocationHash(initialHash);
  api("/api/meta").then(meta => {
    const el = document.getElementById("db-meta");
    if (!meta?.db_path || !el) return;
    el.hidden = false;
    el.textContent = "数据库 " + meta.db_path;
    el.title = "当前页面服务正在读取的 SQLite 文件；与预期不符说明连到了旧进程或其他库";
  }).catch(() => {});  // older servers without /api/meta: stay silent
  setInterval(() => { if (!document.hidden) refresh().catch(showSyncError); }, 15000);
}

function applyLocationHash(params) {
  knowledgeRequestVersion++;
  const focus = params.get("graphat");
  const view = params.get("view");
  if (view && ["tree", "knowledge", "project", "cockpit"].includes(view)) {
    routeView = view; routeViewUserChosen = true;
  }
  if (params.get("kview")) kView = params.get("kview");
  if (params.get("pview")) pView = params.get("pview");
  if (params.get("code") === "open") { routeView = "project"; routeViewUserChosen = true; }
  if (params.get("graph") === "open" || focus) {
    routeView = "knowledge"; kView = "graph"; routeViewUserChosen = true;
  }
  applyRouteView();
  if (focus && graphLayoutCache?.positions[focus]) centerGraphOn(focus);
  const node = params.get("node");
  if (node && graphData?.nodes.some(n => n.id === node)) showNode(node);
  // 深链里显式 view 优先；comp/know 只决定详情内容，不反过来夺视图
  const comp = params.get("comp");
  if (comp && codeMapData?.components?.some(c => c.id === comp)) showCodeModule(comp, !view);
  const know = params.get("know");
  if (know) showKnowledge(know, !view);
  const cp = params.get("cp");
  if (cp) pendingCockpitSel = cp;
}

function updateLocationHash() {
  const params = new URLSearchParams();
  if (courseId) params.set("course", courseId);
  if (selectedNodeId) params.set("node", selectedNodeId);
  if (moduleId) params.set("module", moduleId);
  if (routeView !== "tree") params.set("view", routeView);
  if (routeView === "knowledge" && kView !== "catalog") params.set("kview", kView);
  if (routeView === "project" && pView !== "map") params.set("pview", pView);
  if (selectedCompId) params.set("comp", selectedCompId);
  if (selectedKnowledgeId) params.set("know", selectedKnowledgeId);
  if (routeView === "cockpit" && cockpitSel) params.set("cp", cockpitSel.id);
  history.replaceState(null, "", "#" + params.toString());
  syncLibraryEntry();
}

function syncLibraryEntry() {
  const link = document.querySelector('.library-entry');
  if (!link || !courseId) return;
  const view = courseMetadata[courseId]?.library_view_key || 'course:' + courseId;
  link.href = '/library.html?return=' + encodeURIComponent('/' + location.hash)
    + '#' + new URLSearchParams({view, path:'[]'});
  try {localStorage.setItem('lo.learning:' + courseId, location.hash);localStorage.setItem('lo.last-course', courseId);} catch {}
}

function applyRouteView() {
  document.querySelectorAll(".route-view-tab").forEach(t =>
    t.classList.toggle("active", t.dataset.view === routeView));
  const on = Boolean(moduleId);
  document.body.classList.toggle("module-mode", on);
  const tabs = document.querySelector(".route-views:not(.sub-views)");
  if (tabs) tabs.style.display = on ? "none" : "";
  const heading = document.querySelector(".path-panel .section-heading h2");
  if (heading) heading.textContent = on ? "模块页" : "从这里继续";
  const kv = document.getElementById("knowledge-view");
  const pv = document.getElementById("project-view");
  const cv = document.getElementById("cockpit-view");
  if (kv) kv.style.display = !on && routeView === "knowledge" ? "" : "none";
  if (pv) pv.style.display = !on && routeView === "project" ? "" : "none";
  if (cv) cv.style.display = !on && routeView === "cockpit" ? "" : "none";
  const lt = document.getElementById("learning-tree");
  if (lt) lt.style.display = on || routeView === "tree" ? "" : "none";
  const tn = document.querySelector(".tree-note");
  if (tn) tn.style.display = on || routeView === "tree" ? "" : "none";
  applySubViews();
}

function openModule(id) {
  knowledgeRequestVersion++;
  moduleId = id;
  updateLocationHash();
  applyRouteView();
  renderGlobalTree(learningTreeData);
}

function closeModule() {
  moduleId = null;
  updateLocationHash();
  applyRouteView();
  renderGlobalTree(learningTreeData);
}

async function refresh() {
  if (!courseId) return;
  const version = ++refreshVersion;
  const requestedCourse = courseId;
  const [dashboard, graph, sessions, next, teaching, claims, review, teachingTree, ltree, codeStructure, knowledge, codeMap, cockpit] = await Promise.all([
    api("/api/dashboard?course_id=" + encodeURIComponent(courseId)),
    api("/api/graph?course_id=" + encodeURIComponent(courseId)),
    api("/api/sessions?course_id=" + encodeURIComponent(courseId)),
    api("/api/next?course_id=" + encodeURIComponent(courseId)),
    api("/api/teaching?course_id=" + encodeURIComponent(courseId)),
    api("/api/claims?course_id=" + encodeURIComponent(courseId)),
    api("/api/review?course_id=" + encodeURIComponent(courseId)),
    api("/api/teaching_tree?course_id=" + encodeURIComponent(courseId)),
    api("/api/learning_tree?course_id=" + encodeURIComponent(courseId)),
    api("/api/code_structure?course_id=" + encodeURIComponent(courseId)),
    api("/api/knowledge?course_id=" + encodeURIComponent(courseId)),
    api("/api/code_map?course_id=" + encodeURIComponent(courseId)),
    api("/api/cockpit?course_id=" + encodeURIComponent(courseId))
      .catch(() => ({unavailable: true})),  // 旧版服务无此接口：只缺座舱，不拖垮整页
  ]);
  if (version !== refreshVersion || requestedCourse !== courseId) return;
  statuses = dashboard.node_statuses || {};
  graphData = graph;
  teachingState = teaching;
  learningTreeData = ltree;
  teachingTreeData = teachingTree;
  knowledgeData = knowledge;
  cockpitData = cockpit;
  codeMapData = codeMap && (codeMap.components || []).length ? codeMap : null;
  claimsByNode = {};
  for (const claim of claims) {
    const key = claim.node_id || "(course)";
    (claimsByNode[key] ||= []).push(claim);
  }
  suggestedNodeId = teaching.workspace?.section_id || dashboard.active_session?.current_node?.id || next?.node_id || firstObjective(graph);
  if (!routeViewUserChosen) routeView = "tree";
  applyRouteView();
  renderHero(dashboard, graph, next);
  syncLibraryEntry();
  renderStats(dashboard);
  renderRecordSummary(dashboard);
  renderRequestChain(graph);
  renderStudyFocus(teaching, teachingTree);
  renderGlobalTree(ltree);
  renderKnowledge(knowledge);
  renderCockpit(cockpit);
  if (pendingCockpitSel) {
    const cpId = pendingCockpitSel; pendingCockpitSel = null;
    if (cpId.startsWith("project:")) showCockpitModule(cpId);
    else if (cpId.startsWith("review:")) showCockpitPoint(cpId);
  }
  renderCodeMap(codeMapData);
  renderCodeStructure(codeStructure);
  renderReview(review);
  renderSessions(sessions);
  drawGraph(graph);

  const button = document.getElementById("continue-button");
  button.disabled = !suggestedNodeId;
  // 刷新只恢复详情内容，不改变用户手动选过的入口视图（15s 自动刷新
  // 不得把页面拽回知识/项目页）
  if (selectedKnowledgeId) await showKnowledge(selectedKnowledgeId, false);
  else if (selectedCompId) showCodeModule(selectedCompId, false);
  else {
    const detailId = selectedNodeId || suggestedNodeId;
    if (detailId) await showNode(detailId);
  }
  if (version === refreshVersion) setText("sync-message", `当前课程记录 · 更新于 ${new Date().toLocaleTimeString("zh-CN", {hour12: false})} · 每 15 秒刷新`);
}

function showSyncError(error) {
  setText("sync-message", `读取未完成：${error.message}。显示内容可能是上次记录。`);
}

function renderReview(review) {
  const panel = document.getElementById('review-panel');
  const list = document.getElementById('review-list');
  list.replaceChildren();
  const ov = review && review.overview, today = review && review.today;
  if (!ov || !ov.total) { panel.hidden = true; return; }
  panel.hidden = false;
  const parts = [`到期 ${ov.due_today}`, `未知 ${ov.unknown}`, `循环中 ${ov.active}`];
  if (ov.weak_candidates) parts.push(`薄弱候选 ${ov.weak_candidates}`);
  parts.push(`每日上限 ${ov.daily_cap}`);
  document.getElementById('review-summary').textContent = parts.join(' · ');
  if (!today.items.length) {
    const p = document.createElement('p'); p.className = 'focus-empty';
    p.textContent = '今日没有到期项，也没有待首次复述的知识点。';
    list.append(p); return;
  }
  for (const it of today.items) {
    const row = document.createElement('div'); row.className = 'review-item';
    const id = document.createElement('span'); id.className = 'review-point';
    id.textContent = it.point_id;
    const name = document.createElement('span'); name.className = 'review-title';
    name.textContent = it.title;
    row.append(id, name);
    if (it.weak_candidate) {
      const w = document.createElement('span'); w.className = 'review-badge weak';
      w.textContent = '薄弱候选'; row.append(w);
    }
    const badge = document.createElement('span');
    if (it.kind === 'due') {
      badge.className = 'review-badge due';
      badge.textContent = it.overdue_days > 0 ? `逾期 ${it.overdue_days} 天` : '今日到期';
    } else {
      badge.className = 'review-badge new';
      badge.textContent = '待首次复述';
    }
    row.append(badge); list.append(row);
  }
  if (today.due_total > today.items.length) {
    const more = document.createElement('p'); more.className = 'muted';
    more.textContent = `另有 ${today.due_total - today.items.filter(i => i.kind === 'due').length} 个到期项超出今日上限，顺延展示。`;
    list.append(more);
  }
}

// ---------- 复习座舱（R1） ----------
// 组织口径：基础八股按专题分组、项目内容依托核心模块与通路；题目判断
// 只记录到题目（单题通过不代表整个模块掌握）。详情统一进右侧 detail 面板。

const JUDGE_UI = {
  unjudged: {label: "未判断", cls: "unjudged"},
  pass: {label: "基本通过", cls: "pass"},
  deepen: {label: "需要深入", cls: "deepen"},
};
const Q_LEVEL_LABEL = {normal: "普通", firsthand: "亲历"};

async function postApi(path, body) {
  const response = await fetch(path, {
    method: "POST", cache: "no-store",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body || {}),
  });
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function cockpitFindPoint(id) {
  for (const g of cockpitData?.knowledge || [])
    for (const p of g.points) if (p.id === id) return {point: p, group: g.group};
  return null;
}

function cockpitFindModule(id) {
  return (cockpitData?.modules || []).find(m => m.id === id) || null;
}

function renderCockpit(data) {
  const pwBox = document.getElementById("cockpit-pathways");
  const knBox = document.getElementById("cockpit-knowledge");
  const moBox = document.getElementById("cockpit-modules");
  if (!pwBox || !knBox || !moBox) return;
  pwBox.replaceChildren(); knBox.replaceChildren(); moBox.replaceChildren();
  const note = document.getElementById("cockpit-note");
  if (data && data.unavailable) {
    if (note) note.textContent = "座舱接口不存在：页面服务是旧版本，重启服务进程后刷新即可。";
    return;
  }
  if (!data || (!(data.knowledge || []).length && !(data.modules || []).length)) {
    if (note) note.textContent = "本课程还没有可装配的复习内容（知识块 / 项目模块 / 题目）。";
    return;
  }
  if (note) note.textContent = (data.note || "") + " 判断与浏览不改变学习进度。";

  // 通路条：正常/异步/异常，步骤即模块，点开看模块详情
  for (const pw of data.pathways || []) {
    const row = document.createElement("div"); row.className = "cp-pathway";
    const title = document.createElement("span"); title.className = "cp-pathway-title";
    title.textContent = pw.title; row.append(title);
    const steps = document.createElement("div"); steps.className = "cp-steps";
    (pw.steps || []).forEach((s, i) => {
      if (i) {
        const arrow = document.createElement("span"); arrow.className = "cp-arrow";
        arrow.textContent = "→"; steps.append(arrow);
      }
      const mod = cockpitFindModule(s.module);
      const chip = document.createElement("button"); chip.type = "button";
      chip.className = "cp-step";
      const ref = document.createElement("strong");
      ref.textContent = mod ? mod.ref : s.module;
      chip.append(ref);
      if (s.note) {
        const n = document.createElement("span"); n.className = "cp-step-note";
        n.textContent = s.note; chip.append(n);
      }
      chip.title = mod ? mod.title : s.module;
      chip.onclick = () => showCockpitModule(s.module);
      steps.append(chip);
    });
    row.append(steps); pwBox.append(row);
  }

  // 基础八股：按专题分组（知识关系/上下游来自分组本身），题目判断汇总到组
  const knHead = document.createElement("h3"); knHead.className = "cp-col-title";
  knHead.textContent = "基础八股"; knBox.append(knHead);
  for (const g of data.knowledge || []) {
    const det = document.createElement("details"); det.className = "cp-group";
    bindTreeToggle(det, "cp:g:" + courseId + ":" + g.group, false);
    const sum = document.createElement("summary");
    const t = document.createElement("span"); t.className = "gt-title";
    t.textContent = g.group; sum.append(t);
    const meta = document.createElement("span"); meta.className = "muted gt-meta";
    meta.textContent = `${g.points.length} 点 · 题 ${g.q_total}`;
    sum.append(meta);
    if (g.q_pass) sum.append(cockpitCountChip("pass", g.q_pass));
    if (g.q_deepen) sum.append(cockpitCountChip("deepen", g.q_deepen));
    det.append(sum);
    const list = document.createElement("div"); list.className = "cp-list";
    for (const p of g.points) {
      const row = document.createElement("button"); row.type = "button";
      row.className = "cp-row";
      const name = document.createElement("span"); name.className = "cp-row-title";
      name.textContent = p.title; row.append(name);
      const st = document.createElement("span");
      st.className = "kn-status";
      st.textContent = p.review_status === "unknown" ? "未知" : "循环中";
      row.append(st);
      row.append(cockpitJudgeSummary(p.questions));
      row.onclick = () => showCockpitPoint(p.id);
      list.append(row);
    }
    det.append(list); knBox.append(det);
  }

  // 项目模块：M01–M08，通路之外的全量模块列
  const moHead = document.createElement("h3"); moHead.className = "cp-col-title";
  moHead.textContent = "项目模块"; moBox.append(moHead);
  const mlist = document.createElement("div"); mlist.className = "cp-list";
  for (const m of data.modules || []) {
    const row = document.createElement("button"); row.type = "button";
    row.className = "cp-row";
    const name = document.createElement("span"); name.className = "cp-row-title";
    const ref = document.createElement("strong"); ref.textContent = m.ref + " ";
    name.append(ref, document.createTextNode(m.title.replace(/^M\d+\s*/, "")));
    row.append(name);
    row.append(cockpitJudgeSummary(m.questions));
    row.onclick = () => showCockpitModule(m.id);
    mlist.append(row);
  }
  moBox.append(mlist);
}

function cockpitCountChip(kind, n) {
  const c = document.createElement("span");
  c.className = "cp-cnt " + kind;
  c.textContent = JUDGE_UI[kind].label + " " + n;
  return c;
}

// 题目判断汇总 chips：只到题目粒度，不冒充点/模块掌握
function cockpitJudgeSummary(questions) {
  const box = document.createElement("span"); box.className = "cp-judges";
  const qs = questions || [];
  const n = k => qs.filter(q => q.judgment === k).length;
  if (!qs.length) {
    const none = document.createElement("span"); none.className = "cp-cnt none";
    none.textContent = "无题"; box.append(none); return box;
  }
  if (n("unjudged")) box.append(cockpitCountChip("unjudged", n("unjudged")));
  if (n("pass")) box.append(cockpitCountChip("pass", n("pass")));
  if (n("deepen")) box.append(cockpitCountChip("deepen", n("deepen")));
  return box;
}

function showCockpitPoint(id) {
  knowledgeRequestVersion++;
  const found = cockpitFindPoint(id);
  if (!found) return;
  cockpitSel = {kind: "point", id};
  const {point: p, group} = found;
  const pane = document.getElementById("detail");
  pane.replaceChildren();
  const eyebrow = document.createElement("span"); eyebrow.className = "eyebrow";
  eyebrow.textContent = "REVIEW POINT · " + group; pane.append(eyebrow);
  const h = document.createElement("h2"); h.textContent = p.title; pane.append(h);
  const meta = document.createElement("p"); meta.className = "muted";
  meta.textContent = `锚点 ${p.anchor} · 辅助排期：${p.review_status === "unknown" ? "尚未进入循环" : "循环中"}（不是掌握判断）`;
  pane.append(meta);
  // 双向关联：该知识点被哪些项目模块引用（笔记正文锚点解析而来）
  if ((p.modules || []).length) {
    const box = document.createElement("div"); box.className = "cp-links";
    const t = document.createElement("span"); t.className = "cp-links-title";
    t.textContent = "项目中的使用位置："; box.append(t);
    for (const mid of p.modules) {
      const m = cockpitFindModule(mid);
      const b = document.createElement("button"); b.type = "button";
      b.className = "cp-link-chip";
      b.textContent = m ? m.ref : mid; b.title = m ? m.title : mid;
      b.onclick = () => showCockpitModule(mid);
      box.append(b);
    }
    pane.append(box);
  }
  cockpitQuestionSection(pane, p.questions);
  const traces = document.createElement("details");
  const traceTitle = document.createElement("summary");
  traceTitle.textContent = "在哪里讲过 · 按需查看教学关联";
  const traceBody = document.createElement("div");
  traces.append(traceTitle, traceBody); pane.append(traces);
  const traceCourse = courseId;
  let loaded = false;
  traces.ontoggle = async () => {
    if (!traces.open || loaded) return;
    loaded = true; traceBody.textContent = "读取关联…";
    try {
      const data = await api("/api/knowledge_connections?course_id=" + encodeURIComponent(traceCourse)
        + "&point_id=" + encodeURIComponent(p.point_id));
      traceBody.replaceChildren();
      for (const item of data.teaching_items || []) {
        const line = document.createElement("p");
        line.textContent = `${item.title} · ${item.course_id} · ${TT_STATUS[item.kind]?.[item.status] || item.status}`;
        traceBody.append(line);
      }
      if (!data.teaching_items?.length) traceBody.textContent = "暂无明确关联；不代表没学过，不从历史标题猜测掌握。";
    } catch (err) { loaded = false; traceBody.textContent = "关联读取失败：" + err.message; }
  };
}

function showCockpitModule(id) {
  knowledgeRequestVersion++;
  const m = cockpitFindModule(id);
  if (!m) return;
  cockpitSel = {kind: "module", id};
  const pane = document.getElementById("detail");
  pane.replaceChildren();
  const eyebrow = document.createElement("span"); eyebrow.className = "eyebrow";
  eyebrow.textContent = "PROJECT MODULE · " + m.ref; pane.append(eyebrow);
  const h = document.createElement("h2");
  h.textContent = m.title.replace(/^M\d+\s*/, ""); pane.append(h);
  // 双向关联反向：模块引用哪些基础知识锚点
  if ((m.points || []).length) {
    const box = document.createElement("div"); box.className = "cp-links";
    const t = document.createElement("span"); t.className = "cp-links-title";
    t.textContent = "涉及基础知识："; box.append(t);
    for (const pid of m.points) {
      const chip = document.createElement("span"); chip.className = "cp-link-chip static";
      chip.textContent = pid; box.append(chip);
    }
    pane.append(box);
  }
  cockpitQuestionSection(pane, m.questions);
}

// 题目列：题干 + 等级 + 当前判断（含具体缺口）+ 判断操作。
// 需要深入必须填缺口；提交后只重拉座舱数据并原地重显详情。
function cockpitQuestionSection(pane, questions) {
  const qs = questions || [];
  const head = document.createElement("h3"); head.className = "cp-sec-title";
  head.textContent = qs.length ? `依托题目 ${qs.length}` : "依托题目";
  pane.append(head);
  if (!qs.length) {
    const p = document.createElement("p"); p.className = "muted";
    p.textContent = "还没有挂到这里的题目。"; pane.append(p); return;
  }
  const list = document.createElement("div"); list.className = "cp-qlist";
  for (const q of qs) {
    const card = document.createElement("div");
    card.className = "cp-q " + (JUDGE_UI[q.judgment] || JUDGE_UI.unjudged).cls;
    const stem = document.createElement("p"); stem.className = "cp-q-stem";
    stem.textContent = q.stem; card.append(stem);
    const tags = document.createElement("div"); tags.className = "cp-q-tags";
    const lv = document.createElement("span"); lv.className = "cp-tag";
    lv.textContent = Q_LEVEL_LABEL[q.level] || q.level; tags.append(lv);
    const gid = document.createElement("span"); gid.className = "cp-tag muted";
    gid.textContent = q.id; tags.append(gid);
    if (q.answer_pending) {
      const ap = document.createElement("span"); ap.className = "cp-tag pending";
      ap.textContent = "参考答案待补"; tags.append(ap);
    }
    const j = JUDGE_UI[q.judgment] || JUDGE_UI.unjudged;
    const jc = document.createElement("span"); jc.className = "cp-cnt " + j.cls;
    jc.textContent = j.label; tags.append(jc);
    card.append(tags);
    if (q.answer_summary) {
      const evidence = document.createElement("details");
      const title = document.createElement("summary"); title.textContent = "本次判断依据";
      const body = document.createElement("p"); body.textContent = q.answer_summary;
      if (q.teaching_item_id != null) body.textContent += ` · 教学小项 #${q.teaching_item_id}`;
      evidence.append(title, body); card.append(evidence);
    }
    if (q.judgment === "deepen" && q.gap_note) {
      const gap = document.createElement("p"); gap.className = "cp-q-gap";
      gap.textContent = "缺口：" + q.gap_note; card.append(gap);
    }
    const ops = document.createElement("div"); ops.className = "cp-q-ops";
    const passBtn = document.createElement("button"); passBtn.type = "button";
    passBtn.className = "cp-btn pass"; passBtn.textContent = "基本通过";
    passBtn.onclick = () => submitJudgment(q.id, "pass", "", card);
    const gapInput = document.createElement("input");
    gapInput.className = "cp-gap-input"; gapInput.placeholder = "具体缺口（需要深入时必填）";
    gapInput.value = q.judgment === "deepen" ? (q.gap_note || "") : "";
    const deepenBtn = document.createElement("button"); deepenBtn.type = "button";
    deepenBtn.className = "cp-btn deepen"; deepenBtn.textContent = "需要深入";
    deepenBtn.onclick = () => submitJudgment(q.id, "deepen", gapInput.value.trim(), card);
    ops.append(passBtn, deepenBtn, gapInput); card.append(ops);
    list.append(card);
  }
  pane.append(list);
}

async function submitJudgment(qid, result, gapNote, card) {
  if (result === "deepen" && !gapNote) {
    const input = card.querySelector(".cp-gap-input");
    if (input) { input.classList.add("missing"); input.focus(); }
    return;
  }
  for (const b of card.querySelectorAll("button")) b.disabled = true;
  try {
    await postApi("/api/cockpit/judgment",
      {question_id: qid, result, gap_note: gapNote});
    cockpitData = await api("/api/cockpit?course_id=" + encodeURIComponent(courseId));
    renderCockpit(cockpitData);
    if (cockpitSel?.kind === "point") showCockpitPoint(cockpitSel.id);
    else if (cockpitSel?.kind === "module") showCockpitModule(cockpitSel.id);
  } catch (err) {
    showSyncError(err);
    for (const b of card.querySelectorAll("button")) b.disabled = false;
  }
}

function renderRecordSummary(dashboard) {
  const records = dashboard.record_counts;
  const box = document.getElementById("record-summary");
  if (!records) {
    box.textContent = "记录分类暂不可用，请重启页面服务以加载新版统计。";
    return;
  }
  box.replaceChildren();
  const eventText = Object.entries(records.event_types).map(([type, count]) => `${eventLabel(type)} ${count}`).join(" · ");
  for (const text of [`本课程事件 ${records.events} 条`, `教学更新 ${records.teaching_updates} 条`]) {
    const badge = document.createElement("span"); badge.textContent = text; box.append(badge);
  }
  box.title = eventText;
}

function renderHero(dashboard, graph, next) {
  const course = graph.nodes.find(node => node.type === "course");
  document.getElementById("course-title").textContent = course?.display_title || course?.title || courseId;
  document.getElementById("course-summary").textContent = course?.summary || "";
  const progress = dashboard.objective_progress;
  const demonstrated = progress.counts.demonstrated;
  const ratio = progress.total ? demonstrated / progress.total : 0;
  document.getElementById("course-progress-bar").style.width = `${Math.round(ratio * 100)}%`;
  document.getElementById("course-progress-label").textContent = `${demonstrated} / ${progress.total}`;

  // Keep three different facts distinct: the teaching cursor (where the AI
  // is teaching), an active session's stack top, and the derived next-action
  // suggestion. The card says which one it is showing instead of presenting
  // the teaching position as a "suggestion".
  const active = dashboard.active_session;
  const eyebrow = document.getElementById("next-action-eyebrow");
  let title, detail;
  if (teachingState?.workspace) {
    eyebrow.textContent = "当前教学位置";
    title = titleForNode(teachingState.workspace.section_id)
      || teachingState.workspace.section_id;
    detail = `继续教学进度 · ${teachingState.workspace.focus || "按当前模块学习"}`;
  } else if (active) {
    eyebrow.textContent = "进行中的会话";
    title = active.current_node?.title || active.root_goal.title;
    detail = `继续${MODE_LABEL[active.mode] || active.mode} · 根目标：${active.root_goal.title}`;
  } else {
    eyebrow.textContent = "建议下一步";
    title = titleForNode(next?.node_id) || actionTitle(next?.kind);
    detail = humanizeNext(next);
  }
  document.getElementById("next-action-title").textContent = title || "等待学习记录";
  document.getElementById("next-action-detail").textContent = detail || "";
}

function renderStats(dashboard) {
  const progress = dashboard.objective_progress;
  const counts = progress.counts;
  setText("stat-demonstrated", `${counts.demonstrated} / ${progress.total}`);
  setText("stat-demonstrated-sub", `${Math.round(progress.demonstrated_ratio * 100)}% 的目标通过无提示或轻提示验证`);
  setText("stat-progress", String(counts.in_progress));
  setText("stat-review", String(dashboard.review.due_count));
  setText("stat-review-sub", `目标测试中有 ${counts.struggling} 个薄弱点；已通过目标超过 ${dashboard.review.interval_days} 天进入复习`);
  const coverage = dashboard.source_coverage;
  setText("stat-coverage", `${Math.round(coverage.ratio * 100)}%`);
  setText("stat-coverage-sub", `${coverage.covered} / ${coverage.attached} 处知识点与材料关联已记录覆盖`);
  const chapter = dashboard.chapter_progress;
  const chapterCard = document.getElementById("stat-chapter-card");
  if (chapter && chapter.total > 0) {
    chapterCard.hidden = false;
    setText("stat-chapter", `${chapter.passed} / ${chapter.total}`);
  } else {
    chapterCard.hidden = true;
  }
}

function renderRequestChain(graph) {
  const box = document.getElementById("request-chain");
  if (!box) return;
  box.textContent = "";
  const nodeById = Object.fromEntries(graph.nodes.map(n => [n.id, n]));
  const units = graph.nodes.filter(n => n.type === "unit");
  const nextOf = {}, prevOf = {};
  for (const e of graph.edges) {
    if (e.type !== "sequence") continue;
    if (nodeById[e.src]?.type === "unit" && nodeById[e.dst]?.type === "unit") {
      nextOf[e.src] = e.dst;
      prevOf[e.dst] = e.src;
    }
  }
  const heads = units.filter(u => !prevOf[u.id]);
  const progressUnit = chainUnitOf(suggestedNodeId, graph);
  const selectedUnit = chainUnitOf(selectedNodeId, graph);
  let steps = [];
  if (heads.length) {
    let cur = heads.sort((a, b) => a.sort_order - b.sort_order)[0];
    const seen = new Set();
    while (cur && !seen.has(cur.id)) {
      seen.add(cur.id);
      steps.push(cur);
      cur = nodeById[nextOf[cur.id]];
    }
  } else {
    steps = sorted(units);
  }
  steps.push(...sorted(units.filter(unit => !steps.some(step => step.id === unit.id))));
  if (!steps.length) {
    const p = document.createElement("p"); p.className = "muted";
    p.textContent = "当前课程还没有可展示的主链顺序。";
    box.appendChild(p); return;
  }
  steps.forEach((unit, i) => {
    if (i) {
      const arrow = document.createElement("span");
      arrow.className = "chain-arrow";
      arrow.textContent = "→";
      box.appendChild(arrow);
    }
    const step = document.createElement("button");
    step.type = "button";
    step.className = "chain-step";
    step.dataset.nodeId = unit.id;
    step.classList.add(`status-${unitLearningStatus(unit.id, graph)}`);
    if (unit.id === progressUnit) step.classList.add("current");
    if (unit.id === selectedUnit) step.classList.add("selected");
    const num = document.createElement("small");
    num.textContent = String(i + 1).padStart(2, "0");
    const name = document.createElement("span");
    name.textContent = unit.title;
    step.append(num, name);
    step.title = `${unit.title} · ${STATUS_LABEL[unitLearningStatus(unit.id, graph)]}`;
    step.setAttribute("aria-pressed", String(unit.id === selectedUnit));
    if (unit.id === progressUnit) {
      const marker = document.createElement("b"); marker.className = "current-label";
      marker.textContent = "正在学"; step.append(marker);
    }
    step.onclick = () => showNode(unit.id);
    box.appendChild(step);
  });
}

function unitLearningStatus(unitId, graph) {
  const objectiveIds = graph.edges
    .filter(e => e.type === "part_of" && e.dst === unitId)
    .map(e => e.src)
    .filter(id => graph.nodes.some(n => n.id === id && n.type === "objective"));
  if (!objectiveIds.length) return "untouched";
  const values = objectiveIds.map(nodeStatus);
  if (values.includes("struggling")) return "struggling";
  if (values.every(value => value === "demonstrated")) return "demonstrated";
  if (values.some(value => value === "in_progress" || value === "demonstrated")) return "in_progress";
  return "untouched";
}

function chainUnitOf(nodeId, graph) {
  if (!nodeId) return null;
  const nodeById = Object.fromEntries(graph.nodes.map(n => [n.id, n]));
  const parentOf = {};
  for (const e of graph.edges) if (e.type === "part_of") parentOf[e.src] = e.dst;
  let cur = nodeId;
  const seen = new Set();
  while (cur && !seen.has(cur)) {
    seen.add(cur);
    if (nodeById[cur]?.type === "unit") return cur;
    cur = parentOf[cur];
  }
  return null;
}

// ---------------------------------------------------------------- trees
// Expansion state is user-owned: explicit open/close choices survive the 15s
// auto-refresh; untouched nodes follow the computed default (current path
// expanded, everything else folded).
const treePref = {open: new Set(), closed: new Set()};

function bindTreeToggle(det, key, defaultOpen) {
  det.open = treePref.open.has(key) || (defaultOpen && !treePref.closed.has(key));
  det.addEventListener("toggle", () => {
    if (det.open) { treePref.open.add(key); treePref.closed.delete(key); }
    else { treePref.closed.add(key); treePref.open.delete(key); }
  });
}

const TT_STATUS = {
  milestone: {pending: "待讲", active: "进行中", presented: "已讲解待确认", self_reported_understood: "用户确认理解", done: "验证通过", deferred: "暂缓", retracted: "已作废"},
  section: {pending: "待讲", active: "进行中", presented: "已讲解待确认", self_reported_understood: "用户确认理解", done: "验证通过", deferred: "暂缓", retracted: "已作废"},
  sub: {pending: "待讲", active: "进行中", presented: "已讲解待确认", self_reported_understood: "用户确认理解", done: "验证通过", deferred: "暂缓", retracted: "已作废"},
  question: {open: "讨论中", awaiting_confirmation: "已回答待确认", resolved: "用户确认结束", deferred: "暂缓"},
};

function renderCurrentTree(state, tree) {
  const wrap = document.createElement("div"); wrap.className = "ttree";
  const items = tree.items || [];
  const nav = tree.navigation || {};
  const cursorId = tree.cursor?.item_id || null;
  const returnId = nav.return_position?.item_id || null;
  const nextId = nav.next_item?.id || null;

  // 作废项（retracted）不进正式顺序与统计；按父级留痕，默认折叠可查。
  const kids = {}; const retractedKids = {};
  for (const it of items) {
    const key = it.parent_id || "";
    if (it.status === "retracted") (retractedKids[key] ||= []).push(it);
    else (kids[key] ||= []).push(it);
  }
  for (const list of Object.values(kids)) list.sort((a, b) => a.seq - b.seq || a.id - b.id);

  // Default expansion: the cursor's ancestor chain plus the cursor item
  // itself, so the current path is visible and everything else stays folded.
  const defaultOpen = new Set();
  if (cursorId) {
    const byId = Object.fromEntries(items.map(i => [i.id, i]));
    let cur = byId[cursorId];
    while (cur) { defaultOpen.add(cur.id); cur = byId[cur.parent_id]; }
  }

  const counts = {done: 0, presented: 0, understood: 0, total: 0, openQ: 0, deferred: 0};
  for (const it of items) {
    if (it.status === "retracted") continue;
    if (it.kind !== "question") {
      counts.total++;
      if (it.status === "done") counts.done++;
      else if (it.status === "presented") counts.presented++;
      else if (it.status === "self_reported_understood") counts.understood++;
    }
    else if (["open", "awaiting_confirmation"].includes(it.status)) counts.openQ++;
    if (it.status === "deferred") counts.deferred++;
  }
  const head = document.createElement("p"); head.className = "muted batch-head";
  head.textContent = `教学计划 v${tree.plan.version} · ${counts.done}/${counts.total} 项验证通过`
    + (counts.presented ? ` · ${counts.presented} 项已讲解待确认` : "")
    + (counts.understood ? ` · ${counts.understood} 项用户确认理解` : "")
    + (counts.openQ ? ` · ${counts.openQ} 个讨论中/待确认问题` : "")
    + (counts.deferred ? ` · ${counts.deferred} 个暂缓` : "");
  wrap.append(head);

  // 过程记录按教学小项折叠（记录级 item_id 来自 topic_org 覆盖层）；
  // 与下方主题分组是同一份整理结果，已挂小项的记录不再重复平铺。
  const topicsByItem = {};
  for (const g of tree.topic_groups?.groups || []) {
    for (const t of g.items || []) {
      if (t.item_id) (topicsByItem[t.item_id] ||= []).push({...t, theme: g.title});
    }
  }

  // Position line: every fact comes from the backend cursor/navigation.
  if (cursorId) {
    const cur = items.find(i => i.id === cursorId);
    const bits = [];
    if (cur?.kind === "question") {
      const path = (nav.parent_path || []).map(p => p.title).join(" / ");
      bits.push(`当前讲解：${path || "—"}`, `当前追问：${cur.title}`);
    } else if (cur) {
      const path = [...(nav.parent_path || []).map(p => p.title), cur.title].join(" / ");
      bits.push(`当前讲解：${path}`);
    }
    if (nav.return_position) bits.push(`追问返回位置：${nav.return_position.title || nav.return_position.note || ""}`);
    const nxt = nav.next_item ? `下一小项：${nav.next_item.title}`
      : nav.next_milestone ? `下一阶段：${nav.next_milestone.title}` : "";
    if (nxt) bits.push(nxt);
    const pos = document.createElement("p"); pos.className = "muted tt-posline";
    pos.textContent = bits.join(" · ");
    wrap.append(pos);
  }

  const ctx = {kids, retractedKids, defaultOpen, cursorId, returnId, nextId, milestoneId: nav.milestone_id, topicsByItem};
  const reminders = tree.reminders || state.reminders;
  if (reminders?.count) {
    const panel = document.createElement('details'); panel.className = 'tt-reminders';
    bindTreeToggle(panel, 'tt-reminders:' + courseId, true);
    const summary = document.createElement('summary');
    summary.textContent = `未收口问题 ${reminders.count} 个 · 已回答待确认 ${reminders.awaiting_confirmation_count} 个`;
    panel.append(summary);
    const hint = document.createElement('p'); hint.className = 'muted';
    hint.textContent = '并列问题分别保留，深入一个分支不代表其他问题结束。这里只提醒，不阻止继续学习。';
    panel.append(hint);
    const rows = document.createElement('ul');
    for (const q of reminders.items || []) {
      const row = document.createElement('li');
      const link = document.createElement('button'); link.type = 'button'; link.className = 'tt-reminder-link';
      link.textContent = q.title;
      link.onclick = () => {
        const target = document.getElementById('teaching-item-' + q.id);
        if (!target) return;
        for (let el = target; el && el !== wrap; el = el.parentElement) {
          if (el.tagName === 'DETAILS') el.open = true;
        }
        target.scrollIntoView({behavior: 'smooth', block: 'center'});
      };
      row.append(link, document.createTextNode(' · ' + (TT_STATUS.question[q.status] || q.status)));
      const path = document.createElement('small'); path.className = 'muted';
      path.textContent = (q.path || []).slice(0, -1).map(p => p.title).join(' → ');
      row.append(path); rows.append(row);
    }
    panel.append(rows);
    if (reminders.has_more) {
      const more = document.createElement('p'); more.className = 'muted';
      more.textContent = '还有其他未收口问题，可在下方学习树展开查看。'; panel.append(more);
    }
    wrap.append(panel);
  }
  const roots = kids[""] || [];
  if (!roots.length) {
    const p = document.createElement("p"); p.className = "focus-empty";
    p.textContent = "计划还没有分段。"; wrap.append(p); return wrap;
  }
  const list = document.createElement("div"); list.className = "tt-list";
  for (const it of roots) list.append(ttNode(it, ctx));
  wrap.append(list);
  return wrap;
}

function ttNode(it, ctx) {
  const children = ctx.kids[it.id] || [];
  const dead = (ctx.retractedKids || {})[it.id] || [];
  const recs = (ctx.topicsByItem || {})[it.id] || [];
  const hasBody = children.length > 0 || Boolean(it.note) || recs.length > 0 || dead.length > 0;
  const row = document.createElement(hasBody ? "details" : "div");
  row.id = 'teaching-item-' + it.id;
  // 节的显示状态从子级推导（数据不改写）：有进行中子级→进行中；全结束→已结束。
  const effStatus = (it.kind === "section" && children.length)
    ? (children.some(c => c.status === "active") ? "active"
       : children.every(c => c.status === "done") ? "done" : it.status)
    : it.status;
  row.className = `tt-node tt-${it.kind} st-${effStatus}`;
  if (it.id === ctx.cursorId) row.classList.add("is-cursor");
  else if (it.id === ctx.milestoneId && ctx.cursorId) row.classList.add("is-path");
  const head = document.createElement(hasBody ? "summary" : "div");
  head.className = "tt-head";
  const title = document.createElement("span"); title.className = "tt-title";
  title.textContent = it.title;
  const chips = document.createElement("span"); chips.className = "tt-chips";
  const addChip = (text, cls) => {
    const c = document.createElement("span"); c.className = "tt-chip " + cls;
    c.textContent = text; chips.append(c);
  };
  addChip(TT_STATUS[it.kind]?.[effStatus] || effStatus, "st");
  if (it.kind === "section") {
    const subs = children.filter(c => c.kind === "sub");
    if (subs.length) {
      const dn = subs.filter(c => c.status === "done").length;
      const pn = subs.filter(c => c.status === "presented").length;
      const un = subs.filter(c => c.status === "self_reported_understood").length;
      addChip(`${dn}/${subs.length} 小节验证通过` + (pn ? ` · ${pn} 待确认` : "")
        + (un ? ` · ${un} 用户确认理解` : ""), "cnt");
    }
  }
  if (it.id === ctx.cursorId) addChip("当前", "cur");
  if (it.id === ctx.returnId) addChip("返回位置", "ret");
  if (it.id === ctx.nextId) addChip("下一项", "next");
  head.append(title, chips);
  row.append(head);
  if (hasBody) {
    bindTreeToggle(row, "tt:" + courseId + ":" + it.id, ctx.defaultOpen.has(it.id));
    const body = document.createElement("div"); body.className = "tt-body";
    if (it.note) {
      const nd = document.createElement("details"); nd.className = "tt-note";
      bindTreeToggle(nd, "ttn:" + courseId + ":" + it.id, false);
      const ns = document.createElement("summary"); ns.textContent = "回答摘要 / 过程备注";
      const nt = document.createElement("p"); nt.textContent = it.note;
      nd.append(ns, nt); body.append(nd);
    }
    if (recs.length) {
      const rd = document.createElement("details"); rd.className = "tt-recs";
      bindTreeToggle(rd, "ttr:" + courseId + ":" + it.id, false);
      const rs = document.createElement("summary");
      const openCount = recs.filter(t => ["question", "revisit"].includes(t.status)).length;
      rs.textContent = `过程记录 ${recs.length} 条` + (openCount ? ` · ${openCount} 个疑问/待回补` : "");
      rd.append(rs);
      // 同一小项内按主题再分组，主题关系不丢
      const byTheme = {};
      for (const t of recs) (byTheme[t.theme] ||= []).push(t);
      for (const [theme, list] of Object.entries(byTheme)) {
        const tl = document.createElement("p"); tl.className = "muted tt-recs-theme";
        tl.textContent = theme;
        rd.append(tl);
        const chips = document.createElement("div"); chips.className = "tt-topics-body";
        for (const t of list) {
          const chip = document.createElement("span");
          chip.className = "tt-topic-chip " + t.status;
          chip.textContent = t.title;
          chips.append(chip);
        }
        rd.append(chips);
      }
      body.append(rd);
    }
    for (const c of children) body.append(ttNode(c, ctx));
    if (dead.length) {
      const dd = document.createElement("details"); dd.className = "tt-retracted";
      bindTreeToggle(dd, "ttx:" + courseId + ":" + it.id, false);
      const ds = document.createElement("summary");
      ds.textContent = `已作废 ${dead.length} 条（留痕，不参与正式顺序）`;
      dd.append(ds);
      for (const d of dead) {
        const p = document.createElement("p"); p.className = "muted tt-retracted-item";
        p.textContent = d.title + (d.note ? ` — ${d.note}` : "");
        dd.append(p);
      }
      body.append(dd);
    }
    row.append(body);
  }
  return row;
}

// Global learning tree (默认入口): course → modules → units → objectives,
// teaching branches and topic records folded by default. All records come
// from /api/learning_tree; clicking a unit/objective opens the shared detail
// panel (lazy records via /api/node). Nothing here writes progress.
function renderGlobalTree(tree) {
  const box = document.getElementById("learning-tree");
  if (!box) return;
  box.replaceChildren();
  if (!tree || (!(tree.modules || []).length && !(tree.units || []).length)) {
    const p = document.createElement("p"); p.className = "muted";
    p.textContent = "当前课程还没有可展示的学习树结构。";
    box.append(p); return;
  }
  if (moduleId) { renderModulePage(box, tree); return; }
  if ((tree.outline || []).length) {
    const det = document.createElement("details"); det.className = "gt-outline";
    bindTreeToggle(det, "gt:outline:" + courseId, true);
    const sum = document.createElement("summary");
    const cur = tree.outline.find(s => s.status === "current");
    sum.textContent = "课程讲解规划"
      + (cur ? ` · 当前阶段：${cur.title}` : "");
    det.append(sum);
    for (const s of tree.outline) {
      const row = document.createElement("div");
      row.className = "gt-stage st-" + s.status;
      const st = document.createElement("span"); st.className = "gt-stage-status";
      st.textContent = {current: "当前", pending: "待展开", done: "已结束"}[s.status] || s.status;
      const ti = document.createElement("span"); ti.className = "gt-stage-title";
      ti.textContent = `${s.seq}. ${s.title}`;
      const goal = document.createElement("p"); goal.className = "muted gt-stage-goal";
      goal.textContent = s.goal + (s.note ? `（${s.note}）` : "");
      row.append(st, ti); det.append(row, goal);
    }
    box.append(det);
  }
  for (const m of tree.modules || []) box.append(gtModule(m, tree));
  for (const u of tree.units || []) box.append(gtUnit(u, tree));
  if ((tree.unassigned?.topics || []).length) {
    const total = tree.unassigned.topics.reduce((n, g) => n + g.topics.length, 0);
    const det = document.createElement("details"); det.className = "gt-unassigned";
    bindTreeToggle(det, "gt:unassigned:" + courseId, false);
    const sum = document.createElement("summary");
    sum.textContent = `待归位记录 ${total} 条（原归属小节已不在当前结构中；保留原记录，不删除、不凭标题强行分类）`;
    det.append(sum);
    for (const g of tree.unassigned.topics) {
      const h = document.createElement("p"); h.className = "muted";
      h.textContent = `原归属：${g.section_id}`; det.append(h);
      const chips = document.createElement("div"); chips.className = "tt-topics-body";
      for (const t of g.topics) {
        const chip = document.createElement("span");
        chip.className = "tt-topic-chip " + t.status;
        chip.textContent = t.title; chips.append(chip);
      }
      det.append(chips);
    }
    box.append(det);
  }
}

function gtModule(m, tree) {
  const det = document.createElement("details"); det.className = "gt-module";
  const hasCurrent = (m.units || []).some(u => u.is_current);
  bindTreeToggle(det, "gtm:" + courseId + ":" + m.id,
    hasCurrent || (tree.modules || []).length <= 3);
  const sum = document.createElement("summary");
  const title = document.createElement("span"); title.className = "gt-title";
  title.textContent = m.title;
  const stats = {done: 0, total: 0};
  for (const u of m.units || []) {
    for (const o of u.objectives || []) {
      stats.total++; if (o.status === "demonstrated") stats.done++;
    }
  }
  const meta = document.createElement("span"); meta.className = "muted gt-meta";
  meta.textContent = `${(m.units || []).length} 个单元`
    + (stats.total ? ` · 目标 ${stats.done}/${stats.total} 已验证` : "");
  sum.append(title, meta);
  if (hasCurrent) {
    const c = document.createElement("b"); c.className = "current-label";
    c.textContent = "正在学"; sum.append(c);
  }
  const go = document.createElement("button"); go.type = "button";
  go.className = "gt-enter"; go.textContent = "模块页 →";
  go.onclick = ev => { ev.stopPropagation(); ev.preventDefault(); openModule(m.id); };
  sum.append(go);
  det.append(sum);
  const body = document.createElement("div"); body.className = "gt-units";
  for (const u of m.units || []) body.append(gtUnit(u, tree));
  det.append(body);
  return det;
}

function gtUnit(u, tree) {
  const det = document.createElement("details"); det.className = "gt-unit";
  if (u.is_current) det.classList.add("is-current");
  bindTreeToggle(det, "gtu:" + courseId + ":" + u.id, Boolean(u.is_current));
  const sum = document.createElement("summary");
  const title = document.createElement("button"); title.type = "button";
  title.className = "gt-unit-title"; title.textContent = u.title;
  title.onclick = ev => { ev.stopPropagation(); ev.preventDefault(); showNode(u.id); };
  const meta = document.createElement("span"); meta.className = "muted gt-meta";
  const parts = [];
  if ((u.objectives || []).length) {
    const done = u.objectives.filter(o => o.status === "demonstrated").length;
    parts.push(`目标 ${done}/${u.objectives.length}`);
  }
  if (u.records) parts.push(`记录 ${u.records} 条`);
  const topicCount = (u.topic_groups || []).reduce((n, g) => n + g.items.length, 0)
    + (u.topics_unassigned || []).length;
  if (topicCount) parts.push(`小点 ${topicCount}`);
  meta.textContent = parts.join(" · ");
  sum.append(title, meta);
  if (u.is_current) {
    const c = document.createElement("b"); c.className = "current-label";
    c.textContent = "正在学"; sum.append(c);
  }
  det.append(sum);
  const body = document.createElement("div"); body.className = "gt-unit-body";
  if ((u.objectives || []).length) {
    const ol = document.createElement("div"); ol.className = "gt-objs";
    for (const o of u.objectives) {
      const b = document.createElement("button"); b.type = "button";
      b.className = "gt-obj status-" + o.status;
      b.title = STATUS_LABEL[o.status] || o.status;
      b.textContent = o.title;
      b.onclick = () => showNode(o.id);
      ol.append(b);
    }
    body.append(ol);
  }
  for (const t of u.teaching || []) {
    const p = document.createElement("p"); p.className = "muted gt-teach";
    const c = t.counts || {};
    const segs = [];
    for (const [kind, byStatus] of Object.entries(c)) {
      const n = Object.values(byStatus).reduce((a, b) => a + b, 0);
      if (n) segs.push(`${TT_STATUS[kind] ? {milestone:"阶段",section:"节",sub:"分段",question:"追问"}[kind] : kind} ${n}`);
    }
    p.textContent = `教学计划 v${t.version}${t.active ? "（当前）" : ""}`
      + (segs.length ? ` · ${segs.join(" · ")}` : "");
    body.append(p);
  }
  // 教学条目分支：与本次树同一份 items（同 ID/标题/状态），全局树默认折叠
  const tt = (typeof teachingTreeData !== "undefined") ? teachingTreeData : null;
  if (tt && tt.section_id === u.id && (tt.items || []).length) {
    const det = document.createElement("details"); det.className = "gt-items";
    bindTreeToggle(det, "gti:" + courseId + ":" + u.id, false);
    const sum = document.createElement("summary");
    const nSub = tt.items.filter(i => i.kind !== "question" && i.status !== "retracted").length;
    const nQ = tt.items.filter(i => i.kind === "question").length;
    sum.textContent = `教学条目 ${nSub} 项` + (nQ ? ` · 追问 ${nQ}` : "")
      + "（与上方教学进度同一份记录）";
    det.append(sum);
    const kids = {}; const retractedKids = {};
    for (const it of tt.items) {
      const key = it.parent_id || "";
      if (it.status === "retracted") (retractedKids[key] ||= []).push(it);
      else (kids[key] ||= []).push(it);
    }
    for (const list of Object.values(kids)) list.sort((a, b) => a.seq - b.seq || a.id - b.id);
    const nav = tt.navigation || {};
    const ctx = {kids, retractedKids, defaultOpen: new Set(), cursorId: tt.cursor?.item_id || null,
      returnId: nav.return_position?.item_id || null, nextId: nav.next_item?.id || null,
      milestoneId: nav.milestone_id, topicsByItem: {}};
    for (const g of tt.topic_groups?.groups || [])
      for (const t of g.items || [])
        if (t.item_id) (ctx.topicsByItem[t.item_id] ||= []).push({...t, theme: g.title});
    const list = document.createElement("div"); list.className = "tt-list";
    for (const it of kids[""] || []) list.append(ttNode(it, ctx));
    det.append(list);
    body.append(det);
  }
  body.append(topicGroupsEl(u.topic_groups, u.topics_unassigned, "gtu-tg:" + courseId + ":" + u.id, true));
  det.append(body);
  return det;
}

// 小点分组渲染：本次树与全局树共用的同一份整理结果。
// 主题组（后补主题归类，标注 origin）+ 归档组 + 待归位；原始状态逐条保留。
function topicGroupsEl(groups, unassigned, keyBase, dropMapped = false) {
  const wrap = document.createElement("div"); wrap.className = "tg-wrap";
  const allTotal = (groups || []).reduce((n, g) => n + g.items.length, 0)
    + (unassigned || []).length;
  // 已挂教学小项的记录折叠在条目下，这里只展示未挂到小项的部分
  const view = (groups || [])
    .map(g => ({...g, items: dropMapped ? g.items.filter(t => !t.item_id) : g.items}))
    .filter(g => g.items.length || g.kind === "archive");
  const total = view.reduce((n, g) => n + g.items.length, 0) + (unassigned || []).length;
  if (!total && !allTotal) return wrap;
  const head = document.createElement("p"); head.className = "muted tg-head";
  const mapped = allTotal - total;
  head.textContent = `学习小点记录 ${allTotal} 条（过程记录，不进正式进度；分组为后补主题归类，原始状态未改）`
    + (mapped ? `；其中 ${mapped} 条已挂到教学小项下` : "");
  if (!total) { wrap.append(head); return wrap; }
  wrap.append(head);
  const chip = (t) => {
    const c = document.createElement("span");
    c.className = "tt-topic-chip " + t.status;
    c.textContent = t.title;
    const st = {question: "有疑问", revisit: "待回补", explained: "已讲解",
      untouched: "待学习", self_reported_understood: "自述理解"}[t.status] || t.status;
    c.title = `${st} · 首次记录 ${String(t.first_ts || "").slice(0, 10)}`;
    return c;
  };
  for (const g of view) {
    const det = document.createElement("details");
    det.className = "tg-group" + (g.kind === "archive" ? " tg-archive" : "");
    const openCount = g.items.filter(t => ["question", "revisit"].includes(t.status)).length;
    bindTreeToggle(det, keyBase + ":" + g.key, openCount > 0 && g.kind !== "archive");
    const sum = document.createElement("summary");
    const t = document.createElement("span"); t.className = "tg-title";
    t.textContent = g.title;
    const meta = document.createElement("span"); meta.className = "muted gt-meta";
    meta.textContent = `${g.items.length} 条` + (openCount ? ` · ${openCount} 个疑问/待回补` : "");
    sum.append(t, meta);
    if (g.kind === "archive") {
      const tag = document.createElement("span"); tag.className = "tg-tag";
      tag.textContent = "归档"; sum.append(tag);
    }
    det.append(sum);
    if (g.note) {
      const n = document.createElement("p"); n.className = "muted tg-note";
      n.textContent = g.note; det.append(n);
    }
    const chips = document.createElement("div"); chips.className = "tt-topics-body";
    for (const item of g.items) chips.append(chip(item));
    det.append(chips); wrap.append(det);
  }
  if ((unassigned || []).length) {
    const det = document.createElement("details"); det.className = "tg-group tg-unassigned";
    bindTreeToggle(det, keyBase + ":unassigned", false);
    const sum = document.createElement("summary");
    sum.textContent = `待归位 ${unassigned.length} 条（未能确认主题归属；保留原记录，不强行分类）`;
    det.append(sum);
    const chips = document.createElement("div"); chips.className = "tt-topics-body";
    for (const item of unassigned) chips.append(chip(item));
    det.append(chips); wrap.append(det);
  }
  return wrap;
}

function renderModulePage(box, tree) {
  const m = (tree.modules || []).find(x => x.id === moduleId);
  if (!m) { moduleId = null; updateLocationHash(); applyRouteView(); renderGlobalTree(tree); return; }
  const crumb = document.createElement("div"); crumb.className = "gt-crumb";
  const back = document.createElement("button"); back.type = "button";
  back.className = "gt-back"; back.textContent = "← 返回课程总览";
  back.onclick = closeModule;
  const where = document.createElement("span"); where.className = "gt-crumb-title";
  where.textContent = `${tree.title || tree.course_id} / ${m.title}`;
  crumb.append(back, where); box.append(crumb);
  const stats = {done: 0, total: 0};
  for (const u of m.units || []) {
    for (const o of u.objectives || []) {
      stats.total++; if (o.status === "demonstrated") stats.done++;
    }
  }
  const p = document.createElement("p"); p.className = "muted";
  p.textContent = `${(m.units || []).length} 个单元`
    + (stats.total ? ` · 目标 ${stats.done}/${stats.total} 已验证` : "")
    + (m.summary ? ` — ${m.summary}` : "");
  box.append(p);
  const note = document.createElement("p"); note.className = "section-note";
  note.textContent = "浏览模块页不改变教学位置与进度；这里与总览共用同一份记录。";
  box.append(note);
  const body = document.createElement("div"); body.className = "gt-units";
  for (const u of m.units || []) body.append(gtUnit(u, tree));
  box.append(body);
}

// 代码结构视图：只展示实际解析到的目录包含关系（已登记代码源 + 切分锚点），
// 不推断调用关系。顶层目录按需展开时懒加载该目录的文件与符号。
function renderCodeStructure(data) {
  const box = document.getElementById("code-structure");
  if (!box) return;
  box.replaceChildren();
  if (!data) return;
  const note = document.createElement("p"); note.className = "section-note";
  note.textContent = `关系：${data.relation || "目录包含（实）"} · 仅来自已登记代码源与切分锚点（文件:行号 · 符号），未解析调用关系。`;
  box.append(note);
  let shown = 0;
  for (const s of data.skeletons || []) {
    const det = document.createElement("details"); det.className = "cs-top cs-skeleton";
    bindTreeToggle(det, "cs:skel:" + s.id, false);
    const sum = document.createElement("summary");
    const t = document.createElement("span"); t.className = "gt-title";
    t.textContent = s.title;
    const meta = document.createElement("span"); meta.className = "muted gt-meta";
    meta.textContent = `学习骨架 · ${s.state_label || s.state} · ${(s.symbols || []).length} 个符号块`;
    sum.append(t, meta); det.append(sum);
    const syms = document.createElement("div"); syms.className = "cs-symbols cs-skeleton-symbols";
    for (const sym of s.symbols || []) {
      const chip = document.createElement("span"); chip.className = "cs-symbol";
      chip.textContent = `${sym.lines} ${sym.symbol}`;
      syms.append(chip);
    }
    det.append(syms); box.append(det); shown++;
  }
  for (const t of data.tops || []) {
    const det = document.createElement("details"); det.className = "cs-top";
    bindTreeToggle(det, "cs:top:" + courseId + ":" + t.name, false);
    const sum = document.createElement("summary");
    const name = document.createElement("span"); name.className = "gt-title";
    name.textContent = t.name + "/";
    const meta = document.createElement("span"); meta.className = "muted gt-meta";
    meta.textContent = `${t.files} 个文件 · ${t.chunks} 个符号块`;
    sum.append(name, meta); det.append(sum);
    const body = document.createElement("div"); body.className = "cs-files";
    det.append(body);
    det.addEventListener("toggle", () => loadCsDir(body, t.name), {once: true});
    box.append(det); shown++;
  }
  if (!shown) {
    const p = document.createElement("p"); p.className = "focus-empty";
    p.textContent = "本课程暂未登记项目代码或学习骨架，暂无代码视图。登记代码源或骨架后，这里按目录包含展示实际结构。";
    box.append(p);
  }
}

async function loadCsDir(body, top) {
  if (!body.isConnected || body.dataset.loaded) return;
  body.dataset.loaded = "1";
  const data = await api("/api/code_structure?course_id=" + encodeURIComponent(courseId)
    + "&top=" + encodeURIComponent(top));
  const files = data.files || [];
  body.replaceChildren();
  if (!files.length) {
    const p = document.createElement("p"); p.className = "muted";
    p.textContent = "这个目录下没有已切分的代码块。"; body.append(p); return;
  }
  for (const f of files) {
    const det = document.createElement("details"); det.className = "cs-file";
    bindTreeToggle(det, "cs:f:" + courseId + ":" + f.rel, false);
    const sum = document.createElement("summary");
    const name = document.createElement("span"); name.className = "cs-file-name";
    name.textContent = f.rel;
    const meta = document.createElement("span"); meta.className = "muted gt-meta";
    meta.textContent = (f.title ? f.title + " · " : "") + `${f.chunks} 块`;
    sum.append(name, meta); det.append(sum);
    const syms = document.createElement("div"); syms.className = "cs-symbols";
    for (const s of f.symbols || []) {
      const chip = document.createElement("span"); chip.className = "cs-symbol";
      chip.textContent = `${s.lines} ${s.symbol}`;
      chip.title = `${f.rel}:${s.lines} · ${s.symbol}`;
      syms.append(chip);
    }
    det.append(syms); body.append(det);
  }
}

// ---------------------------------------------------------------- 知识入口
// 目录：知识点（骨架锚点 / 复习知识点）按载体分组 + 资料清单；关系图 = 旧图谱。
const BASIS_LABEL = {"source-confirmed": "源码确认", "config-example": "配置/示例接线",
  inferred: "推断", manual: "人工整理"};

function linkButtons(links) {
  const wrap = document.createElement("div"); wrap.className = "link-list";
  for (const l of links || []) {
    const b = document.createElement("button"); b.type = "button";
    b.className = "link-chip kind-" + l.kind;
    const label = l.kind === "node" ? (titleForNode(l.id) || l.id)
      : l.kind === "code_module" ? (codeMapData?.components?.find(c => c.id === l.id)?.label || l.id)
      : l.kind === "theme" ? "主题：" + (l.id.split("#")[1] || l.id)
      : l.id.split("#").pop();
    b.textContent = label;
    b.title = `${{node: "学习位置/主链步骤", code_module: "代码模块", knowledge: "知识锚点", theme: "讲解主题"}[l.kind] || l.kind} · ${BASIS_LABEL[l.basis] || l.basis}` + (l.note ? ` · ${l.note}` : "");
    b.onclick = () => followLink(l);
    wrap.append(b);
  }
  return wrap;
}

function followLink(l) {
  if (l.kind === "node") { showNode(l.id); document.getElementById("detail").scrollIntoView({behavior: "smooth"}); }
  else if (l.kind === "knowledge") showKnowledge(l.id);
  else if (l.kind === "code_module") {
    routeView = "project"; pView = "map"; routeViewUserChosen = true;
    updateLocationHash(); applyRouteView(); showCodeModule(l.id);
  } else if (l.kind === "theme") {
    const [section, key] = l.id.split("#");
    routeView = "tree"; routeViewUserChosen = true;
    // 展开该单元与对应主题组（treePref 是用户级展开状态，浏览不写进度）
    treePref.open.add("gtu:" + courseId + ":" + section);
    treePref.closed.delete("gtu:" + courseId + ":" + section);
    treePref.open.add("gtu-tg:" + courseId + ":" + section + ":" + key);
    treePref.closed.delete("gtu-tg:" + courseId + ":" + section + ":" + key);
    updateLocationHash(); applyRouteView(); renderGlobalTree(learningTreeData);
  }
}

function renderKnowledge(data) {
  const box = document.getElementById("knowledge-catalog");
  if (!box) return;
  box.replaceChildren();
  if (!data) return;
  const blocks = data.blocks || [];
  if (!blocks.length && !(data.sources || []).length) {
    const p = document.createElement("p"); p.className = "focus-empty";
    p.textContent = "本课程还没有已定位的知识内容。登记资料或建立知识锚点后，目录会列在这里；未关联内容会如实标注。";
    box.append(p); return;
  }
  const byGroup = {};
  for (const b of blocks) (byGroup[b.group || "未分组"] ||= []).push(b);
  for (const [group, items] of Object.entries(byGroup)) {
    const det = document.createElement("details"); det.className = "kn-group";
    bindTreeToggle(det, "kn:g:" + courseId + ":" + group,
      !group.startsWith('项目实现') && !group.startsWith('面经题目'));
    const sum = document.createElement("summary");
    const t = document.createElement("span"); t.className = "gt-title"; t.textContent = group;
    const meta = document.createElement("span"); meta.className = "muted gt-meta";
    meta.textContent = `${items.length} 个知识位置`;
    sum.append(t, meta); det.append(sum);
    const list = document.createElement("div"); list.className = "kn-list";
    for (const b of items) {
      const row = document.createElement("button"); row.type = "button";
      row.className = "kn-row";
      const name = document.createElement("span"); name.className = "kn-title";
      // 锚点标题里的 " / " 是骨架里的嵌套路径：父级淡显为面包屑，末段加粗，
      // 纯展示层拆分，不改锚点本身
      const parts = String(b.title).split(" / ");
      if (parts.length > 1) {
        const path = document.createElement("span"); path.className = "kn-path";
        path.textContent = parts.slice(0, -1).join(" / ") + " / ";
        const leaf = document.createElement("strong");
        leaf.textContent = parts[parts.length - 1];
        name.append(path, leaf);
      } else {
        name.textContent = b.title;
      }
      row.append(name);
      const tag = document.createElement("span");
      tag.className = "kn-kind " + b.kind;
      tag.textContent = ({'skeleton-anchor':'骨架锚点',
        'project-anchor':'项目实现', 'interview-question':'面经题目'}[b.kind] || '知识点');
      row.append(tag);
      if (b.status) {
        const st = document.createElement("span"); st.className = "kn-status";
        st.textContent = b.status === "unknown" ? "未知" : "循环中";
        row.append(st);
      }
      const linked = (b.links || []).length;
      const lk = document.createElement("span");
      lk.className = "kn-links" + (linked ? "" : " none");
      lk.textContent = linked ? `关联 ${linked}` : "暂无关联";
      row.append(lk);
      row.onclick = () => showKnowledge(b.id);
      list.append(row);
    }
    det.append(list); box.append(det);
  }
  if ((data.sources || []).length) {
    const det = document.createElement("details"); det.className = "kn-group kn-sources";
    bindTreeToggle(det, "kn:sources:" + courseId, false);
    const sum = document.createElement("summary");
    const totalChunks = data.sources.reduce((n, s) => n + (s.chunks || 0), 0);
    sum.textContent = `资料清单 ${data.sources.length} 份 · ${totalChunks} 个检索块（索引定位用，清单不代表已学习）`;
    det.append(sum);
    const list = document.createElement("div"); list.className = "kn-list";
    for (const s of data.sources) {
      const row = document.createElement("div"); row.className = "source-item";
      const name = document.createElement("span"); name.className = "source-title";
      name.textContent = s.title; row.append(name);
      if (s.lecture_ref) {
        const role = document.createElement("span"); role.className = "source-role";
        role.textContent = s.lecture_ref; row.append(role);
      }
      const meta = document.createElement("span"); meta.className = "source-meta";
      meta.textContent = `${s.chunks} 块`; row.append(meta);
      list.append(row);
    }
    det.append(list); box.append(det);
  }
}

async function showKnowledge(id, navigate = true) {
  const requestVersion = ++knowledgeRequestVersion;
  const requestCourse = courseId;
  const requestView = routeView;
  selectedKnowledgeId = id;
  selectedCompId = null;
  updateLocationHash();
  const item = await api("/api/knowledge_item?course_id=" + encodeURIComponent(courseId)
    + "&id=" + encodeURIComponent(id));
  if (id !== selectedKnowledgeId || requestVersion !== knowledgeRequestVersion
      || courseId !== requestCourse || routeView !== requestView) return;
  if (navigate) {
    routeView = "knowledge"; kView = "catalog"; routeViewUserChosen = true;
    applyRouteView();
  }
  const pane = document.getElementById("detail");
  pane.replaceChildren();
  if (item.kind === 'wiki-block') {
    pane.append(WikiReader.render(item.wiki, blockId => showKnowledge('wiki:' + blockId)));
    return;
  }
  const eyebrow = document.createElement("span"); eyebrow.className = "eyebrow";
  eyebrow.textContent = ({'review-point':'KNOWLEDGE POINT',
    'project-anchor':'PROJECT IMPLEMENTATION',
    'interview-question':'INTERVIEW QUESTION'}[item.kind] || 'SKELETON ANCHOR');
  pane.append(eyebrow);
  const h = document.createElement("h2");
  h.textContent = id.includes("#") ? id.split("#").pop()
    : (knowledgeData?.blocks || []).find(b => b.id === id)?.title || id;
  pane.append(h);
  const block = (knowledgeData?.blocks || []).find(b => b.id === id);
  if (block?.ref) {
    const p = document.createElement("p"); p.className = "muted";
    p.textContent = `对应：${block.ref}`;
    pane.append(p);
  }
  if (block?.note) {
    const p = document.createElement("p"); p.className = "muted";
    p.textContent = block.note; pane.append(p);
  }
  if (item.match === "approximate") {
    const p = document.createElement("p"); p.className = "muted";
    p.textContent = "以下为按符号近似匹配的正文片段（锚点与切分符号未逐一对应时如实标注）。";
    pane.append(p);
  }
  const chunks = item.kind === "review-point"
    ? (item.prepare?.material ? [item.prepare.material] : [])
    : (item.chunks || []);
  for (const c of chunks) {
    const det = document.createElement("details"); det.className = "kn-chunk";
    const sum = document.createElement("summary"); sum.textContent = c.anchor;
    const pre = document.createElement("pre"); pre.textContent = c.text;
    det.append(sum, pre); pane.append(det);
  }
  if (!chunks.length) {
    const p = document.createElement("p"); p.className = "muted";
    p.textContent = "该知识位置暂无可展示的正文片段（未关联不等于缺失，索引行与正文分工见资料清单）。";
    pane.append(p);
  }
  const lh = document.createElement("h3"); lh.textContent = "跨视图关联";
  pane.append(lh);
  if ((item.links || []).length) pane.append(linkButtons(item.links));
  else {
    const p = document.createElement("p"); p.className = "muted";
    p.textContent = "暂无关联。没有自然关联时不强行连接。"; pane.append(p);
  }
  pane.scrollTop = 0;
}

// ------------------------------------------------------ 项目理解（Archify）
function renderCodeMap(map) {
  const box = document.getElementById("code-map");
  if (!box) return;
  box.replaceChildren();
  if (!map) {
    const p = document.createElement("p"); p.className = "focus-empty";
    p.textContent = "本课程暂无已认可的项目架构图。纯课程有教学骨架时，骨架结构在下方「源码导航」中展示；都没有则不生成代码凑图。";
    box.append(p); return;
  }
  const views = map.meta?.views || [];
  if (views.length) {
    const bar = document.createElement("div"); bar.className = "cm-views";
    const all = document.createElement("button"); all.type = "button";
    all.className = "cm-view-btn active"; all.textContent = "全图";
    all.onclick = () => { box.dataset.focus = ""; bar.querySelectorAll(".cm-view-btn").forEach(b => b.classList.remove("active")); all.classList.add("active"); applyCmFocus(box, map); };
    bar.append(all);
    for (const v of views) {
      const b = document.createElement("button"); b.type = "button";
      b.className = "cm-view-btn"; b.textContent = v.label; b.title = v.note || "";
      b.onclick = () => { box.dataset.focus = v.id; bar.querySelectorAll(".cm-view-btn").forEach(x => x.classList.remove("active")); b.classList.add("active"); applyCmFocus(box, map); };
      bar.append(b);
    }
    box.append(bar);
  }
  const stage = document.createElement("div"); stage.className = "cm-stage";
  const comps = map.components || [];
  const maxX = Math.max(...comps.map(c => c.pos[0] + c.size[0]), 1200);
  const maxY = Math.max(...comps.map(c => c.pos[1] + c.size[1]), 650);
  stage.style.height = (maxY + 30) + "px";
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "cm-edges");
  svg.setAttribute("viewBox", `0 0 ${maxX} ${maxY + 30}`);
  const byId = Object.fromEntries(comps.map(c => [c.id, c]));
  for (const e of map.connections || []) {
    const a = byId[e.from], b = byId[e.to];
    if (!a || !b) continue;
    const x1 = a.pos[0] + a.size[0] / 2, y1 = a.pos[1] + a.size[1] / 2;
    const x2 = b.pos[0] + b.size[0] / 2, y2 = b.pos[1] + b.size[1] / 2;
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", x1); line.setAttribute("y1", y1);
    line.setAttribute("x2", x2); line.setAttribute("y2", y2);
    line.setAttribute("class", "cm-edge" + (e.variant === "emphasis" ? " emphasis" : ""));
    line.dataset.from = e.from; line.dataset.to = e.to;
    svg.append(line);
    const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
    text.setAttribute("x", (x1 + x2) / 2); text.setAttribute("y", (y1 + y2) / 2 - 6);
    text.setAttribute("class", "cm-edge-label");
    text.dataset.from = e.from; text.dataset.to = e.to;
    text.textContent = e.label || "";
    svg.append(text);
  }
  stage.append(svg);
  for (const c of comps) {
    const d = document.createElement("button"); d.type = "button";
    d.className = "cm-node"; d.dataset.comp = c.id;
    d.style.left = (c.pos[0] / maxX * 100) + "%";
    d.style.top = c.pos[1] + "px";
    d.style.width = (c.size[0] / maxX * 100) + "%";
    d.style.minHeight = c.size[1] + "px";
    const t = document.createElement("strong"); t.textContent = c.label;
    const s = document.createElement("small"); s.textContent = c.sublabel || "";
    d.append(t, s);
    d.onclick = () => showCodeModule(c.id);
    stage.append(d);
  }
  box.append(stage);
  if (map.response_note) {
    const p = document.createElement("p"); p.className = "muted cm-foot";
    p.textContent = map.response_note; box.append(p);
  }
  for (const card of map.cards || []) {
    const d = document.createElement("div"); d.className = "cm-card dot-" + (card.dot || "cyan");
    const t = document.createElement("strong"); t.textContent = card.title;
    const ul = document.createElement("ul");
    for (const it of card.items || []) {
      const li = document.createElement("li"); li.textContent = it; ul.append(li);
    }
    d.append(t, ul); box.append(d);
  }
  const note = document.createElement("p"); note.className = "section-note";
  note.textContent = "模块职责与关系来自已认可的 Archify 预览（人工核对当前代码）；配置接线与推断关系在节点详情中分别标注。点击节点看职责、输入输出、源码依据与跨视图关联。";
  box.append(note);
  applyCmFocus(box, map);
}

function applyCmFocus(box, map) {
  const view = (map.meta?.views || []).find(v => v.id === box.dataset.focus);
  const focus = view ? new Set(view.focus) : null;
  box.querySelectorAll(".cm-node").forEach(n =>
    n.classList.toggle("dim", focus && !focus.has(n.dataset.comp)));
  box.querySelectorAll(".cm-edge, .cm-edge-label").forEach(el =>
    el.classList.toggle("dim", focus && !(focus.has(el.dataset.from) && focus.has(el.dataset.to))));
}

function showCodeModule(id, navigate = true) {
  const map = codeMapData;
  const c = map?.components?.find(x => x.id === id);
  if (!c) return;
  selectedCompId = id;
  selectedKnowledgeId = null;
  updateLocationHash();
  if (navigate) {
    routeView = "project"; pView = "map"; routeViewUserChosen = true;
    applyRouteView();
  }
  document.querySelectorAll(".cm-node").forEach(n =>
    n.classList.toggle("selected", n.dataset.comp === id));
  const pane = document.getElementById("detail");
  pane.replaceChildren();
  const eyebrow = document.createElement("span"); eyebrow.className = "eyebrow";
  eyebrow.textContent = "CODE MODULE";
  const h = document.createElement("h2"); h.textContent = c.label;
  const sub = document.createElement("p"); sub.className = "muted";
  sub.textContent = c.sublabel || "";
  pane.append(eyebrow, h, sub);
  const d = c.detail || {};
  if (d.basis) {
    const b = document.createElement("span");
    b.className = "basis-badge basis-" + d.basis;
    b.textContent = BASIS_LABEL[d.basis] || d.basis;
    pane.append(b);
  }
  if (d.role) {
    const p = document.createElement("p"); p.className = "cm-role";
    p.textContent = d.role; pane.append(p);
  }
  if (d.io) {
    const io = document.createElement("div"); io.className = "cm-io";
    for (const [k, label] of [["input", "输入"], ["process", "关键处理"], ["output", "输出"]]) {
      if (!d.io[k]) continue;
      const row = document.createElement("p");
      const t = document.createElement("span"); t.className = "pos-label"; t.textContent = label;
      const v = document.createElement("span"); v.textContent = d.io[k];
      row.append(t, v); io.append(row);
    }
    pane.append(io);
  }
  if ((d.files || []).length) {
    const fh = document.createElement("h3"); fh.textContent = "关键源码";
    pane.append(fh);
    const ul = document.createElement("ul"); ul.className = "cm-files";
    for (const f of d.files) {
      const li = document.createElement("li"); li.textContent = f; ul.append(li);
    }
    pane.append(ul);
  }
  if (d.note) {
    const p = document.createElement("p"); p.className = "muted";
    p.textContent = d.note; pane.append(p);
  }
  // 上下游（来自图连线；顺序细节以请求主链步骤说明为准）
  const ups = (map.connections || []).filter(e => e.to === id);
  const downs = (map.connections || []).filter(e => e.from === id);
  if (ups.length || downs.length) {
    const rh = document.createElement("h3"); rh.textContent = "上下游";
    pane.append(rh);
    const wrap = document.createElement("div"); wrap.className = "link-list";
    const byId = Object.fromEntries(map.components.map(x => [x.id, x]));
    for (const e of ups) {
      const b = document.createElement("button"); b.type = "button"; b.className = "link-chip";
      b.textContent = "← " + (byId[e.from]?.label || e.from) + (e.label ? `（${e.label}）` : "");
      b.onclick = () => showCodeModule(e.from); wrap.append(b);
    }
    for (const e of downs) {
      const b = document.createElement("button"); b.type = "button"; b.className = "link-chip";
      b.textContent = "→ " + (byId[e.to]?.label || e.to) + (e.label ? `（${e.label}）` : "");
      b.onclick = () => showCodeModule(e.to); wrap.append(b);
    }
    pane.append(wrap);
  }
  const lh = document.createElement("h3"); lh.textContent = "相关知识、学习位置与主链步骤";
  pane.append(lh);
  if ((c.links || []).length) pane.append(linkButtons(c.links));
  else {
    const p = document.createElement("p"); p.className = "muted";
    p.textContent = "暂无关联。没有自然关联时不强行连接。"; pane.append(p);
  }
  pane.scrollTop = 0;
}

function renderStudyFocus(state, tree) {
  const box = document.getElementById('study-focus');
  box.dataset.sectionId = state.section_id || '';
  box.replaceChildren();
  const labels = {untouched:'待学习',self_reported_understood:'自述理解',explained:'已讲解',question:'有疑问',revisit:'待回补'};
  const stage = {learning:'自由学习中',awaiting_review:'章节测试待主讲确认',passed:'章节已通过',revisit:'针对薄弱点回补'};
  const top = document.createElement('div'); top.className='focus-heading';
  const copy = document.createElement('div');
  const tag = document.createElement('span'); tag.className='eyebrow'; tag.textContent='TEACHING CURSOR · 教学进度';
  const title = document.createElement('h2'); title.textContent=titleForNode(suggestedNodeId) || '准备开始';
  const hint = document.createElement('p'); hint.className='muted';
  hint.textContent=state.workspace?.focus ? `当前学习焦点：${state.workspace.focus}` : '这里由教学 AI 更新；点击下方节点只会浏览内容，不会自动改变学习进度。';
  copy.append(tag,title,hint);
  if (graphData && suggestedNodeId) {
    const unitId = chainUnitOf(suggestedNodeId, graphData);
    const prev = graphData.edges.find(e => e.type === "sequence" && e.dst === unitId);
    const nextU = graphData.edges.find(e => e.type === "sequence" && e.src === unitId);
    if (prev || nextU) {
      const pos = document.createElement('p');
      pos.className = 'muted chain-pos-line';
      pos.textContent = `主链位置：上游 ${prev ? titleForNode(prev.src) : '（起点）'} · 下游 ${nextU ? titleForNode(nextU.dst) : '（终点）'}`;
      copy.appendChild(pos);
    }
  }
  const badge = document.createElement('span'); badge.className='chapter-stage'; badge.textContent=stage[state.workspace?.status] || '准备开始';
  top.append(copy,badge); box.append(top);
  // —— 本次学习树：当前教学范围（计划分段/子问题/追问），替代平铺小点 ——
  if (tree && tree.plan) {
    box.append(renderCurrentTree(state, tree));
    // 小点记录：与全局树同一份整理结果（主题分组 + 归档 + 待归位）
    if (tree.topic_groups) {
      box.append(topicGroupsEl(tree.topic_groups.groups,
        tree.topic_groups.unassigned, "tt-tg:" + courseId, true));
    } else if ((state.topics || []).length) {
      const det = document.createElement('details'); det.className='tt-topics';
      bindTreeToggle(det, 'tt-topics:'+courseId, false);
      const sum = document.createElement('summary');
      const pending = state.topics.filter(t => ['question','revisit'].includes(t.status)).length;
      sum.textContent = `本节学习小点记录 ${state.topics.length} 条` + (pending ? ` · ${pending} 个疑问/待回补` : '') + '（过程记录，不进正式进度）';
      det.append(sum);
      const wrap = document.createElement('div'); wrap.className='tt-topics-body';
      for (const t of state.topics) {
        const chip = document.createElement('span'); chip.className='tt-topic-chip '+t.status;
        chip.textContent = t.title; chip.title = labels[t.status] || t.status;
        wrap.append(chip);
      }
      det.append(wrap); box.append(det);
    }
  } else {
    const hint = document.createElement('p'); hint.className='focus-empty';
    hint.textContent = '尚未建立讲解计划。已有的讲解与问答记录仍在上方保留；建立计划后，这里会显示当前讲解位置与计划进度。';
    box.append(hint);
  }
  const foot=document.createElement('p'); foot.className='focus-foot';
  foot.textContent='看懂就继续 · 疑问随时问 · 章节结束统一测试。自述理解与测试通过分别记录。';box.append(foot);
  if(state.assessment) {
    const p=document.createElement('p'); p.className='assessment-note';
    p.textContent=state.workspace?.status==='passed'?'章节测试：主讲已确认通过。':state.workspace?.status==='revisit'?'章节测试：主讲要求回补。':state.assessment.result==='passed'?'章节测试：答疑教师评定通过，等待主讲确认。':'章节测试：需要回补，按错题定位具体疑问。';box.append(p);
  }
}

async function showNode(id) {
  knowledgeRequestVersion++;
  const version = ++detailVersion;
  const requestedCourse = courseId;
  selectedNodeId = id;
  selectedKnowledgeId = null;
  selectedCompId = null;
  updateLocationHash();
  document.querySelectorAll(".objective-button").forEach(button =>
    button.classList.toggle("selected", button.dataset.nodeId === id));
  updateGraphSelection();
  if (graphData) renderRequestChain(graphData);
  const pane = document.getElementById("detail");
  const detail = await api("/api/node?id=" + encodeURIComponent(id));
  if (version !== detailVersion || requestedCourse !== courseId) return;
  const signature = JSON.stringify([detail, statuses[id]]);
  if (detailSignature === signature) return;
  detailSignature = signature;
  const scrollTop = pane.dataset.nodeId === id ? pane.scrollTop : 0;
  pane.dataset.nodeId = id;
  pane.textContent = "";

  const eyebrow = document.createElement("span");
  eyebrow.className = "eyebrow";
  eyebrow.textContent = detail.node.type === "objective" ? "LEARNING OBJECTIVE" : detail.node.type.toUpperCase();
  pane.appendChild(eyebrow);

  const crumbs = document.createElement("div");
  crumbs.className = "breadcrumbs";
  for (const node of breadcrumbNodes(id)) {
    const span = document.createElement("span");
    span.textContent = node.title;
    crumbs.appendChild(span);
  }
  pane.appendChild(crumbs);

  const heading = document.createElement("h2");
  heading.textContent = detail.node.title;
  pane.appendChild(heading);
  if (detail.published_note) {
    const note = document.createElement('a');
    note.href = '/library.html#node=' + encodeURIComponent(id);
    note.textContent = '阅读正式笔记与关联知识'; note.className = 'chip';
    pane.appendChild(note);
  }
  const status = statuses[id];
  if (status) {
    const badge = document.createElement("span");
    badge.className = `badge ${status.status}`;
    badge.textContent = STATUS_LABEL[status.status] || status.status;
    pane.appendChild(badge);
  }
  const summary = document.createElement("p");
  summary.textContent = detail.node.summary;
  pane.appendChild(summary);

  addTextList(pane, "前置知识", detail.prerequisites.map(item => item.title));
  addChainPosition(pane, id);
  addClaimsList(pane, detail.claims || []);
  if ((detail.links || []).length) {
    const lh = document.createElement("h3"); lh.textContent = "跨视图关联";
    pane.append(lh, linkButtons(detail.links));
  }
  addSourceList(pane, detail.sources);
  const openMisconceptions = detail.misconceptions.filter(item => item.status === "open");
  if (openMisconceptions.length) {
    const notice = document.createElement("div");
    notice.className = "notice";
    notice.textContent = `待澄清：${openMisconceptions.map(item => item.text).join("；")}`;
    pane.appendChild(notice);
  }
  addTextList(pane, "最近活动", detail.recent_events.map(event =>
    `${formatDate(event.ts)} · ${eventLabel(event.type)}`));

  const LESSON_LABEL = {intro: "已保存的首次讲解", clarify: "已保存的答疑讲解",
    review: "已保存的复习串联"};
  for (const mode of ["intro", "clarify", "review"]) {
    const lesson = detail.lesson_artifacts?.[mode];
    if (!lesson) continue;
    const label = document.createElement("h3");
    label.textContent = LESSON_LABEL[mode];
    const content = document.createElement("div");
    content.className = "lesson";
    if (window.WikiReader) content.append(WikiReader.markdown(lesson.content));
    else content.textContent = lesson.content;
    pane.append(label, content);
  }
  pane.scrollTop = scrollTop;
}

function addTextList(pane, title, items) {  if (!items.length) return;
  const heading = document.createElement("h3");
  heading.textContent = title;
  const list = document.createElement("ul");
  for (const item of items.slice(0, 8)) {
    const li = document.createElement("li");
    li.textContent = item;
    list.appendChild(li);
  }
  pane.append(heading, list);
}

function addChainPosition(pane, nodeId) {
  if (!graphData) return;
  const unitId = chainUnitOf(nodeId, graphData);
  if (!unitId) return;
  const prev = graphData.edges.find(e => e.type === "sequence" && e.dst === unitId);
  const next = graphData.edges.find(e => e.type === "sequence" && e.src === unitId);
  if (!prev && !next) return;
  const box = document.createElement("div");
  box.className = "chain-position";
  const mk = (id, label) => {
    if (!id) return null;
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = `${label} ${titleForNode(id)}`;
    b.onclick = () => showNode(id);
    return b;
  };
  const up = mk(prev?.src, "← 上游");
  const down = mk(next?.dst, "下游 →");
  if (up) box.appendChild(up);
  if (down) box.appendChild(down);
  if (box.childNodes.length) {
    const heading = document.createElement("h3");
    heading.textContent = "主链位置";
    pane.append(heading, box);
  }
}

function addClaimsList(pane, claims) {
  if (!claims.length) return;
  const heading = document.createElement("h3");
  heading.textContent = "实现状态（表述 vs 代码核实）";
  pane.appendChild(heading);
  const list = document.createElement("ul");
  list.className = "claims-list";
  for (const claim of claims) {
    const li = document.createElement("li");
    const badge = document.createElement("span");
    badge.className = `claim-badge ${claim.status}`;
    badge.textContent = CLAIM_LABEL[claim.status] || claim.status;
    const text = document.createElement("span");
    text.textContent = claim.text;
    li.append(badge, text);
    if (claim.evidence) {
      const ev = document.createElement("small");
      ev.className = "claim-evidence";
      ev.textContent = claim.evidence;
      li.appendChild(ev);
    }
    list.appendChild(li);
  }
  pane.appendChild(list);
}

function addSourceList(pane, sources) {
  if (!sources.length) return;
  const heading = document.createElement("h3");
  heading.textContent = "关联材料";
  const list = document.createElement("ul");
  for (const source of sources.slice(0, 8)) {
    const li = document.createElement("li");
    if (source.kind === "url") {
      const link = document.createElement("a");
      link.href = source.uri;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = source.title;
      li.appendChild(link);
    } else {
      li.textContent = source.title;
    }
    if (source.lecture_ref) li.append(` · ${source.lecture_ref}`);
    if (source.note === "code") {
      const tag = document.createElement("span");
      tag.className = "src-kind-tag";
      tag.textContent = "源码";
      li.appendChild(tag);
    }
    list.appendChild(li);
    for (const ex of (source.excerpts || []).slice(0, 3)) {
      if (!ex.anchor) continue;
      const item = document.createElement("li");
      item.className = "excerpt-item";
      const anchor = document.createElement("code");
      anchor.className = "excerpt-anchor";
      anchor.textContent = ex.anchor;
      anchor.title = source.uri;
      item.appendChild(anchor);
      const snippet = document.createElement("pre");
      snippet.className = "excerpt-text";
      snippet.textContent = ex.text.length > 600 ? ex.text.slice(0, 600) + " …" : ex.text;
      item.appendChild(snippet);
      list.appendChild(item);
    }
  }
  pane.append(heading, list);
}

function renderSessions(sessions) {
  const body = document.querySelector("#sessions-table tbody");
  body.textContent = "";
  document.getElementById("sessions-empty").style.display = sessions.length ? "none" : "block";
  document.getElementById("sessions-table").style.display = sessions.length ? "table" : "none";
  setText("session-summary", sessions.length ? `最近 ${sessions.length} 次` : "尚无记录");
  for (const session of sessions) {
    const row = document.createElement("tr");
    const target = document.createElement("td");
    target.className = "session-target";
    const current = document.createElement("strong");
    current.textContent = session.current_title || session.root_title;
    const distribution = document.createElement("small");
    distribution.textContent = (session.activity_nodes || []).length
      ? `会话事件归属：${session.activity_nodes.map(item => `${item.title}（${item.count} 条）`).join(" · ")}`
      : `起始目标：${session.root_title}`;
    target.append(current, distribution);
    const values = [
      formatDate(session.started_at),
      MODE_LABEL[session.mode] || session.mode,
      session.status === "active" ? "进行中" : session.status === "finished" ? "已完成" : "已放弃",
      session.event_count, session.summary || "—",
    ];
    values.forEach((value, index) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.appendChild(cell);
      if (index === 0) row.appendChild(target);
    });
    body.appendChild(row);
  }
}

function buildEdgeFilters() {
  const box = document.getElementById("edge-filters");
  for (const type of FILTERABLE_EDGES) {
    const meta = EDGE_META[type];
    const label = document.createElement("label");
    label.title = `${meta.label}：${meta.desc}`;
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = activeEdgeTypes.has(type);
    checkbox.onchange = () => {
      checkbox.checked ? activeEdgeTypes.add(type) : activeEdgeTypes.delete(type);
      drawGraph(graphData);
    };
    const swatch = document.createElement("span");
    swatch.className = `edge-swatch ${type}`;
    const text = document.createElement("span");
    text.textContent = `${meta.label} · ${meta.desc}`;
    label.append(checkbox, swatch, text);
    box.appendChild(label);
  }
}

// ---------------------------------------------------------------------------
// Advanced graph: layered SVG layout + pan/zoom viewport.
// The viewBox is the single source of truth for the camera; it survives the
// 15s refresh because drawGraph() short-circuits when nothing relevant changed.
// ---------------------------------------------------------------------------

function graphBox() {
  const rect = document.getElementById("graph-scroll").getBoundingClientRect();
  // The <details> panel may be collapsed: fall back to a sane aspect so fit
  // math stays finite; the toggle handler refits once the panel opens.
  return { width: rect.width || 1200, height: rect.height || 620 };
}

function graphAspect() {
  const box = graphBox();
  return box.width / box.height;
}

function fitGraphView(layout) {
  const margin = 50;
  const aspect = graphAspect();
  let w = layout.width + margin * 2, h = layout.height + margin * 2;
  if (w / h > aspect) h = w / aspect; else w = h * aspect;
  return { x: layout.width / 2 - w / 2, y: layout.height / 2 - h / 2,
           w, h, auto: true };
}

function applyGraphView() {
  if (!graphView) return;
  // Keep the viewBox aspect locked to the container so event→graph
  // coordinate math stays exact (no preserveAspectRatio letterboxing).
  graphView.h = graphView.w / graphAspect();
  const svg = document.getElementById("graph");
  svg.setAttribute("viewBox",
    `${graphView.x} ${graphView.y} ${graphView.w} ${graphView.h}`);
}

function persistGraphView() {
  if (courseId && graphView) graphViewsByCourse[courseId] = graphView;
}

function graphPointFromEvent(e) {
  const rect = document.getElementById("graph").getBoundingClientRect();
  return {
    x: graphView.x + (e.clientX - rect.left) / rect.width * graphView.w,
    y: graphView.y + (e.clientY - rect.top) / rect.height * graphView.h,
  };
}

function zoomGraphAt(point, factor) {
  if (!graphView || !graphLayoutCache) return;
  const minW = 240;
  const maxW = (graphLayoutCache.width + 400) * 2.5;
  const w = Math.min(maxW, Math.max(minW, graphView.w * factor));
  const real = w / graphView.w;
  graphView = {
    x: point.x - (point.x - graphView.x) * real,
    y: point.y - (point.y - graphView.y) * real,
    w, h: w / graphAspect(), auto: false,
  };
  persistGraphView();
  applyGraphView();
}

function centerGraphOn(nodeId, viewW = 1150) {
  const point = graphLayoutCache?.positions[nodeId];
  if (!point) return false;
  const w = Math.min(viewW, graphLayoutCache.width + 200);
  graphView = { x: point.x - w / 2, y: point.y - w / graphAspect() / 2,
                w, h: w / graphAspect(), auto: false };
  persistGraphView();
  applyGraphView();
  return true;
}

function toggleUnitExpanded(unitId) {
  const set = (expandedUnitsByCourse[courseId] ||= new Set());
  set.has(unitId) ? set.delete(unitId) : set.add(unitId);
  drawGraph(graphData);
}

function updateGraphSelection() {  document.querySelectorAll("#graph .node").forEach(g => {
    g.classList.toggle("selected", g.dataset.nodeId === selectedNodeId);
    g.classList.toggle("teaching", g.dataset.nodeId === suggestedNodeId);
  });
  const chip = document.getElementById("graph-selection");
  if (!chip) return;
  if (selectedNodeId) {
    chip.hidden = false;
    document.getElementById("graph-selection-title").textContent =
      titleForNode(selectedNodeId) || selectedNodeId;
  } else {
    chip.hidden = true;
  }
}

function buildGraphControls() {
  const scroll = document.getElementById("graph-scroll");
  document.getElementById("graph-zoom-in").onclick = () => {
    if (graphView) zoomGraphAt(
      {x: graphView.x + graphView.w / 2, y: graphView.y + graphView.h / 2},
      1 / 1.4);
  };
  document.getElementById("graph-zoom-out").onclick = () => {
    if (graphView) zoomGraphAt(
      {x: graphView.x + graphView.w / 2, y: graphView.y + graphView.h / 2},
      1.4);
  };
  document.getElementById("graph-fit").onclick = () => {
    if (!graphLayoutCache) return;
    graphView = fitGraphView(graphLayoutCache);
    persistGraphView();
    applyGraphView();
  };
  document.getElementById("graph-locate").onclick = () => {
    if (suggestedNodeId && centerGraphOn(suggestedNodeId)) {
      showNode(suggestedNodeId);
    }
  };
  document.getElementById("graph-goto-detail").onclick = () => {
    document.getElementById("detail")
      .scrollIntoView({behavior: "smooth", block: "start"});
  };

  let drag = null;
  scroll.addEventListener("pointerdown", e => {
    if (!graphView) return;
    // Remember what was pressed: once the container captures the pointer,
    // pointerup is retargeted to it and e.target no longer helps.
    drag = {x: e.clientX, y: e.clientY, moved: false,
            node: e.target.closest(".node"),
            expander: e.target.closest(".unit-expander")};
    scroll.setPointerCapture(e.pointerId);
  });
  scroll.addEventListener("pointermove", e => {
    if (!drag || !graphView) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (!drag.moved && Math.hypot(dx, dy) < 5) return;
    drag.moved = true;
    scroll.classList.add("dragging");
    const rect = scroll.getBoundingClientRect();
    graphView.x -= dx * graphView.w / rect.width;
    graphView.y -= dy * graphView.h / rect.height;
    drag.x = e.clientX;
    drag.y = e.clientY;
    graphView.auto = false;
    persistGraphView();
    applyGraphView();
  });
  const finishDrag = e => {
    const wasDrag = drag?.moved;
    const node = drag?.node;
    const expander = drag?.expander;
    drag = null;
    scroll.classList.remove("dragging");
    if (wasDrag) return;
    if (expander) {
      toggleUnitExpanded(expander.dataset.nodeId);
    } else if (node) {
      showNode(node.dataset.nodeId);
    }
  };
  scroll.addEventListener("pointerup", finishDrag);
  scroll.addEventListener("pointercancel", () => {
    drag = null;
    scroll.classList.remove("dragging");
  });
  scroll.addEventListener("wheel", e => {
    if (!graphView) return;
    e.preventDefault();
    zoomGraphAt(graphPointFromEvent(e), e.deltaY > 0 ? 1.18 : 1 / 1.18);
  }, {passive: false});

  // Refit an untouched (auto) view when the graph tab opens or the window resizes.
  document.querySelectorAll(".k-view-tab").forEach(tab => {
    tab.addEventListener("click", () => {
      if (tab.dataset.view === "graph" && graphView?.auto && graphLayoutCache) {
        graphView = fitGraphView(graphLayoutCache);
        persistGraphView();
        applyGraphView();
      }
    });
  });
  let resizeTimer = null;
  window.addEventListener("resize", () => {
    if (!graphView?.auto || !graphLayoutCache) return;
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      graphView = fitGraphView(graphLayoutCache);
      persistGraphView();
      applyGraphView();
    }, 180);
  });
}

const SVGNS = "http://www.w3.org/2000/svg";
function svgElement(tag, attrs) {
  const element = document.createElementNS(SVGNS, tag);
  for (const key in attrs) element.setAttribute(key, attrs[key]);
  return element;
}

// Layered layout: course on top, modules as labeled boxes, units side by side
// inside their module box (主链顺序), boxes wrap into rows like text. The row
// width target is chosen so the canvas aspect matches the viewer, which keeps
// 适配全图 readable. Objectives only appear for expanded units (层级折叠).
function graphLayout(nodes, edges, targetAspect = 1.9) {
  const nodeById = Object.fromEntries(nodes.map(n => [n.id, n]));
  const children = childrenByParent(edges);
  const course = nodes.find(node => node.type === "course") || nodes[0];
  const expanded = new Set(expandedUnitsByCourse[course.id] || []);
  const teachingUnit = chainUnitOf(suggestedNodeId, {nodes, edges});
  if (teachingUnit) expanded.add(teachingUnit);

  // Units of one module in chain order (sequence edges first, sort_order as
  // fallback / tie-break), same rule as the route view.
  const unitsInOrder = (module) => {
    const units = sorted((children[module.id] || [])
      .map(id => nodeById[id]).filter(n => n?.type === "unit"));
    const nextOf = {}, prevOf = {};
    for (const e of edges) {
      if (e.type !== "sequence") continue;
      if (units.some(u => u.id === e.src) && units.some(u => u.id === e.dst)) {
        nextOf[e.src] = e.dst;
        prevOf[e.dst] = e.src;
      }
    }
    const out = [];
    const seen = new Set();
    for (const head of units.filter(u => !prevOf[u.id])) {
      let cur = head;
      while (cur && !seen.has(cur.id)) {
        seen.add(cur.id);
        out.push(cur);
        cur = nodeById[nextOf[cur.id]];
      }
    }
    out.push(...units.filter(u => !seen.has(u.id)));
    return out;
  };

  const objectivesOf = (unit) => sorted((children[unit.id] || [])
    .map(id => nodeById[id]).filter(n => n?.type === "objective"));

  const UNIT_W = 250, UNIT_H = 66, OBJ_GAP_Y = 12, OBJ_H = 52;
  const boxes = [];
  for (const module of modulesOf(children, nodeById, course)) {
    const cols = unitsInOrder(module).map(unit => ({
      unit,
      objs: expanded.has(unit.id) ? objectivesOf(unit) : [],
      objCount: objectivesOf(unit).length,
    }));
    if (!cols.length) continue;
    const innerW = cols.length * UNIT_W + (cols.length - 1) * 46;
    const colH = col => UNIT_H +
      (col.objs.length ? OBJ_GAP_Y * 1.5 + col.objs.length * (OBJ_H + OBJ_GAP_Y) : 0);
    boxes.push({
      module, cols,
      w: innerW + 2 * 28,
      h: 52 + Math.max(...cols.map(colH)) + 26,
    });
  }

  // Pick the row-width target whose resulting canvas aspect is closest to the
  // viewer's, so 适配全图 wastes as little screen as possible.
  let best = null;
  for (const targetW of [900, 1150, 1400, 1650, 1950, 2300, 2700, 3200]) {
    const result = arrangeBoxes(boxes, targetW, nodes, edges, nodeById, course);
    const score = Math.abs(Math.log((result.width / result.height) / targetAspect));
    if (!best || score < best.score) best = {result, score};
  }
  return best.result;
}

function modulesOf(children, nodeById, course) {
  return sorted((children[course.id] || [])
    .map(id => nodeById[id]).filter(n => n?.type === "module"));
}

function arrangeBoxes(boxes, targetRowW, nodes, edges, nodeById, course) {
  const UNIT_W = 250, UNIT_H = 66, OBJ_GAP_Y = 12, OBJ_H = 52;
  const BOX_GAP_X = 70, ROW_GAP = 80;

  const rows = [];
  let row = [], rowW = 0;
  for (const box of boxes) {
    const addW = (row.length ? BOX_GAP_X : 0) + box.w;
    if (row.length && rowW + addW > targetRowW) {
      rows.push({boxes: row, w: rowW});
      row = [];
      rowW = 0;
    }
    row.push(box);
    rowW += (row.length > 1 ? BOX_GAP_X : 0) + box.w;
  }
  if (row.length) rows.push({boxes: row, w: rowW});

  const positions = {};
  const width = Math.max(760, ...rows.map(r => r.w)) + 60;
  positions[course.id] = {x: width / 2, y: 72, w: 400, h: 64};

  let y = 168;
  for (const r of rows) {
    const rowH = Math.max(...r.boxes.map(b => b.h));
    let x = (width - r.w) / 2;
    for (const box of r.boxes) {
      positions[box.module.id] = {x: x + box.w / 2, y: y + box.h / 2,
        w: box.w, h: box.h, box: true};
      let ux = x + 28 + UNIT_W / 2;
      for (const col of box.cols) {
        positions[col.unit.id] = {x: ux, y: y + 52 + UNIT_H / 2,
          w: UNIT_W, h: UNIT_H, objCount: col.objCount,
          expanded: col.objs.length > 0};
        let oy = y + 52 + UNIT_H + OBJ_GAP_Y * 1.5 + OBJ_H / 2;
        for (const obj of col.objs) {
          positions[obj.id] = {x: ux, y: oy, w: 250, h: OBJ_H};
          oy += OBJ_H + OBJ_GAP_Y;
        }
        ux += UNIT_W + 46;
      }
      x += box.w + BOX_GAP_X;
    }
    y += rowH + ROW_GAP;
  }

  // Nodes outside the hierarchy land in a bottom grid. Objectives of a known
  // unit are NOT leftovers — they are hidden by the collapse toggle.
  const placed = new Set(Object.keys(positions));
  const parentOf = {};
  for (const e of edges) if (e.type === "part_of") parentOf[e.src] = e.dst;
  const unitIds = new Set(nodes.filter(n => n.type === "unit").map(n => n.id));
  const leftovers = sorted(nodes.filter(node => {
    if (placed.has(node.id)) return false;
    if (node.type === "objective" && unitIds.has(parentOf[node.id])) {
      return false;
    }
    return true;
  }));
  let lx = 0, ly = y + 20;
  leftovers.forEach((node, index) => {
    if (index && index % 4 === 0) { lx = 0; ly += 78; }
    positions[node.id] = {x: 190 + lx, y: ly, w: 280, h: 54};
    lx += 310;
  });
  const height = Math.max(420, y + (leftovers.length ? 110 : 10));
  return {positions, width, height};
}

function drawGraph(graph) {
  const svg = document.getElementById("graph");
  if (!graph) {
    svg.textContent = "";
    graphRenderKey = null;
    graphLayoutCache = null;
    return;
  }
  const layout = graphLayout(graph.nodes, graph.edges, graphAspect());
  graphLayoutCache = layout;
  const key = JSON.stringify([
    graph.course_id,
    [...activeEdgeTypes].sort(),
    [...(expandedUnitsByCourse[graph.course_id] || [])].sort(),
    graph.nodes.map(n => n.id).join("|"),
    graph.edges.map(e => `${e.src}>${e.dst}:${e.type}`).sort().join("|"),
    statuses,
    suggestedNodeId,
  ]);
  if (key === graphRenderKey) {
    // Nothing structural changed (e.g. a 15s background refresh): keep the
    // camera exactly where the user left it, only refresh selection rings.
    updateGraphSelection();
    return;
  }
  graphRenderKey = key;
  svg.textContent = "";
  const nodeById = Object.fromEntries(graph.nodes.map(n => [n.id, n]));
  const childMap = childrenByParent(graph.edges);

  const defs = svgElement("defs", {});
  const glow = svgElement("filter", {id: "node-glow", x: "-30%", y: "-40%", width: "160%", height: "180%"});
  glow.appendChild(svgElement("feDropShadow", {dx: 0, dy: 0, stdDeviation: 5,
    "flood-color": "#5e9cf5", "flood-opacity": .42}));
  defs.appendChild(glow);
  const edgeColors = {
    part_of: "#7890aa", sequence: "#48c7d9", prerequisite: "#8d7cf6",
    explains: "#6ea8fe", contrasts_with: "#f0b45d", tested_by: "#ef7185",
    fails_as: "#e86c65",
  };
  for (const type of EDGE_TYPES) {
    const marker = svgElement("marker", {id: `arrow-${type}`, viewBox: "0 0 10 10",
      refX: 9, refY: 5, markerWidth: 6, markerHeight: 6, orient: "auto-start-reverse"});
    marker.appendChild(svgElement("path", {d: "M0,0 L10,5 L0,10 z",
      fill: edgeColors[type] || "#7890aa"}));
    defs.appendChild(marker);
  }
  svg.appendChild(defs);

  for (const edge of graph.edges) {
    if (!activeEdgeTypes.has(edge.type)) continue;
    // part_of is expressed by enclosure (module boxes, objective columns),
    // not by arrows.
    if (edge.type === "part_of") continue;
    const source = layout.positions[edge.src];
    const target = layout.positions[edge.dst];
    if (!source || !target) continue;
    const line = svgElement("path", {d: curvedEdge(source, target),
      class: `edge ${edge.type}`, "marker-end": `url(#arrow-${edge.type})`});
    const title = svgElement("title", {});
    const meta = EDGE_META[edge.type] || {label: edge.type, desc: ""};
    title.textContent = `${meta.label}（${meta.desc}）：${nodeById[edge.src]?.title || edge.src} → ${nodeById[edge.dst]?.title || edge.dst}`;
    line.appendChild(title);
    svg.appendChild(line);
  }

  for (const node of graph.nodes) {
    const point = layout.positions[node.id];
    if (!point) continue;  // collapsed objective
    const group = svgElement("g", {class: `node ${node.type}${node.id === suggestedNodeId ? " teaching" : ""}`,
      transform: `translate(${point.x},${point.y})`, "data-node-id": node.id});
    const tip = svgElement("title", {});
    tip.textContent = `${TYPE_LABEL[node.type] || node.type} · ${node.title}`;
    group.appendChild(tip);
    const status = node.type === "objective" ? nodeStatus(node.id) : "none";
    group.appendChild(svgElement("rect", {x: -point.w / 2, y: -point.h / 2,
      width: point.w, height: point.h, rx: node.type === "objective" ? 10 : 13}));
    if (node.type === "objective") {
      group.appendChild(svgElement("circle", {cx: -point.w / 2 + 14, cy: 0, r: 4.5,
        fill: STATUS_COLOR[status]}));
    }
    if (node.type === "module") {
      // The module node IS the container box: label sits in its header strip.
      const meta = svgElement("text", {class: "node-meta",
        x: -point.w / 2 + 14, y: -point.h / 2 + 15});
      const unitCount = (childMap[node.id] || [])
        .filter(id => nodeById[id]?.type === "unit").length;
      meta.textContent = `模块 · ${unitCount} 章节`;
      group.appendChild(meta);
      const text = svgElement("text", {class: "node-title",
        x: -point.w / 2 + 14, y: -point.h / 2 + 36});
      text.textContent = truncateTitle(node.title, Math.floor((point.w - 28) / 12.5));
      group.appendChild(text);
      svg.appendChild(group);
      continue;
    }
    const meta = svgElement("text", {class: "node-meta", x: -point.w / 2 + 16,
      y: -point.h / 2 + 16});
    meta.textContent = node.type === "objective" ? STATUS_LABEL[status] : (TYPE_LABEL[node.type] || node.type.toUpperCase());
    group.appendChild(meta);
    const text = svgElement("text", {class: "node-title", "text-anchor": "middle"});
    const maxUnits = node.type === "course" ? 30 : 18;
    const lines = wrapTitle(node.title, maxUnits);
    lines.forEach((line, index) => {
      const baseY = node.type === "objective" ? 8 : 6;
      const span = svgElement("tspan", {x: node.type === "objective" ? 7 : 0,
        y: lines.length === 1 ? baseY : baseY - 7 + index * 14});
      span.textContent = line;
      text.appendChild(span);
    });
    group.appendChild(text);
    if (node.type === "unit" && point.objCount > 0) {
      // Bottom strip toggles the objective list for this unit.
      const exp = svgElement("g", {class: "unit-expander",
        "data-node-id": node.id});
      const stripH = 20;
      exp.appendChild(svgElement("rect", {x: -point.w / 2 + 6,
        y: point.h / 2 - stripH - 5, width: point.w - 12, height: stripH, rx: 6}));
      const done = (childMap[node.id] || [])
        .filter(id => nodeById[id]?.type === "objective" &&
          nodeStatus(id) === "demonstrated").length;
      const label = svgElement("text", {x: 0,
        y: point.h / 2 - 10, "text-anchor": "middle"});
      label.textContent =
        `${point.expanded ? "▾" : "▸"} ${done}/${point.objCount} 目标`;
      exp.appendChild(label);
      const expTip = svgElement("title", {});
      expTip.textContent = point.expanded ? "收起知识目标" : "展开知识目标";
      exp.appendChild(expTip);
      group.appendChild(exp);
    }
    svg.appendChild(group);
  }

  // Restore this course's camera (kept across refreshes and course switches),
  // or fit the whole graph on first view.
  graphView = graphViewsByCourse[graph.course_id] || fitGraphView(layout);
  applyGraphView();
  updateGraphSelection();
}

function curvedEdge(source, target) {
  const dx = target.x - source.x;
  const dy = target.y - source.y;
  if (Math.abs(dy) >= Math.abs(dx) * .55) {
    const direction = Math.sign(dy) || 1;
    const startY = source.y + direction * source.h / 2;
    const endY = target.y - direction * target.h / 2;
    const bend = (endY - startY) * .48;
    return `M ${source.x} ${startY} C ${source.x} ${startY + bend}, ${target.x} ${endY - bend}, ${target.x} ${endY}`;
  }
  const direction = Math.sign(dx) || 1;
  const startX = source.x + direction * source.w / 2;
  const endX = target.x - direction * target.w / 2;
  const bend = (endX - startX) * .48;
  return `M ${startX} ${source.y} C ${startX + bend} ${source.y}, ${endX - bend} ${target.y}, ${endX} ${target.y}`;
}

function childrenByParent(edges) {
  const result = {};
  for (const edge of edges) {
    if (edge.type === "part_of") (result[edge.dst] ||= []).push(edge.src);
  }
  return result;
}

function breadcrumbNodes(id) {
  if (!graphData) return [];
  const nodeById = Object.fromEntries(graphData.nodes.map(node => [node.id, node]));
  const parentOf = {};
  for (const edge of graphData.edges) if (edge.type === "part_of") parentOf[edge.src] = edge.dst;
  const result = [];
  let current = id;
  while (current && nodeById[current]) {
    result.unshift(nodeById[current]);
    current = parentOf[current];
  }
  return result.slice(1, -1);
}

function firstObjective(graph) {
  return sorted(graph.nodes.filter(node => node.type === "objective"))[0]?.id || null;
}
function nodeStatus(id) { return statuses[id]?.status || "untouched"; }
function sorted(nodes) { return [...nodes].sort((a, b) => a.sort_order - b.sort_order || a.title.localeCompare(b.title)); }
function setText(id, value) { document.getElementById(id).textContent = value; }
function titleForNode(id) { return graphData?.nodes.find(node => node.id === id)?.title || ""; }
function actionTitle(kind) {
  return ({intro: "开始第一个学习目标", review: "开始今日复习", resume_session: "继续上次学习", done: "课程目标已完成",
    no_objectives: "资料已登记，暂无课程目标"})[kind] || "查看学习建议";
}
function humanizeNext(next) {
  if (!next) return "教学 AI 产生学习记录后，这里会给出下一步。";
  if (next.kind === "intro") return "尚无学习证据，建议从课程主链的第一个目标开始。";
  if (next.kind === "review") return "已有节点到期或尚未稳定掌握，建议先完成一次回忆测试。";
  if (next.kind === "done") return "当前目标均已验证掌握，继续按复习周期巩固。";
  if (next.kind === "no_objectives") return "该课程是资料型课程，没有知识目标；下方是已登记的资料，复习流启用后从这里出题。";
  return next.message || "";
}
function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", {hour12: false});
}
function eventLabel(type) {
  return ({attempt: "理解检查", source_coverage: "学习材料", checkpoint: "会话节点", note: "学习笔记"})[type] || type;
}
// Width-aware wrap: CJK glyphs count ~1 unit, latin ~0.56. Breaks at spaces
// or punctuation when possible, hard-breaks otherwise; max two lines, the
// second one gets an ellipsis when content remains.
function charUnits(ch) {
  return /[⺀-鿿豈-﫿　-〿]/.test(ch) ? 1 : 0.56;
}
function textUnits(s) {
  return [...s].reduce((sum, ch) => sum + charUnits(ch), 0);
}
function wrapTitle(title, maxUnits) {
  if (textUnits(title) <= maxUnits) return [title];
  const lines = [];
  let cur = "", curW = 0, breakAt = -1;
  for (const ch of title) {
    if (curW + charUnits(ch) > maxUnits && cur) {
      if (breakAt > 2 && lines.length === 0) {
        lines.push(cur.slice(0, breakAt));
        cur = cur.slice(breakAt).trimStart();
        curW = textUnits(cur);
      } else {
        lines.push(cur);
        cur = "";
        curW = 0;
      }
      breakAt = -1;
      if (lines.length === 2) break;
    }
    cur += ch;
    curW += charUnits(ch);
    if (/\s/.test(ch) || /[-·/:：]/.test(ch)) breakAt = cur.length;
  }
  if (lines.length === 2) {
    let second = lines[1];
    while (second && textUnits(second) > maxUnits - 1) {
      second = second.slice(0, -1);
    }
    lines[1] = second.replace(/[\s\-·/:：]+$/, "") + "…";
    return lines;
  }
  if (cur) lines.push(cur);
  return lines;
}
function truncateTitle(title, maxUnits) {
  if (textUnits(title) <= maxUnits) return title;
  let out = "", width = 0;
  for (const ch of title) {
    if (width + charUnits(ch) > maxUnits - 1) break;
    out += ch;
    width += charUnits(ch);
  }
  return out.replace(/\s+$/, "") + "…";
}

init().catch(error => {
  const message = document.createElement("p");
  message.style.cssText = "max-width:900px;margin:40px auto;color:#b42318";
  message.textContent = "Dashboard error: " + error.message;
  document.body.appendChild(message);
});
