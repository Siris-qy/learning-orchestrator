"""MCP adapter: exposes the Orchestrator as tools over stdio.

Requires the `mcp` package (Python >= 3.10). The core library does not depend
on it. Run with:  python -m learning_orchestrator.mcp_server
"""

import json
import sys

from .graph import ValidationError
from .service import Orchestrator

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - adapter-only dependency
    sys.stderr.write(
        "The MCP adapter requires the 'mcp' package and Python >= 3.10.\n"
        "Install with: pip install -e '.[mcp]'\n")
    raise SystemExit(1)

mcp = FastMCP("learning-orchestrator")
_orch = Orchestrator()
_orch.initialize()


def _call(fn, **kwargs):
    """Uniform error surface: validation failures become tool errors."""
    try:
        return json.dumps(fn(**kwargs), ensure_ascii=False, indent=2)
    except ValidationError as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def initialize_database() -> str:
    """Create the schema and seed the CMU 15-445 slice. Idempotent."""
    return _call(_orch.initialize)


@mcp.tool()
def list_courses() -> str:
    """List seeded courses."""
    return _call(_orch.list_courses)


@mcp.tool()
def get_dashboard(course_id: str) -> str:
    """Coverage / objective progress / review-due / active session cards."""
    return _call(_orch.get_dashboard, course_id=course_id)


@mcp.tool()
def get_graph(course_id: str, edge_types: list = None) -> str:
    """Course graph; optional edge-type filter (e.g. ['part_of','prerequisite'])."""
    return _call(_orch.get_graph, course_id=course_id, edge_types=edge_types)


@mcp.tool()
def get_node_detail(node_id: str) -> str:
    """Node with sources, misconceptions, recent events, lesson artifacts."""
    return _call(_orch.get_node_detail, node_id=node_id)


@mcp.tool()
def start_session(course_id: str, root_node_id: str, mode: str,
                  goal: str = "") -> str:
    """Start a session at a root node. mode: intro | clarify | review."""
    return _call(_orch.start_session, course_id=course_id,
                 root_node_id=root_node_id, mode=mode, goal=goal)


@mcp.tool()
def resume_session(course_id: str = None) -> str:
    """Resume the active session: root goal, stack, open questions, next step."""
    return _call(_orch.resume_session, course_id=course_id)


@mcp.tool()
def push_node(session_id: str, node_id: str, reason: str = "") -> str:
    """Dive into a nested node (e.g. a prerequisite) inside the session."""
    return _call(_orch.push_node, session_id=session_id, node_id=node_id,
                 reason=reason)


@mcp.tool()
def pop_node(session_id: str, reason: str = "") -> str:
    """Return from a nested dive to the parent node."""
    return _call(_orch.pop_node, session_id=session_id, reason=reason)


@mcp.tool()
def finish_session(session_id: str, summary: str = "",
                   abandon: bool = False) -> str:
    """Close (or abandon) a session with a summary."""
    return _call(_orch.finish_session, session_id=session_id, summary=summary,
                 abandon=abandon)


@mcp.tool()
def build_context_pack(node_id: str, mode: str,
                       focused_question: str = None) -> str:
    """Assemble teaching material for a node. mode: intro | clarify | review."""
    return _call(_orch.build_context_pack, node_id=node_id, mode=mode,
                 focused_question=focused_question)


@mcp.tool()
def record_source_coverage(session_id: str, node_id: str, source_id: str,
                           anchor: str = "") -> str:
    """Mark that a source (or anchor within it) was covered at a node."""
    return _call(_orch.record_source_coverage, session_id=session_id,
                 node_id=node_id, source_id=source_id, anchor=anchor)


@mcp.tool()
def record_attempt(session_id: str, node_id: str, result: str,
                   hint_level: int = 0, response_summary: str = "",
                   mistake_signatures: list = None, batch_id: int = None,
                   record_kind: str = None) -> str:
    """Record a recall/exercise attempt. result: correct | partial | incorrect.
    hint_level 0..3 (0 = unaided). Evidence only; progress is derived.
    batch_id/record_kind attach the record to a teaching batch (TODO §8.5)."""
    return _call(_orch.record_attempt, session_id=session_id, node_id=node_id,
                 result=result, hint_level=hint_level,
                 response_summary=response_summary,
                 mistake_signatures=mistake_signatures,
                 batch_id=batch_id, record_kind=record_kind)


@mcp.tool()
def record_note(session_id: str, node_id: str, text: str,
                batch_id: int = None, record_kind: str = None) -> str:
    """Process record attached to a node (a question while copying, time spent).
    Reviewable per node afterwards; not a mastery signal."""
    return _call(_orch.record_note, session_id=session_id, node_id=node_id,
                 text=text, batch_id=batch_id, record_kind=record_kind)


@mcp.tool()
def record_misconception(session_id: str, node_id: str, text: str,
                         signature: str = "") -> str:
    """Record an observed misconception tied to a node."""
    return _call(_orch.record_misconception, session_id=session_id,
                 node_id=node_id, text=text, signature=signature)


@mcp.tool()
def resolve_misconception(misconception_id: int) -> str:
    """Mark a misconception resolved after the learner demonstrates it."""
    return _call(_orch.resolve_misconception, misconception_id=misconception_id)


