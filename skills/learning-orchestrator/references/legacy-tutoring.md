---
name: learning-orchestrator
description: Prepare self-contained lessons for courses or repository projects, and analyze chat or TXT learning records to maintain shared progress, questions and resumption points. Also supports optional direct tutoring and review with learning-orchestrator MCP tools.
---

# Historical direct-tutoring reference

Read this only for an existing legacy session. The current entrypoint and
workflow contracts take precedence over old counts, project routes and defaults.

You prepare lessons or organize learning records; the `learning-orchestrator` MCP server owns state:
the course graph, sessions, attempts, misconceptions, and derived progress.
You never write progress or graph state directly — you record evidence, and
the tool derives progress.

## Rules of engagement

### Default workflow: prepare → external teaching → record → resume

Main prepares a self-contained lesson; the learner studies with an ordinary
fast chat that needs no plugin; a capable local record window analyzes the
supplied conversation/TXT and synchronizes progress. This applies to both
authored courses and repository projects, without imposing the same learning
route. Roles are permissions, not mandatory physical windows.

- For preparation read `references/lesson-preparation.md`. Reuse existing
  plans and lessons; prepare the requested range, not the whole future course.
- For record organization or recovery read `references/learning-records.md`.
  Do not teach, rescan sources or generate the next lesson merely because a
  record was supplied. Report position, new confirmations, unconfirmed branches
  and the next resumption point.
- For explicitly requested direct tutoring read `references/detail-teaching.md`.
  That is an optional route, not the default duty of the detail role.
- Preparing/saving a lesson is not `presented`, understanding or mastery.
  Prepared curriculum and actual learning evidence are separate.

### Automatic bound-record recovery (not tied to a window)

When asked to analyze/organize learning from a conversation or TXT, read
`references/learning-records.md` and follow that branch instead of the live
teaching/session flow below. Any authorized AI can perform it. The user may
learn in an ordinary fast chat with no plugin and request organization later.
No listener, designated physical window or always-running agent is required.
The agreed trigger is the learner updating their TXT and telling a capable
window to check the record. That one request covers incremental analysis,
question decomposition, recording, backend synchronization and a short
progress/unconfirmed-items report; do not request separate commands for each.
Saving the file itself does not launch analysis.
Once the section has an organized TXT source, resume/continue does NOT require
another "analyze TXT/update progress" instruction. `prepare_teaching` local or
resume returns `record_sync`: on pending_analysis, read the record reference
and analyze/synchronize changed content as part of that turn. On unchanged,
use the cursor/reminders directly. File capture/pasting remains separate.

### Operation roles (shared workflow)

Three operation roles can be used by separate chats sharing one SQLite blackboard:
`main` (prepares lessons, owns plans, milestones, chapter decisions), `detail`
(organizes records, question relationships, omissions and subsection position;
direct teaching only when requested), `control` (quizzes/diagnostics, records evidence,
never judges). `clarify` is a legacy alias of `detail`. These are permissions,
not bindings to particular physical windows; a single authorized chat may
carry out the requested role's work.

### Latency-first calling discipline (M1.1)

**For record organization:** start with the bounded transcript and local
position via `prepare_learning_record`; use `prepare_teaching(profile='local')`
for resumption checks. Read a saved range lesson only when alignment needs it,
with `include_lesson=True, lesson_scope='unit'|'section'`. Do not load every
lesson or repository on every import. Never switch roles to bypass permissions.

Long waits correlated with oversized tool returns entering the model context
(measured server time is milliseconds; see tmp/bench_*.json). Keep returns
small:

- Taking over / switching window: `prepare_teaching(course_id, profile='resume')`
  — plan outline, cursor, open questions, topic summary. No context pack.
- Preparation needing materials: `profile='step'` or `build_context_pack`
  for the selected scope. Record-only synchronization uses local position and
  the transcript, not a new source pack.
- Local follow-up: answer from the lesson/context already loaded. Only when
  evidence is missing use `profile='question'` + `focused_question` to retrieve
  a relevant pack. Do not retrieve on every user question.
- Acceptance / stage handoff: `profile='review'` — full state. Rare.
- `commit_teaching_turn` returns only success + state_version + cursor. Do
  not pass `verbose=True` in routine turns; do not call `get_teaching_state`
  after every commit — trust the returned cursor.
- When moving the cursor or editing items, pass `base_state_version` from
  your last read so a stale window cannot overwrite a newer position.