@mcp.tool()
def save_lesson_artifact(node_id: str, mode: str, content: str,
                         teaching_item_id: int = None) -> str:
    """Main prepares and saves a self-contained handoff lesson, not learning
    evidence. Include course/section/item identifiers, subsection IDs and
    ordered outline, necessary background, explanation/examples/code/images,
    source anchors and suggested batches (no fixed subsection count).
    teaching_item_id attaches it to the
    teaching unit/section/subsection that it covers. A complete range lesson
    need not be split or rewritten. Omit it for legacy whole-node lessons."""
    return _call(_orch.save_lesson_artifact, node_id=node_id, mode=mode,
                 content=content, teaching_item_id=teaching_item_id)


@mcp.tool()
def get_lesson_artifact(node_id: str, mode: str = "intro",
                        teaching_item_id: int = None) -> str:
    """Retrieve a previously saved lesson artifact, if any."""
    return _call(_orch.get_lesson_artifact, node_id=node_id, mode=mode,
                 teaching_item_id=teaching_item_id)


@mcp.tool()
def propose_graph_change(kind: str, payload: dict, rationale: str = "") -> str:
    """Stage a graph change (add_node | update_node | add_edge | remove_edge).
    Nothing is applied until a human approves it."""
    return _call(_orch.propose_change, kind=kind, payload=payload,
                 rationale=rationale)


@mcp.tool()
def list_proposals(status: str = None) -> str:
    """List proposals, optionally filtered by status."""
    return _call(_orch.list_proposals, status=status)


@mcp.tool()
def approve_proposal(proposal_id: str) -> str:
    """Apply a pending proposal transactionally; bumps the graph version."""
    return _call(_orch.approve_proposal, proposal_id=proposal_id)


@mcp.tool()
def reject_proposal(proposal_id: str, reason: str = "") -> str:
    """Reject a pending proposal."""
    return _call(_orch.reject_proposal, proposal_id=proposal_id, reason=reason)


@mcp.tool()
def register_source_file(course_id: str, path: str, title: str = None,
                         lecture_ref: str = "") -> str:
    """Import a Markdown/TXT/PDF file from a configured source root."""
    return _call(_orch.register_source_file, course_id=course_id, path=path,
                 title=title, lecture_ref=lecture_ref)


@mcp.tool()
def attach_source(node_id: str, source_id: str, anchor: str = "") -> str:
    """Attach a registered source to a node with an optional anchor."""
    return _call(_orch.attach_source, node_id=node_id, source_id=source_id,
                 anchor=anchor)


@mcp.tool()
def suggest_next_action(course_id: str) -> str:
    """One plain-language suggestion for what to learn next."""
    return _call(_orch.suggest_next_action, course_id=course_id)


def main():
    mcp.run()


@mcp.tool()
def prepare_teaching(course_id: str, role: str = 'main', section_id: str = None,
                     focused_question: str = None, profile: str = None,
                     include_lesson: bool = False,
                     lesson_scope: str = 'subsection',
                     learning_route: str = None) -> str:
    """Assemble teaching context BY SCENARIO — pick the smallest profile that fits:
    Default workflow: main prepares lessons, an external chat teaches, detail
    analyzes supplied learning records and maintains continuity. Direct tutoring
    remains optional. learning_route='course'|'project' overrides route hints
    for resume; it does not change progress or require a new course schema.
    local    = record window: subsection position + local questions, NO retrieval
               or history. On takeover use include_lesson=True, lesson_scope='unit'
               for the current unit's complete saved lesson + ordered outline.
               'section' narrows to its grouping; 'subsection' keeps legacy behavior.
               Whole-range lesson wins; otherwise gather saved child lessons.
    Missing lessons are listed, not fabricated. No fixed item count.
               Later local checks omit include_lesson to avoid returning it again.
    resume   = taking over / switching window: plan outline, cursor, open questions.
    step     = advancing inside a stage: current item + its sub-items/questions +
               next pending milestone + a small context pack.
    question = local follow-up: only the context pack for focused_question.
    review   = stage handoff/acceptance: full state and history (rare, main only).
    Default: 'question' if focused_question given, else 'resume'.
    local/resume automatically check the section's previously organized TXT.
    record_sync='pending_analysis' supplies bounded changed text: the calling
    AI must analyze and merge progress in this turn, without asking the learner
    to repeat an analysis instruction. Unchanged files return metadata only.
    This is resume-time automation, NOT a continuously running listener.
    Do NOT call review for routine turns; do NOT re-fetch material you already have.
    """
    return _call(_orch.prepare_teaching, course_id=course_id, role=role,
                 section_id=section_id, focused_question=focused_question,
                 profile=profile, include_lesson=include_lesson,
                 lesson_scope=lesson_scope, learning_route=learning_route)


@mcp.tool()
def prepare_learning_record(course_id: str, section_id: str = None,
                            path: str = None, transcript: str = None,
                            source_ref: str = None, offset: int = 0,
                            max_chars: int = 10000) -> str:
    """On-demand, window-neutral learning-record organization. Read a TXT/MD
    file OR supplied chat transcript, in bounded character slices with next_offset.
    Returns source fingerprint, current position and item IDs for AI analysis.
    Does NOT analyze with a model, index the text, or change any progress.
    For an app conversation, the calling AI first reads the user-specified thread
    with the app's conversation tool, then passes transcript + source_ref here.
    Save an AI report via commit_teaching_turn(record_analysis=...). Once saved,
    path/transcript can be omitted to reuse this section's bound TXT. Persist
    processed_chars=fragment.end_offset and prefix_fingerprint only after that
    contiguous range has actually been analyzed (plus fingerprint/source_ref).
    Reading alone never advances this checkpoint."""
    return _call(_orch.prepare_learning_record, course_id=course_id,
                 section_id=section_id, path=path, transcript=transcript,
                 source_ref=source_ref, offset=offset, max_chars=max_chars)


@mcp.tool()
def commit_teaching_turn(course_id: str, section_id: str, role: str,
                         topics: list = None, focus: str = None,
                         assessment: dict = None, handoff: dict = None,
                         decision: str = None, next_section_id: str = None,
                         current_item_id: int = None,
                         items_add: list = None, items_update: list = None,
                         base_state_version: int = None,
                         push_return_position: dict = None,
                         pop_return_position: bool = False,
                         verbose: bool = False, turn_record: dict = None,
                         record_analysis: dict = None,
                         current_item_key: str = None) -> str:
    """ONE merged write per reply: topic updates + item-tree edits + cursor move.
    role: main | detail | control ('clarify' = legacy alias of detail).
    层级：阶段(milestone) → 单元(sub) → 节(section) → 小节(sub) → 小项(追问
    question / 过程记录)。完整教案作为背景；输出批次按实际内容与用户负荷定。
    Item tree: milestones come from save_teaching_plan (main only); detail may
    add 'sub' items while teaching and 'question' items when the learner asks
    something worth returning to. items_add: [{kind: section|sub|question,
    title, note?, parent_id? (defaults to current item)}] — kind='section'
    (分节) is main-only. items_update: [{id, status?, note?, title?, seq?,
    parent_id?}] — statuses are informational markers, never gated.
    Structural edits (title/seq/parent_id/status='retracted', and touching an
    already-retracted item) are main-only: detail proposes, main executes.
    'retracted' = 作废留痕（被替代/误登记），不进正式顺序与统计，不物理删除。
    'presented' = 讲义已输出/已讲解，不代表已理解；'done' = 已验证通过，
    only main marks any item 'done'. Solving a child never completes its
    parent; questions never affect formal progress.
    Detail aligns the supplied transcript to the saved lesson: keep
    current_item_id at the subsection, hang nested question items underneath.
    Explained questions are
    awaiting_confirmation; only user confirmation makes them resolved.
    self_reported_understood marks a user's subsection confirmation, NOT mastery.
    turn_record={item_id, question_id?, user_text?, assistant_text?,
    user_confirmation?} stores raw text in the SAME commit and returns record_id;
    no inline note consolidation. A newly added question's id is in items_added;
    its first raw turn can rely on item_id + items_add, without a second call.
    On subsection transition, handoff={kind:'organize_followups', item_id,
    record_ids?, summary?, remaining_questions?}; main pulls it later, no active
    notification or waiting. Legacy push/pop remain available for old clients.
    record_analysis={source_ref, summary, fingerprint?, covered_ranges?,
    learned?, confirmations?, questions?, gaps?, suggested_position?} stores
    AI analysis of external chat/TXT in this same log. Alone it changes NO
    workspace, cursor or mastery. Merge existing item/topic operations only
    when synchronization is requested. Exact replay reuses the record_id.
    Roles are operation permissions, not a required physical chat window.
    To import a recursive question tree in ONE commit, items_add accepts key,
    parent_key (an earlier key in this same list), initial status and record_key.
    With record_analysis, stable record_key identifies the same source question
    across later TXT additions, updating it rather than creating duplicates.
    Return item_refs maps these temporary keys to persisted item IDs.
    current_item_key targets a newly created/reused subsection; do not point
    the formal cursor at a recursive question. Confirmed states aren't downgraded
    by a reimport. Keep source/turn/line evidence in the report and item note.
    Default detail work is incremental record analysis and synchronization,
    not re-teaching the supplied transcript or re-reading project sources.
    In optional direct tutoring, answer only the current point and divide by
    learner load, never a fixed subsection count. External chat teaching
    requires no per-turn plugin write; merge changes per analyzed increment.
    Pass base_state_version from prepare/get_teaching_state so a stale window
    cannot overwrite a newer position. Returns only success + state_version +
    cursor (+ open_question_count). verbose=True returns full state — avoid it
    in routine turns.
    """
    return _call(_orch.commit_teaching_turn, course_id=course_id, section_id=section_id,
                 role=role, topics=topics, focus=focus, assessment=assessment,
                 handoff=handoff, decision=decision, next_section_id=next_section_id,
                 current_item_id=current_item_id, items_add=items_add,
                 items_update=items_update, base_state_version=base_state_version,
                 push_return_position=push_return_position,
                 pop_return_position=pop_return_position, verbose=verbose,
                 turn_record=turn_record, record_analysis=record_analysis,
                 current_item_key=current_item_key)