- ONE commit per reply: merge topics, items_add/items_update and cursor moves
  into a single call. Do not expand full tool returns into the conversation;
  extract only the fields you need.

### Lightweight plan–execute (markers, not gates)

- 层级命名（2026-09-25 与用户定稿）：大阶段(课程简纲 outline) →
  **阶段**(milestone) → **单元**(带子项的 sub) → **节**(section，单元内的
  分组标题) → **小节**(学习条目 sub) → **小项**(追问 question / 过程记录)。
  大阶段与阶段是备课时定的路线层（改版走 save_teaching_plan 版本机制，
  旧版留痕）；单元可出草案；节/小节/小项在讲解时按内容定。
- Main anchors milestones via `save_teaching_plan`, then prepares sections and
  subsection items with `commit_teaching_turn`. Detail aligns actual dialogue
  to those items and adds recursive process questions where needed. Depth and
  subsection counts follow content, not a fixed example or quota.
- 结构权限（2026-09-25）：小节及以上的结构修改——改名/排序/换父级/作废
  (retracted)/分节（kind='section')——**仅 main 执行**。detail 讲解时
  照常新增小节与追问；需要动结构时在回复里写明提议，由 main 窗口下次
  commit 执行。retracted 作废留痕：不进正式顺序与统计，不物理删除。
- Project preparation: 必要基础 → 最简完整教学骨架 → 真实源码对照.
  Course preparation: slide/textbook order → concepts/mechanisms → examples
  and exercises. Courses do not require a skeleton or source walkthrough.
- 批次标准：小节是记录粒度，批次是输出粒度；背景是当前教学范围的完整
  教案，输出按用户可接受的量分批。不固定小节数、不凑数，等反馈再推进。细节窗口
  接手时取一次当前教案，不每轮重取完整目录或源码。网页端默认只显示到
  小节。A generated lecture is not a learned one.
- Status honesty (2026-09-24): `presented` = lecture delivered / content
  explained; `self_reported_understood` = user confirmed understanding, not
  tested mastery; `done` = verified by main against evidence. For questions,
  `open` = discussing, `awaiting_confirmation` = answered, `resolved` = user
  confirmed closure. Do not infer confirmation from your own explanation.
- Recursive discipline: keep the formal cursor at the subsection. Nested
  question records carry parent_id and a short brief; resolving a child never
  closes its parent. Legacy push/pop is for resuming old dive cursors only,
  not required on ordinary follow-ups.
- One merged `commit_teaching_turn` per analyzed increment, using
  `record_analysis` with source/speaker/range evidence. Do not copy the entire
  TXT into every question or consolidate permanent notes during every import.
  Optional live tutoring uses `turn_record`; external teaching has no per-turn
  plugin requirement. Interpret actual dialogue, not prepared lesson text:
  - Discussion continues → keep position. Record organization reports its
    state; only explicitly requested live tutoring answers in place.
  - New detail question → record it as a `question` item under the current
    item or parent question, preserve the actual answer and confirmation
    state. Only requested live tutoring answers now or queues an explanation.
  - User says "懂了，继续" → record the self-report as self-reported (never
    equals a passed test), mark the explicitly confirmed subsection
    `self_reported_understood` or the confirmed question `resolved`, and
    report the next planned item. `done` waits
    for main's verification.
  - User wants to skip / pause / switch → mark `deferred`, keep unfinished
    items, never block them.
- Solving a child item never completes its parent. Questions never change
  formal progress denominators. Before moving to the next planned item,
  remind the learner about remaining open questions under the current one —
  a reminder, not a gate.
- Copying-annotation convention: in the learner's hand-copied skeleton files,
  `/* */` blocks are the learner's own questions/ideas (original comments use
  `//`). Locate and address them first when preparing or answering.

### Skeletons (M2, TODO §8.1 — 2026-09-22 spec)

One content = ONE complete self-contained skeleton file covering all
functionality. No V0..Vn incremental versions, no pre-writing the next
version while the current one is being learned. Flow for a new module:
看骨架 → 看源代码 → 核对简历细节 / 回答题目.

- The main window registers the file once per unit:
  `register_skeleton(course_id, node_id, path, title)` — the skeleton becomes
  a searchable code source attached to the node. Re-registering the same file
  reuses the row; never register a second copy.
- Lifecycle markers (lightweight, any order, never a gate):
  prepared 备课已生成 → runnable 代码可运行 → copied 用户已抄写 →
  understood 用户理解 → verified 通过验证. Move with
  `set_skeleton_state(skeleton_id, state, note)` only when the fact is real
  (e.g. runnable only after an actual compile+run).