@mcp.tool()
def save_teaching_plan(course_id: str, section_id: str, milestones: list,
                       created_by: str = 'main', stage_key: str = None) -> str:
    """Create a new teaching plan version (main window only).
    milestones: [{title, node_id?, material_ref?}] in teaching order — the
    stage-level outline only; main prepares section/subsection items using
    commit_teaching_turn before saving their handoff lesson. Detail may add
    process questions and unplanned sub-items while organizing actual records.
    The previous active plan is superseded; existing evidence is kept.
    Optional stage_key registers the section under an existing course outline
    stage, so its current badge follows the subsection cursor automatically.
    Moving an item via commit also synchronizes its plan and workspace section;
    do not perform separate plan/section repair calls."""
    return _call(_orch.save_teaching_plan, course_id=course_id,
                 section_id=section_id, milestones=milestones, created_by=created_by,
                 stage_key=stage_key)


@mcp.tool()
def get_teaching_state(course_id: str, full: bool = False,
                        records_for_item: int = None, after_id: int = 0,
                        limit: int = 5, analysis_id: int = None) -> str:
    """Window recovery: plan outline, cursor, open questions (compact).
    full=True returns state history — acceptance only. For handoff organization,
    records_for_item reads only that subsection's raw turns/handoffs, paginated
    by after_id/limit. analysis_id explicitly retrieves one saved learning-record
    report; reports are excluded from routine state returns to keep them small.
    These explicit reads do not change any progress."""
    return _call(_orch.get_teaching_state, course_id=course_id, full=full,
                 records_for_item=records_for_item, after_id=after_id, limit=limit,
                 analysis_id=analysis_id)


@mcp.tool()
def register_skeleton(course_id: str, node_id: str, path: str,
                      title: str = None) -> str:
    """Register ONE complete skeleton file for a unit (TODO §8.1, 2026-09-22
    spec: one content = one self-contained file covering all functionality).
    Imports it as a code source, attaches it to the node, state='prepared'.
    Re-registering the same file returns the existing row."""
    return _call(_orch.register_skeleton, course_id=course_id,
                 node_id=node_id, path=path, title=title)


@mcp.tool()
def set_skeleton_state(skeleton_id: int, state: str, note: str = "") -> str:
    """Advance a skeleton lifecycle marker (lightweight, any order):
    prepared 备课已生成 | runnable 代码可运行 | copied 用户已抄写 |
    understood 用户理解 | verified 通过验证. Recorded for review."""
    return _call(_orch.set_skeleton_state, skeleton_id=skeleton_id,
                 state=state, note=note)


@mcp.tool()
def add_skeleton_map(skeleton_id: int, entries: list) -> str:
    """Skeleton→real-source index rows (TODO §8.4). Each entry:
    {skeleton_anchor, claim_id?, real_ref?, note?} — skeleton_anchor names the
    skeleton class/section; real_ref is real file:line evidence (string or
    list); note carries the boundary declaration; claim_id links a resume
    claim of the same course."""
    return _call(_orch.add_skeleton_map, skeleton_id=skeleton_id,
                 entries=entries)


@mcp.tool()
def list_skeletons(course_id: str = None, node_id: str = None) -> str:
    """Skeletons with their real-source index and current state marker."""
    return _call(_orch.list_skeletons, course_id=course_id, node_id=node_id)


@mcp.tool()
def review_today(course_id: str, limit: int = 15) -> str:
    """Today's review menu (M3): due items most-overdue first, then unknown
    points to fill capacity. The limit is a cap, NOT a quota — unfinished
    items roll over without penalty. Review by knowledge point, not by file."""
    return _call(_orch.review_today, course_id=course_id, limit=limit)


@mcp.tool()
def review_overview(course_id: str) -> str:
    """Review counts: unknown / active / due today / weak candidates.
    'unknown' means never verified — it is not mastery and not overdue."""
    return _call(_orch.review_overview, course_id=course_id)


@mcp.tool()
def prepare_review(review_item_id: int) -> str:
    """The point's own knowledge-block chunk for building ONE closed-book
    question. Do not show this material to the learner before they answer,
    and do not substitute index-file snippets for it."""
    return _call(_orch.prepare_review, review_item_id=review_item_id)


@mcp.tool()
def record_review(review_item_id: int, result: str, hint_level: int = 0,
                  note: str = "") -> str:
    """Record one review action and advance the schedule (fixed Ebbinghaus
    1/2/4/7/15/30d). result: correct | partial | wrong. Only a clean correct
    (hint<=1) advances a level; heavily-hinted reads as partial; wrong resets
    to level 0 due tomorrow. Dates count from this action; overdue never
    penalises."""
    return _call(_orch.record_review, review_item_id=review_item_id,
                 result=result, hint_level=hint_level, note=note)


@mcp.tool()
def add_claim(course_id: str, text: str, status: str, node_id: str = None,
              evidence: str = "") -> str:
    """Record a resume/project claim with its implementation status.
    status: implemented_and_wired | implemented_not_wired |
    interface_or_example | planned_upgrade | needs_verification.
    evidence should cite file:line. Never present plans as wired."""
    return _call(_orch.add_claim, course_id=course_id, text=text,
                 status=status, node_id=node_id, evidence=evidence)


@mcp.tool()
def list_claims(course_id: str = None, node_id: str = None,
                status: str = None) -> str:
    """List claims (resume statements) with implementation status."""
    return _call(_orch.list_claims, course_id=course_id, node_id=node_id,
                 status=status)