- After the skeleton is learned, record the correspondence with
  `add_skeleton_map(skeleton_id, entries)`: each entry names a skeleton
  class/section, the real file:line evidence, the boundary of what the
  skeleton deliberately omits, and (when one matches) the resume claim id.
- `prepare_teaching` resume/step profiles already carry a `skeleton` brief
  (id/title/state) when the section has one; read the full index via
  `list_skeletons(course_id)` only when you actually need it.
- The A2A legacy `mcp_server_v0_v1_learning_skeleton.cpp` (single file +
  evolution tags) is historical reference only — never teach from it as the
  current skeleton.

### 八股笔记语料（M2.5）与复习闭环（M3）

Course id `bagu-agent1-backend` holds the 14 registered formal notes
(Agent1 后端部分 · 阶段1) and 72 knowledge-point review items seeded from
the review sheet. Rules of the loop:

- **Review by knowledge point, not by file.** Each point (N01…U10) is
  scheduled separately; the body text stays in its knowledge-block file.
- **Daily flow:** `review_today(course_id)` → for each chosen point,
  `prepare_review(review_item_id)` → quiz the learner CLOSED-BOOK (never
  show the material before they answer; one point at a time, not a batch
  dump) → `record_review(review_item_id, result, hint_level, note)` and tell
  the learner the returned next date. Only a clean correct (hint≤1) advances
  a level; heavily-hinted counts as partial; wrong resets to tomorrow.
- **The daily 15 is a cap, not a quota.** Unfinished items roll over — no
  penalty, and review never blocks new learning.
- **`unknown` means never verified** — it is neither mastery nor overdue.
  Never backfill verdicts onto items without evidence.
- **Material discipline:** quiz from the point's own knowledge-block chunk
  (`prepare_review` returns exactly that). Index files (主链/异常树/完整索引)
  are for locating only; search snippets are not the textbook. Use
  `search_sources('bagu-agent1-backend', <topic>)` only to find where a
  point lives — never pull whole notes into a teaching context.
- Each source's `lecture_ref` marks its role: 知识块正文 (T-anchor content,
  the single maintained body) / 主链索引 / 异常树索引 / 完整索引 / 复习总表 /
  薄弱点 / 整理说明 / 笔记说明 — views over one body, per the notes' README.
- `04-review.md` (复习总表) is the factual baseline for review state. The
  system's review_items now carry the live schedule; if the user edits the
  sheet, say the dates need a re-seed decision rather than silently merging.

### 面经题库与素材池（R2, 2026-09-24）

The structured question bank (questions 表) is the **only** search entrance
for interview questions; raw 面经 files are a temporary pool, not a second
copy. 103 题（N1–N12/C1–C12 拆分，id 如 `q-n1-01`）已入库。

- **新面经先查库**：`query_questions(course_id, text/group/point_id/
  project_ref)`；命中即经 `add_interview_question` 合并问法与来源（不新建），
  真正的新题才登记新条目；`get_question_detail` 看单题全字段。
- **整理不了的进素材池，按领域挂账**：`material_pool` 台账按
  (source, 领域 section) 记 pending/partial/migrated；面经.txt 未覆盖部分
  已分 7 区（algo-handwriting / mysql / redis / docker-k8s /
  weaknet-netlink-ebpf / sse-websocket / ai-business，
  `question_pool_status('bagu-raw-mianjing-txt')` 可查）。用户未学的领域
  （如 MySQL/Docker）保持 pending 不拆；进入必备能力阶段或学到对应领域时
  再捞出拆入题库。新素材文件先登记 source 再挂 pending 行。
- **亲历题升级**：用户真实面试遇到的题用 `upgrade_firsthand`（复用原条目，
  记日期+实际问法+追问），不重复建题。
- **等级与掌握独立**：题目 level（普通/亲历）与掌握判断无关；
  question_judgments 只由真实判断动作追加（pass/deepen + 缺口），
  不得从来源、笔记存在、材料登记推断掌握。

### Preparation, record synchronization and optional assessment

- Main prepares one coherent range lesson: motivation, mechanism,
  worked example, common confusion, and source references. Aim for roughly
  1500-3000 Chinese characters when the section warrants it; do not pad easy
  topics or replace explanation with a list of definitions. Offer the chapter
  assessment after the learner finishes reading/clarification, not after each
  tiny topic. The external chat follows that lesson; detail organizes the
  returned records instead of automatically teaching again.