@mcp.tool()
def set_claim_status(claim_id: int, status: str, evidence: str = None) -> str:
    """Update a claim's implementation status after verifying against code."""
    return _call(_orch.set_claim_status, claim_id=claim_id, status=status,
                 evidence=evidence)


@mcp.tool()
def query_questions(course_id: str, text: str = None, group: str = None,
                    point_id: str = None, project_ref: str = None) -> str:
    """结构化题库检索入口（R2）。新面经先查题库再登记；查不到再看素材池
    （question_pool_status）。题目等级与掌握独立，本工具不判断掌握。"""
    return _call(_orch.query_questions, course_id=course_id, text=text,
                 group=group, point_id=point_id, project_ref=project_ref)


@mcp.tool()
def get_question_detail(question_id: str) -> str:
    """单题全貌：题干/问法/上下文/答案依据/来源/知识归属/判断状态。没有
    判断行 = 未判断，不代表已掌握。"""
    return _call(_orch.get_question_detail, question_id=question_id)


@mcp.tool()
def record_question_judgment(question_id: str, result: str, answer_summary: str,
                             gap_note: str = '', teaching_item_id: int = None) -> str:
    """实际答题后一次记录：pass=基本可以，deepen=需深入（附具体缺口）。
    answer_summary 简记用户实际回答/提示程度，不能把AI讲过当用户已掌握。
    可关联教学小项；不完成父章节、不推进排期。只返回小回执，无历史装配。
    """
    if not answer_summary.strip():
        return json.dumps({'error': '请简记用户实际回答，不从讲解记录推断掌握。'}, ensure_ascii=False)
    return _call(_orch.record_question_judgment, question_id=question_id,
                 result=result, gap_note=gap_note, origin='teaching-ai',
                 answer_summary=answer_summary, teaching_item_id=teaching_item_id)


@mcp.tool()
def link_teaching_knowledge(item_id: int, knowledge_course_id: str,
                            point_id: str, note: str = '') -> str:
    """将教学小项关联到已有知识点锚点（如 T02），不复制正文、不改进度。
    仅在对应关系明确时写入；跨项目复用基础知识时显式指定知识所属课程。
    """
    return _call(_orch.link_teaching_knowledge, item_id=item_id,
                 knowledge_course_id=knowledge_course_id, point_id=point_id, note=note)


@mcp.tool()
def knowledge_connections(knowledge_course_id: str, point_id: str) -> str:
    """需要追溯时才查询某知识点关联的教学小项和题目；日常局部追问不必调用。"""
    return _call(_orch.knowledge_connections, knowledge_course_id=knowledge_course_id,
                 point_id=point_id)


@mcp.tool()
def append_knowledge(block_id: str, title: str, heading: str, content: str,
                     area: str = 'backend', kind: str = 'explanation',
                     source_refs: list = None, placements: list = None,
                     entry_id: str = None) -> str:
    """小节结束/有价值的追问解决后，追加长期知识（不必等整门课程结束）。
    先检索现有 block_id，复用概念知识块，例如 tcp、mcp、database-storage。
    area: backend/cpp/algorithms/database/other；kind: explanation/example/question/correction/reference。
    已登记旧笔记可用 reference，content=''，source_refs 指定准确 source_id+anchor，正文不复制。
    content 是该点可复习的解释/例子，不是整段聊天；疑问用 question，注明待确认。
    source_refs: [{source_id,anchor},{course_id,teaching_item_id},{path,anchor}] 保留出处。
    placements: [{view_key:'foundations',path:['数据库','存储']},
      {view_key:'course:<course_id>',path:['Lecture 03','存储']}]
    项目视角用 project:<course_id>，多个位置只引用同一正文。使用稳定 entry_id
    防重试重复写入。只返回回执；不改掌握、游标或排期，不装配全量历史。
    """
    return _call(_orch.append_knowledge, block_id=block_id, title=title,
                 heading=heading, content=content, area=area, kind=kind,
                 source_refs=source_refs, placements=placements, entry_id=entry_id)


@mcp.tool()
def get_knowledge_block(block_id: str, include_history: bool = False) -> str:
    """读取一个知识块：整理正文＋尚未合并的增量＋来源及双向关联。
    仅在要学/复习这一块时调用。整理前 include_history=True 读取原始补充。
    """
    return _call(_orch.get_knowledge_block, block_id=block_id, include_history=include_history)


@mcp.tool()
def list_knowledge_library() -> str:
    """查看基础能力、项目、课程下的知识块索引（不返回正文）。追加前找已有块。
    已有笔记以引用接入；缺笔记不会被当成没学过。
    """
    return _call(_orch.knowledge_library)


@mcp.tool()
def search_knowledge_points(query: str, limit: int = 20) -> str:
    """按块内标题找知识点，返回稳定ID和所属块，不装配正文或历史。"""
    return _call(_orch.search_knowledge_points, query=query, limit=limit)


@mcp.tool()
def get_knowledge_point(point_id: str) -> str:
    """只读指定知识点正文及关联；不改变学习、掌握或排期。"""
    return _call(_orch.get_knowledge_point, point_id=point_id)


@mcp.tool()
def relate_knowledge_points(from_id: str, to_id: str, relation: str = 'related', note: str = '') -> str:
    """建立块内知识点的双向可查关联；前置/使用保留方向，不自动猜关系。"""
    return _call(_orch.relate_knowledge_points, from_id=from_id,to_id=to_id,relation=relation,note=note)