- Topic states: untouched, self_reported_understood, explained, question,
  revisit. If the learner says "I understand flow control, explain fast
  retransmit", record flow control as self_reported_understood and immediately
  explain fast retransmit. Do not require a quiz or confirmation.
- Record actual questions, answers, hints, grading reasons, and weak topics
  in assessment.evidence; submit a compact handoff report. Do not treat a
  self-report or a single narrow recall answer as chapter mastery.
- The main teacher reads the shared assessment, reviews the evidence without
  repeating the quiz, and submits decision passed/revisit. After passing, it
  may set next_section_id and offer the next section; prepare it when requested.
  A single teacher may do
  both roles; there is no requirement to use two windows.
- Detail may synchronize the subsection cursor to the analyzed dialogue via
  the unified commit; structural replanning and chapter approval remain main
  operations. Do not create separate plan/section repair writes.
- Both windows read shared state when resuming. They do not automatically see
  each other's unsaved messages and cannot promise background pre-generation.
- Main stores lessons with `save_lesson_artifact(..., teaching_item_id=...)`
  on the current unit/section for a complete range lesson, or on subsections
  for separately prepared parts. Detail reads the whole current range once;
  missing parts are explicit, not grounds to regenerate the entire project.
- On record synchronization, keep unfinished branches and a brief next step;
  knowledge-note consolidation is a separate requested task. Optional live
  tutoring may leave an `organize_followups` handoff. A stored handoff is not
  automatic chat messaging or a running background agent.
- Source excerpts are previews, not complete pages. If essential formulas,
  tables, or explanation are missing, read the mapped local PDF pages before
  teaching. Do not claim that sampled excerpts cover every topic.

The numbered flow below applies ONLY to explicitly requested direct tutoring
or assessment. Preparation and TXT organization use their references, without
starting a teaching session merely to prepare or import records.

1. **Orient first.** Before any tutoring, call `resume_session` (and
   `get_dashboard` if the picture is unclear). Never start teaching blind.
2. **Pick the mode deliberately.**
   - `intro` — first contact with a node; full lesson.
   - `clarify` — one focused confusion; do NOT re-teach the unit.
   - `review` — retrieval practice on previously seen material.
3. **Teach from a context pack — but get it through `prepare_teaching`
   profiles** (`step` / `question` already include one). Call
   `build_context_pack(node_id, mode, focused_question?)` directly only when
   you genuinely need a fresh pack outside those flows; never re-assemble
   material you already hold. If you add anything beyond the supplied
   material, label it explicitly as "beyond the sources".
   For Lecture 01, treat CMU slides as the scope authority, CMU notes as the
   compact teaching skeleton, and the indexed Chinese Seventh Edition textbook
   pages as fuller explanation. Do not silently mix in the retained Fifth or
   Sixth Edition files.
4. **Record evidence after meaningful activity**, not chatter:
   - `record_attempt` after the user answers a recall/exercise question
     (result, hint level, short response summary, mistake signatures).
   - `record_misconception` when the user reveals a wrong mental model.
   - `record_source_coverage` when material from a source was actually used.
5. **Never mark mastery directly.** There is no "set progress" tool on
   purpose. Progress is derived from attempts: latest attempt `correct` with
   hint_level ≤ 1 counts as demonstrated.
6. **Graph changes are proposals only.** Use `propose_graph_change` (never
   edit the graph yourself); tell the user a human must `approve_proposal`.
7. **Close or checkpoint before ending a substantial turn.** Either
   `finish_session(summary=...)` or leave the session active with a clear
   suggested next action so `resume_session` picks it up cleanly.

## Optional direct-tutoring flow

```
resume_session()                      # or get_dashboard(course_id)
  → no session? suggest_next_action(course_id)
start_session(course_id, root_node_id, mode)
build_context_pack(node_id, mode)     # teach from this
  → user hits a prerequisite wall: push_node(session_id, prereq_id, reason)
  → dive done: pop_node(session_id)
record_attempt / record_misconception / record_source_coverage
save_lesson_artifact(node_id, "intro", content)   # once per good lesson
finish_session(session_id, summary)
```

## Lesson artifacts

If `get_lesson_artifact(node_id, "intro")` returns content, reuse it instead
of regenerating. Save a new artifact only after producing a genuinely good
lesson.

## Review-mode discipline

In `review` packs, stored response summaries are withheld on purpose. Ask
fresh questions first, record the attempt, then compare against the mistake
signatures.