@mcp.tool()
def place_knowledge(block_id: str, view_key: str, path: list, seq: int = 0) -> str:
    """为现有块补一个展示位置。foundations 或 project:/course:<course_id>。
    path 是标题层级；位置变化不复制正文。"""
    return _call(_orch.place_knowledge, block_id=block_id, view_key=view_key, path=path, seq=seq)


@mcp.tool()
def consolidate_knowledge(block_id: str, content: str, covered_entry_ids: list) -> str:
    """内容成体系后保存整理正文，明确覆盖的补充ID（包括上一版本已覆盖ID）。
    原始增量保留；后来的补充仍单独显示。注明未解决问题，不把猜想写成定论。
    不需要每次追加就整理，也不改学习状态。"""
    return _call(_orch.consolidate_knowledge, block_id=block_id,
                 content=content, covered_entry_ids=covered_entry_ids)


@mcp.tool()
def relate_knowledge(from_id: str, to_id: str, relation: str = 'related', note: str = '') -> str:
    """关联两个知识块：related/prerequisite/used_in/contrasts_with。反向可查，
    前置和使用关系保留方向。不依据标题相似自动连全部节点。"""
    return _call(_orch.relate_knowledge, from_id=from_id, to_id=to_id, relation=relation, note=note)


@mcp.tool()
def add_interview_question(course_id: str, stem: str, group_key: str = "",
                           variants: list = None, context: str = "",
                           answer_basis: str = "", source_lines: list = None,
                           points: list = None, projects: list = None) -> str:
    """登记新面经题。先 query_questions 去重：命中已有题则补问法/来源
    （不新建），确实没有才建新题。等级与掌握独立，登记不代表掌握。"""
    return _call(_orch.add_interview_question, course_id=course_id, stem=stem,
                 group_key=group_key, variants=variants, context=context,
                 answer_basis=answer_basis, source_lines=source_lines,
                 points=points, projects=projects)


@mcp.tool()
def upgrade_firsthand(question_id: str, interviewed_at: str,
                      actual_wording: str = "", followups: str = "") -> str:
    """把用户真实面试遇到过的题升级为亲历题：复用原条目，记录日期、实
    际问法与追问。只改等级，不触碰判断记录——亲历≠掌握。"""
    return _call(_orch.upgrade_firsthand, question_id=question_id,
                 interviewed_at=interviewed_at, actual_wording=actual_wording,
                 followups=followups)


@mcp.tool()
def question_pool_status(source_id: str = None) -> str:
    """素材池迁移台账：各 (source, section) 的迁移状态与已迁出题 id。"""
    return _call(_orch.question_pool_status, source_id=source_id)


@mcp.tool()
def resolve_review_mentions(mentions: list, project_id: str = None,
                            limit_per_mention: int = 5) -> str:
    """项目复盘登记前，按名称/别名/正文查已有知识候选，不自动合并或判断掌握。"""
    return _call(_orch.resolve_review_mentions, mentions=mentions, project_id=project_id,
                 limit_per_mention=limit_per_mention)


@mcp.tool()
def commit_review_map(request_id: str, project_id: str = None, nodes: list = None,
                      edges: list = None, findings: list = None,
                      question_links: list = None, legacy_bindings: list = None) -> str:
    """增量保存复盘知识图，一次原子提交，稳定 request_id 防重。
    新节点 {client_key,title,kind:project/module/flow/knowledge/option/claim,
    domains?,summary?,content_ref?,content?}; 复用节点提供 id。正文仍存知识块。
    边 {from,to,relation:contains/uses/requires/next/fails_to/supports/alternative_to/
    upgrade_to/abstracts_to/analogous_to,context_project_id?,inclusion:core/extension,
    usage?,used_parts?,required_depth?,default_expansion?}。from/to 可引用 client_key。
    旧排期绑定 {type:review_point,course_id,id:旧点号,node_id}。
    省略保留旧值，掌握评估另调 record_review_assessment；来源/实现状态可选。
    """
    return _call(_orch.commit_review_map, request_id=request_id, project_id=project_id,
                 nodes=nodes, edges=edges, findings=findings, question_links=question_links,
                 legacy_bindings=legacy_bindings)


@mcp.tool()
def list_content_strategies() -> str:
    """List replaceable note/lesson production strategies; no full rule bundle."""
    return _call(_orch.list_content_strategies)


@mcp.tool()
def get_workflow_contract(operation: str = None) -> str:
    """List business operations; supply operation for its scope, artifact schema,
    writes and available strategies. Stages classify tasks, not artifact formats.
    """
    return _call(_orch.get_workflow_contract, operation=operation)


@mcp.tool()
def register_curriculum(request_id: str, course_id: str, title: str,
                         kind: str = 'course', sections: list = None) -> str:
    """Register a course/project in a blank workspace. sections=[{id,title,type?:
    module/unit/objective,parent_id?,summary?,seq?}]. Stable IDs preserve updates;
    registration itself creates no learning, mastery or review evidence.
    """
    return _call(_orch.register_curriculum, request_id=request_id, course_id=course_id,
                 title=title, kind=kind, sections=sections)