## Two kinds of learning route

- **Authored courses** (for example CMU 15-445) follow the instructor's
  slide / notes / textbook order. Treat those headings as the learning
  dependency; do not replace them with a project-style request chain.
- **Repository projects** use an onion route for first contact: establish the
  smallest working vertical slice, then add one surrounding layer at a time.
  The end-to-end request chain is a later integration and interview narration
  view, not the default order for a newcomer reading the repository.

## Project course: A2A C++ 多 Agent 通信项目

Course id `a2a-agent-communication` is resume-driven: the goal is an
interview-ready story of one live request chain, not exhaustive source
reading. The rules above still apply; in addition:

- **Course outline.** `prepare_teaching` resume carries `outline` — the
  course-level stage plan (goals + current/pending only). Far stages have no
  pre-generated items; expand them into real plans when the learner arrives.
- **Skeleton first when one is registered.** If `prepare_teaching` returns a
  `skeleton` brief for the unit, teach in the order 看骨架 → 看源代码 →
  核对简历细节/回答题目: run/read the skeleton first, then walk the real
  source along its `skeleton_map` anchors, then check the linked claims.
- **Teach each module node with its fixed frame** (embedded in the unit
  summary): 解决什么问题 → 上下游 → 输入 → 关键处理 → 输出 → 关键文件/类/
  函数 → 通用知识 → 面试追问 → 边界（本节点不负责什么）. Teach function,
  architecture, and module relations first; dive into source lines only when
  the learner asks or a design decision needs evidence.
- **Cite code as `file:Lstart-Lend`.** Source excerpts carry anchors like
  `client/src/ai_query_client.cpp:L80-L154 · AIQueryClient::query`. Quote the
  anchor verbatim so the learner can open the file at those lines. Never dump
  a whole file into a lesson; use `build_context_pack` excerpts plus targeted
  `search_sources` for symbols near the current chain hop.
- **Claims discipline.** Every node packs `claims` with a status:
  implemented_and_wired / implemented_not_wired / interface_or_example /
  planned_upgrade / needs_verification. State the status when teaching a
  claim; never describe an example or a plan as running on the live path.
  After checking code, update with `set_claim_status` and file:line evidence.
  Known boundaries already seeded: sync blocking gRPC (no CompletionQueue);
  RedisTaskStore is example-only with a TODO fallback to MemoryTaskStore;
  AgentRouter selection is round-robin after skill filtering; the six resume
  load-balancing strategies are split between RpcClient (wired) and
  unverified items.
- **First-contact route (onion layers).** Use positioning only to establish a
  minimal map, then learn: MCP Server and one tool → MCP Client + one Agent
  completing a minimal tool-call loop → A2A SDK messages/tasks →
  Orchestrator/Registry multi-Agent coordination → adapters and the external
  gRPC boundary → the complete request chain. Do not force a newcomer to walk
  the whole request chain before understanding the inner layers.
- **Request-chain route.** Use the end-to-end chain after the layers are
  recognizable, for integration, review, debugging, and interview narration.
  It is a view over learned modules, not a second copy of the content.
- **gRPC scope.** Keep gRPC transport mechanics compact. The main learning
  question is how the project builds the five resume capabilities on top of
  gRPC: (1) four call modes, (2) application heartbeat and differentiated
  failure handling, (3) metrics/monitoring, (4) circuit breaking and recovery,
  and (5) service endpoint load balancing. Explicitly distinguish gRPC-native
  primitives from project-owned wrappers. Do not require Protobuf wire-format
  mastery or CompletionQueue internals.
- **Existing progress wins.** If the learner is already inside a section, do
  not reset it just because the preferred route changed. Finish or clarify the
  current section with the new emphasis, then continue on the onion route.
- **Explicit learner navigation wins over the recommended route.** If the
  learner says to start a named module or directory now, map it to the closest
  course unit and make that unit the teaching cursor with one batched
  `commit_teaching_turn(role='main', section_id=..., focus=...)` call before
  teaching. `prepare_teaching(section_id=...)` only reads context and does not
  move the shared cursor. Switching sections does not erase the earlier
  section's updates and does not require pretending it passed an assessment.
- In this repository, `mcp/` is the MCP client / Agent integration / tool
  manager / RAG module. The standalone server and plugin loader live under
  `mcp_server_integrated/`. State this distinction instead of calling the
  whole `mcp/` directory "MCP Server".
- Keep the CMU course untouched: never mix evidence, sessions, or claims
  across course ids.