@mcp.tool()
def prepare_workflow(stage: str = None, scope: dict = None, inputs: dict = None,
                      strategy_id: str = None, operation: str = None, controls: dict = None) -> str:
    """Prepare an explicit business operation from get_workflow_contract.
    Examples: note.publish, lesson.publish, record.learning, record.review,
    questions.commit, graph.commit, review.save. stage is legacy compatibility.
    Return ticket, selected context/method, artifact schema and allowed effects.
    """
    return _call(_orch.prepare_workflow, stage=stage, scope=scope, inputs=inputs,
                 strategy_id=strategy_id, operation=operation, controls=controls)


@mcp.tool()
def get_workflow_board(project_id: str = '') -> str:
    """Four processes, saved project controls and available methods. Same state as the workflow board."""
    return _call(_orch.get_workflow_board, project_id=project_id)


@mcp.tool()
def save_workflow_controls(project_id: str, process: str, values: dict, base_version: int = 0) -> str:
    """Save clarified project goal/input/output/method/material selections; process=lesson/record/note/associate."""
    return _call(_orch.save_workflow_controls, project_id=project_id, process=process,
                 values=values, base_version=base_version)


@mcp.tool()
def save_constraint_module(title: str, effect: str, instructions: str, applies_to: list,
                            module_id: str = None, base_version: int = 0) -> str:
    """Create/edit a reusable input/method/output constraint. Applies to lesson/record/note/associate."""
    return _call(_orch.save_constraint_module, title=title, effect=effect, instructions=instructions,
                 applies_to=applies_to, module_id=module_id, base_version=base_version)


@mcp.tool()
def save_workflow_task(task: dict, title: str = None) -> str:
    """Save a prepared handoff and its exact ticket in documents; can resume after closing the window."""
    return _call(_orch.save_workflow_task, task=task, title=title)


@mcp.tool()
def get_workflow_task(document_id: str) -> str:
    """Restore a saved handoff, its stable submit request_id and previous receipt if already submitted."""
    return _call(_orch.get_workflow_task, document_id=document_id)


@mcp.tool()
def list_documents(project_id: str = None, kind: str = None, query: str = '', offset: int = 0, limit: int = 60) -> str:
    """Find raw materials, lessons, records and canonical notes by stable document ID."""
    return _call(_orch.list_documents, project_id=project_id, kind=kind, query=query, offset=offset, limit=limit)


@mcp.tool()
def save_document(title: str, kind: str = 'material', project_id: str = '', document_id: str = None,
                  text: str = None, path: str = None, base_version: int = None, source_refs: list = None) -> str:
    """Import text or an allowed local file into workspace documents; updates preserve previous versions."""
    return _call(_orch.save_document, title=title, kind=kind, project_id=project_id, document_id=document_id,
                 text=text, path=path, base_version=base_version, source_refs=source_refs)


@mcp.tool()
def read_document(document_id: str, version: int = None, start_line: int = 1, end_line: int = None,
                  page_start: int = 1, page_end: int = None, max_chars: int = 12000, anchor: str = None) -> str:
    """Read a selected version/line/page/anchor; bounded text, original document identity and fingerprint."""
    return _call(_orch.read_document, document_id=document_id, version=version, start_line=start_line,
                 end_line=end_line, page_start=page_start, page_end=page_end, max_chars=max_chars, anchor=anchor)


@mcp.tool()
def commit_workflow(request_id: str, ticket: dict, artifact: dict) -> str:
    """Commit an AI-produced stage artifact through existing LO stores. Original
    request replay is idempotent; note publication does not imply understanding.
    """
    return _call(_orch.commit_workflow, request_id=request_id, ticket=ticket, artifact=artifact)


@mcp.tool()
def save_review_batch(request_id: str, batch_id: str, title: str, items: list,
                      project_id: str = None, source_ref: str = '') -> str:
    """Keep an ordered set of existing questions for external study and later
    review. items=[{question_id,label?,node_ids?}]. Never creates duplicate questions.
    """
    return _call(_orch.save_review_batch, request_id=request_id, batch_id=batch_id,
                 title=title, items=items, project_id=project_id, source_ref=source_ref)


@mcp.tool()
def commit_question_batch(request_id: str, entries: list, source_ref: dict = None) -> str:
    """Incremental question ingestion. entries identify existing question_id or
    new stem/client_key; optional variants, source_ref, categories, links=[{node_id,
    context_project_id?,focus?,coverage?}], pending_reason and explicit corrections.
    Omitted fields are preserved; semantic dedup is the AI's decision before commit.
    """
    return _call(_orch.commit_question_batch, request_id=request_id, entries=entries, source_ref=source_ref)


@mcp.tool()
def list_review_batches(project_id: str = None) -> str:
    """Find the user's registered original-question batches, even before due dates."""
    return _call(_orch.list_review_batches, project_id=project_id)


@mcp.tool()
def get_review_batch(batch_id: str) -> str:
    """Read the batch's original questions, actual answers and unresolved branches."""
    return _call(_orch.get_review_batch, batch_id=batch_id)


@mcp.tool()
def export_review_batch(batch_id: str, node_ids: list = None, include_answers: bool = False) -> str:
    """Self-contained Markdown and stable manifest for a web AI. Without answers
    by default; selected published bodies use the same reader as the dashboard.
    """
    return _call(_orch.export_review_batch, batch_id=batch_id, node_ids=node_ids,
                 include_answers=include_answers)


@mcp.tool()
def prepare_review_record(batch_id: str, transcript: str, source_key: str = 'pasted-chat') -> str:
    """Read only unprocessed TXT/chat delta and the batch's original questions.
    AI matches unlabelled answers; ambiguous items remain unmatched, not discarded.
    """
    return _call(_orch.prepare_review_record, batch_id=batch_id, transcript=transcript,
                 source_key=source_key)


@mcp.tool()
def commit_review_record(request_id: str, batch_id: str, attempts: list = None,
                         gaps: list = None, unmatched: list = None,
                         source_ticket: dict = None, recall_results: list = None,
                         source_updates: list = None) -> str:
    """Save external analysis once. attempts=[{question_id,kind:answer/explanation/
    confirmation,text,result?:pass/deepen,coverage?:[{node_id,...}],attempt_id?}].
    gaps=[{id,title,state:open/explained/resolved/deferred,parent_id?,question_id?,node_id?}].
    A child answer never automatically closes parent/sibling gaps or marks mastery.
    """
    return _call(_orch.commit_review_record, request_id=request_id, batch_id=batch_id,
                 attempts=attempts, gaps=gaps, unmatched=unmatched, source_ticket=source_ticket,
                 recall_results=recall_results, source_updates=source_updates)


@mcp.tool()
def prepare_content_task(operation: str, node_ids: list, profile: str = None,
                         strategy_id: str = None, goal: str = '', materials: list = None,
                         project_id: str = None, teaching_item_id: int = None) -> str:
    """Prepare note/lesson generation for selected existing nodes. Returns only
    selected bodies, materials and one strategy. The AI generates documents;
    commit_content_task publishes them using the returned compact ticket.
    """
    return _call(_orch.prepare_content_task, operation=operation, node_ids=node_ids,
                 profile=profile, strategy_id=strategy_id, goal=goal,
                 materials=materials, project_id=project_id, teaching_item_id=teaching_item_id)


@mcp.tool()
def relocate_node_content(request_id: str, node_id: str, target_ref: dict,
                           owner_ref: dict = None) -> str:
    """Move a node's formal body/maintainer to an already-readable block/point
    reference without changing its identity, graph edges, question links or dates.
    Old bodies and point aliases remain accessible; target content is prepared first.
    """
    return _call(_orch.relocate_node_content, request_id=request_id, node_id=node_id,
                 target_ref=target_ref, owner_ref=owner_ref)


@mcp.tool()
def commit_content_task(request_id: str, ticket: dict, documents: list,
                        edges: list = None, question_links: list = None) -> str:
    """Publish generated Markdown and its existing-node/question references in
    one transaction. documents=[{node_id,body,area?,source_refs?}]. Replaying the
    same request is safe. Returns IDs only; does not assess learning or schedule.
    """
    return _call(_orch.commit_content_task, request_id=request_id, ticket=ticket,
                 documents=documents, edges=edges, question_links=question_links)


@mcp.tool()
def get_review_map(root_id: str = None, project_id: str = None, domains: list = None,
                   learning_status: str = None, mastery: str = None,
                   include_extensions: bool = False, dependency_expansion: str = 'reference',
                   node_id: str = None, cursor: int = 0, limit: int = 20) -> str:
    """按项目/领域/掌握查询知识图摘要；扩展默认隐藏。
    dependency_expansion: reference/used_parts/full；展开依赖全树不增加必学范围。
    结果分页，不带正文。单点内容用 get_review_node。
    """
    return _call(_orch.get_review_map, root_id=root_id, project_id=project_id, domains=domains,
                 learning_status=learning_status, mastery=mastery, include_extensions=include_extensions,
                 dependency_expansion=dependency_expansion, node_id=node_id, cursor=cursor, limit=limit)


@mcp.tool()
def get_review_node(node_id: str, context_edge_id: str = None,
                    include_content: bool = False) -> str:
    """读取一个节点及公共/项目内掌握、旧排期；需要正文时才 include_content=True。"""
    return _call(_orch.get_review_node, node_id=node_id, context_edge_id=context_edge_id,
                 include_content=include_content)


@mcp.tool()
def record_review_assessment(request_id: str, assessments: list = None,
                             recall_results: list = None, question_id: str = None) -> str:
    """摸底记录 {node_id,context_edge_id?,mastery?,learning_status?,gap_note?,basis?}。
    mastery:unassessed/weak/usable/solid；learning_status:unknown/not_started/learning/learned。
    仅实际复述时给 recall_results:[{node_id,result:correct/partial/wrong,hint_level?,note?}]，
    才推进旧排期。题目判断不广播给所有关联点。一次提交只回小回执。
    """
    return _call(_orch.record_review_assessment, request_id=request_id, assessments=assessments,
                 recall_results=recall_results, question_id=question_id)


@mcp.tool()
def review_graph_today(project_id: str = None, domains: list = None, limit: int = 15) -> str:
    """统一知识点复习卡：沿用旧日期，同一规范知识点只出一次，明确未学的排除。"""
    return _call(_orch.review_graph_today, project_id=project_id, domains=domains, limit=limit)


if __name__ == "__main__":
    main()
