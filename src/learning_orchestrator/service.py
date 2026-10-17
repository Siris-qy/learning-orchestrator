"""Orchestrator: the single facade used by the MCP server, the dashboard,
and the tests. Wraps one SQLite connection plus config (source roots)."""

import json
import os
from pathlib import Path

from . import context as context_mod
from . import graph, progress, seed as seed_mod, sessions, sources
from .db import connect, dicts, transaction
from .graph import ValidationError, now_iso


class Orchestrator:
    def __init__(self, db=None, source_roots=None, a2a_root="auto",
                 bagu_root="auto", workspace=None):
        from .workspace import load
        self.workspace = load(workspace)
        if self.workspace:
            db = db or self.workspace['database']
            source_roots = source_roots if source_roots is not None else self.workspace['source_roots']
            if self.workspace['seed'] != 'legacy':
                a2a_root = None if a2a_root == 'auto' else a2a_root
                bagu_root = None if bagu_root == 'auto' else bagu_root
        elif source_roots is None and os.environ.get('LEARNING_ORCHESTRATOR_SOURCE_ROOTS'):
            source_roots = os.environ['LEARNING_ORCHESTRATOR_SOURCE_ROOTS'].split(os.pathsep)
        self.conn = connect(db)
        from . import teaching
        teaching.setup(self.conn)
        from . import skeletons
        skeletons.setup(self.conn)
        from . import review
        review.setup(self.conn)
        from . import questions
        questions.setup(self.conn)
        from . import organize
        organize.setup(self.conn)
        from . import knowledge
        knowledge.setup(self.conn)
        from . import review_graph
        review_graph.setup(self.conn)
        from . import production
        production.setup(self.conn)
        from . import question_batch
        question_batch.setup(self.conn)
        from . import review_batches
        review_batches.setup(self.conn)
        from . import curricula
        curricula.setup(self.conn)
        from . import documents, workflow_board
        documents.setup(self.conn)
        workflow_board.setup(self.conn)
        from .seed_a2a import default_repo_root
        if a2a_root == "auto":
            candidate = default_repo_root()
            self.a2a_root = candidate if candidate.is_dir() else None
        else:
            self.a2a_root = Path(a2a_root) if a2a_root else None
        from . import seed_bagu
        if bagu_root == "auto":
            candidate = seed_bagu.default_corpus_root()
            self.bagu_root = candidate if candidate.is_dir() else None
        else:
            self.bagu_root = Path(bagu_root) if bagu_root else None
        if source_roots is None:
            from .db import DEFAULT_SOURCE_ROOT
            source_roots = [DEFAULT_SOURCE_ROOT]
            if self.a2a_root and self.a2a_root.is_dir():
                source_roots.append(self.a2a_root)
            if self.bagu_root and self.bagu_root.is_dir():
                source_roots.append(self.bagu_root)
        self.source_roots = [str(r) for r in source_roots]
        from .workflow import StrategyRegistry
        self._strategies = StrategyRegistry()
        if self.workspace:
            import importlib
            for module in self.workspace['strategy_modules']:
                extension = importlib.import_module(module)
                extension.register(self)

    def close(self):
        self.conn.close()

    def teaching_workspace(self, course_id, section_id=None):
        from . import teaching
        return teaching.read(self.conn, course_id, section_id)

    def commit_teaching_turn(self, **kwargs):
        from .operation_handlers import learning_turn
        return learning_turn(self, **kwargs)

    def save_teaching_plan(self, course_id, section_id, milestones, created_by='main', stage_key=None):
        from .workflow_compat import invoke
        return invoke(self, 'plan.save', course_id=course_id, section_id=section_id,
                      milestones=milestones, created_by=created_by, stage_key=stage_key)

    def get_teaching_state(self, course_id, full=False, records_for_item=None,
                           after_id=0, limit=5, analysis_id=None):
        """Window recovery: plan outline, cursor, open questions (compact by
        default; full=True only for acceptance/review)."""
        from . import teaching
        if analysis_id is not None:
            from . import learning_records
            return learning_records.read_analysis(self.conn, course_id, analysis_id)
        if records_for_item is not None:
            return teaching.records_for_item(self.conn, course_id, records_for_item,
                                             after_id, limit)
        return teaching.get_state(self.conn, course_id, full)

    def prepare_learning_record(self, course_id, section_id=None, path=None,
                                transcript=None, source_ref=None, offset=0,
                                max_chars=10000):
        from . import learning_records
        return learning_records.prepare(self.conn, self.source_roots, course_id,
                                       section_id, path, transcript, source_ref,
                                       offset, max_chars)

    def get_teaching_tree(self, course_id):
        """Active plan's full item tree for the page (teaching AI keeps using
        the compact profiles; this is the page-side tree)."""
        from . import teaching
        return teaching.get_tree(self.conn, course_id)

    def get_learning_tree(self, course_id):
        """Course→modules→units→objectives with teaching branches and topic
        records for the global learning tree view. Structure + counts; unit
        records lazy-load via get_node_detail."""
        return progress.learning_tree(self.conn, course_id)

    def code_structure(self, course_id, top=None):
        """Page-side code view: directory containment over indexed code
        sources (top=None → summary; top=<dir> → files+symbols), plus the
        skeleton group. Containment only — no inferred call edges."""
        from . import code_index
        return code_index.structure(self.conn, course_id, top)

    # -- cross-view organization (2026-09-23 收敛轮) -------------------------
    def get_code_map(self, course_id):
        """The course's approved architecture map (Archify preview JSON +
        authored component details) with per-component cross-view links."""
        from . import organize
        return organize.get_code_map(self.conn, course_id)

    def knowledge_catalog(self, course_id):
        """知识入口目录: knowledge positions (skeleton anchors with their
        real-source index; review knowledge points with note anchors) plus the
        registered sources with roles. Blocks carry cross-view links; content
        loads lazily via knowledge_item. Unlinked blocks stay honestly so."""
        from . import bagu_catalog, organize, review, seed_bagu, skeletons, knowledge, presentation
        blocks = []
        extra = (bagu_catalog.blocks(self.conn)
                 if course_id == seed_bagu.COURSE_ID else [])
        related = {}
        for block in extra:
            for point_id in block['points']:
                related.setdefault(point_id, []).append({
                    'kind': 'knowledge', 'id': block['id'], 'basis': 'manual',
                    'note': '笔记正文引用 ' + point_id, 'dir': 'out'})
        for sk in skeletons.list_skeletons(self.conn, course_id=course_id):
            for m in sk['map']:
                kid = '%s#%s' % (sk['source_id'], m['skeleton_anchor'])
                blocks.append({
                    'id': kid, 'kind': 'skeleton-anchor',
                    'title': m['skeleton_anchor'],
                    'group': sk['title'], 'ref': m['real_ref'],
                    'note': m['note'], 'claim_id': m['claim_id'],
                    'links': organize.links_for(self.conn, course_id,
                                                'knowledge', kid)})
        for r in review.iter_items(self.conn, course_id):
            kid = 'review:%s' % r['id']
            blocks.append({
                'id': kid, 'kind': 'review-point',
                'title': '%s %s' % (r['point_id'], r['title']),
                'group': r['source_title'], 'ref': r['anchor'],
                'note': '', 'status': r['status'],
                'links': (organize.links_for(self.conn, course_id,
                                             'knowledge', kid)
                          + related.get(r['point_id'], []))})
        for block in extra:
            blocks.append({key: block[key] for key in
                           ('id', 'kind', 'title', 'group', 'ref', 'note')})
        seen = set()
        for view in ('project:' + course_id, 'course:' + course_id):
            for b in knowledge.catalog(self.conn, view):
                if b['id'] in seen:
                    continue
                seen.add(b['id'])
                blocks.append({'id': b['id'], 'kind': 'wiki-block', 'title': b['title'],
                               'group': ' / '.join(b['path']), 'ref': b['id'],
                               'note': '增量知识块 · %s 条补充' % b['entry_count'], 'links': []})
        counts = {r[0]: r[1] for r in self.conn.execute(
            'SELECT source_id, COUNT(*) FROM chunks GROUP BY source_id')}
        src_list = [{'id': s['id'], 'title': s['title'],
                     'lecture_ref': s['lecture_ref'], 'note': s['note'],
                     'chunks': counts.get(s['id'], 0)}
                    for s in self.list_sources(course_id)]
        source_titles = {s['title']: presentation.source_name(s['id'], s['title']) for s in src_list}
        for b in blocks:
            if b['kind'] == 'project-anchor':
                b.update(presentation.module_name(b['id'], b['title']))
            elif b['kind'] == 'review-point':
                b['original_title'] = b['title']
                b['title'] = presentation.point_title(b['title'])
            if b.get('group') in source_titles:
                b['original_group'] = b['group']
                b['group'] = source_titles[b['group']]['title']
        for s in src_list:
            s.update(presentation.source_name(s['id'], s['title']))
        return {'course_id': course_id, 'blocks': blocks,
                'sources': src_list}

    def knowledge_item(self, course_id, item_id):
        """One knowledge position's content. review point → its own note-body
        chunk (same discipline as review.prepare); skeleton anchor → the map
        row plus best-effort matching chunks (labelled 近似 when inexact)."""
        from . import bagu_catalog, organize, review, seed_bagu
        if item_id.startswith('wiki:'):
            from . import knowledge
            return {'id': item_id, 'kind': 'wiki-block',
                    'wiki': knowledge.read(self.conn, item_id[5:])}
        if course_id == seed_bagu.COURSE_ID and item_id.startswith(
                ('project:', 'question:')):
            detail = bagu_catalog.detail(self.conn, item_id)
            if detail is None:
                raise ValidationError('Unknown knowledge item: ' + item_id)
            return detail
        if item_id.startswith('review:'):
            r = review.prepare(self.conn, int(item_id.split(':', 1)[1]))
            return {'id': item_id, 'kind': 'review-point', 'prepare': r,
                    'links': (organize.links_for(self.conn, course_id,
                                                 'knowledge', item_id)
                              + (bagu_catalog.related(self.conn, r['point_id'])
                                 if course_id == seed_bagu.COURSE_ID else []))}
        source_id, _, anchor = item_id.partition('#')
        words = [w for w in anchor.replace('()', ' ').split(' / ') if w]
        rows = self.conn.execute(
            'SELECT anchor, text FROM chunks WHERE source_id=? ORDER BY id',
            (source_id,)).fetchall()
        scored = []
        for row in rows:
            sym = row['anchor'].split(' · ', 1)[-1]
            score = sum(1 for w in words if w in sym or w in row['text'])
            if score:
                scored.append((score, dict(row)))
        scored.sort(key=lambda x: -x[0])
        exact = any(anchor.split(' / ')[0] in s[1]['anchor'] for s in scored[:1])
        return {'id': item_id, 'kind': 'skeleton-anchor',
                'chunks': [s[1] for s in scored[:3]],
                'match': 'exact' if exact else 'approximate',
                'links': organize.links_for(self.conn, course_id,
                                            'knowledge', item_id)}

    def prepare_teaching(self, course_id, role='main', section_id=None,
                         focused_question=None, profile=None, include_lesson=False,
                         lesson_scope='subsection', learning_route=None):
        """Assemble teaching context by scenario, not by role (final wording §三).

        profile:
        - local:    current position/questions; include_lesson optionally loads
                    saved background for subsection, section or unit, once.
        - resume:   window takeover — plan outline, cursor, open questions,
                    topic summary. No context pack, no full history.
        - step:     in-stage advance — current item with children, its open
                    questions, next pending milestone, small context pack.
        - question: local follow-up — only the focused-question context pack.
        - review:   stage handoff/acceptance — full state + full history.
        Default: 'question' when focused_question is given, else 'resume'.
        """
        from . import teaching
        if profile == 'local':
            result = teaching.local_state(self.conn, course_id)
            result['profile'] = 'local'
            from . import learning_records
            result['record_sync'] = learning_records.check_bound_record(
                self.conn, self.source_roots, course_id, result['section_id'])
            if include_lesson and result['current_item']:
                if lesson_scope == 'subsection':
                    result['lesson'] = self.get_lesson_artifact(
                        result['section_id'], teaching_item_id=result['current_item']['id'])
                elif lesson_scope in ('section', 'unit'):
                    result['lesson_background'] = self._teaching_lesson_background(
                        course_id, result, lesson_scope)
                else:
                    raise ValidationError('lesson_scope must be subsection, section or unit')
            return result
        shared = self.teaching_workspace(course_id, section_id)
        sid = section_id or shared['section_id']
        if not sid:
            resumed = sessions.resume_session(self.conn, course_id=course_id)
            sid = resumed['current_node']['id'] if resumed else self.suggest_next_action(course_id)['node_id']
            shared = self.teaching_workspace(course_id, sid)
        if profile is None:
            profile = 'question' if focused_question else 'resume'
        if profile not in ('resume', 'step', 'question', 'review'):
            raise ValidationError('invalid prepare profile: %r' % profile)
        state = teaching.get_state(self.conn, course_id)
        if section_id is None and state['section_id']:
            sid = state['section_id']
        nav = state['navigation'] or {}
        result = {'profile': profile, 'section_id': sid,
                  'state_version': state['state_version'],
                  'workspace': state['workspace'], 'cursor': state['cursor'],
                  'navigation': state['navigation'],
                  'next_item': nav.get('next_item'),
                  'next_milestone': nav.get('next_milestone'),
                  'stagnation': teaching.stagnation_hint(self.conn, course_id, sid)}
        if profile in ('resume', 'step'):
            result['reminders'] = state['reminders']
        if profile == 'resume':
            from . import learning_records
            result['record_sync'] = learning_records.check_bound_record(
                self.conn, self.source_roots, course_id, sid)
        if profile in ('resume', 'step'):
            # M2: a registered skeleton on this section is part of the
            # position picture (id/title/state only; index via list_skeletons).
            from . import skeletons
            result['skeleton'] = skeletons.brief_for_node(self.conn, sid)
        if profile == 'resume':
            result['knowledge_capture'] = {
                'when': '由主讲在接手整理交接时追加知识；细节讲解不在本轮整理正文。',
                'workflow': 'list_knowledge_library 找已有块 → append_knowledge 保存补充与来源、展示位置；内容稳定后 consolidate_knowledge。',
                'legacy': '已有笔记使用 source:<source_id> 续写同一块，正文留在原处。',
                'scope': '保存可复习解释，保留待确认问题；不把讲过转换为掌握，不每轮读全量历史。'}
            result.update(plan=state['plan'], milestones=state['milestones'],
                          current_item=state['current_item'],
                          navigation=state['navigation'],
                          questions=state['questions'],
                          handoff=state['handoff'],
                          topics=state['topics'])
            result['teaching_strategy'] = self._teaching_strategy(course_id, learning_route)
            # 课程简纲：只有阶段标题与状态，不给远期小项/教案（组织层）
            from . import organize
            result['outline'] = [
                {'stage_key': s['stage_key'], 'title': s['title'],
                 'status': s['status'], 'goal': s['goal']}
                for s in organize.get_outline(self.conn, course_id)]
        elif profile == 'step':
            result.update(current_item=state['current_item'],
                          navigation=state['navigation'],
                          questions=state['questions'])
            # 批次提示（2026-09-25 节层定稿）：节是单元内的分组标题，小节是
            # 学习条目（记录粒度），批次是输出粒度，数量按材料与用户负荷定；
            # step 为需要材料的备课/可选直接讲解提供目录；记录整理使用 local，
            # 不必每轮重复取目录和材料。讲义输出 ≠ 用户理解。
            cur = state.get('current_item') or {}
            outline = None
            if state.get('plan') and cur.get('id'):
                outline = teaching.unit_outline(
                    teaching._items(self.conn, state['plan']['id']),
                    cur['id'])
            cur_section = None
            if outline and outline.get('current_section'):
                cur_section = next(
                    (s for s in outline['sections']
                     if s['id'] == outline['current_section']), None)
            result['batch'] = {
                'item': {'id': cur.get('id'), 'title': cur.get('title'),
                         'status': cur.get('status')},
                'section': ({'id': cur_section['id'],
                             'title': cur_section['title']}
                            if cur_section else None),
                'sub_items': (cur_section['subs'] if cur_section
                              else cur.get('children') or []),
                'unit_outline': outline,
                'rule': ('当前教案作为完整背景，按内容与用户负荷分批讲，不固定小节数；'
                         '输出讲义标 presented，验证通过才由 main 标 done；'
                         '结构变动（改名/排序/作废/分节）请 main 执行；'
                         '追问挂在小节下，游标留在小节；用户确认后才结束讨论。')}
            result['context'] = self.build_context_pack(sid, 'clarify',
                                                        focused_question)
        elif profile == 'question':
            result['context'] = self.build_context_pack(sid, 'clarify',
                                                        focused_question)
        else:  # review
            result['state'] = teaching.get_state(self.conn, course_id, full=True)
            result['context'] = self.build_context_pack(
                sid, 'clarify' if role in ('clarify', 'detail') else 'intro',
                focused_question)
        return result

    # 2026-09-24 讲解纪律：阶段路线 + 小项/批次 + 递归返回，所有课程通用。
    _FLOW_RULES = {
        'workflow': '主讲备课并保存教案 → 外部快速窗口讲解 → 本地分析学习记录并同步 → 恢复或继续。',
        'lesson_rule': ('教案包含范围标识、小节ID与目录、必要背景、自包含解释/例子/代码或图示、'
                        '材料索引与建议分批方式；数量由内容决定。保存教案只表示备课，不表示已讲或理解。'),
        'batch_rule': ('层级：阶段(milestone) → 单元(sub) → 节(section) → 小节'
                       '(学习条目) → 小项(追问记录)。节是单元内的分组标题；'
                       '完整教案是背景，单次输出按内容与用户负荷拆分，不固定小节数，等用户'
                       '理解/追问反馈再推进；讲义已输出标 presented（已讲解），'
                       '不代表已理解；done 仅由 main 结合验证标记。结构修改'
                       '（改名/排序/作废/分节）仅 main 执行，detail 先提出。'),
        'recurse_rule': ('游标停在小节；追问可递归挂在小节或父问题下，只记简短状态。'
                         '讲过标 awaiting_confirmation，用户确认才 resolved；'
                         '子问题结束不自动结束父项。暂缓不强制清零。'),
        'write_rule': ('用户提交/更新学习记录或接手续学时按需分析增量；复用已有条目，'
                       '合并保存追问、确认和小节游标。无需每问一句调用插件。'
                       '报告当前位置、本次确认、讲过未确认项及下次起点；用户自述理解不等于验证通过。'),
    }

    def _teaching_strategy(self, course_id, learning_route=None):
        # Explicit selection wins. Code maps/sources are lightweight project
        # hints, not a schema migration or an assumption that every skeleton
        # belongs to a project (authored courses may have teaching code too).
        if learning_route not in (None, 'project', 'course'):
            raise ValidationError('learning_route must be project or course')
        project = learning_route == 'project'
        if learning_route is None:
            from .curricula import kind
            project = (kind(self.conn, course_id) == 'project' or bool(self.conn.execute(
                "SELECT 1 FROM code_maps WHERE course_id=? UNION ALL "
                "SELECT 1 FROM sources WHERE course_id=? AND note='code' LIMIT 1",
                (course_id, course_id)).fetchone()))
        if project:
            strategy = {
                'kind': 'project_onion',
                **Orchestrator._FLOW_RULES,
                'stage_flow': ('必要基础 → 最简完整教学骨架 → 真实源码对照；'
                               '先建立最小完整功能再扩展，复习时可用完整主链串联。'),
                'preserve_existing_progress': True,
            }
            # Project-specific order belongs to its saved plan/materials, not
            # application defaults. Registered projects use this same route.
            return strategy
        return {
            'kind': 'authored_course',
            **Orchestrator._FLOW_RULES,
            'stage_flow': '按教材/课件范围备课：概念与机制 → 例子/推演 → 练习；不强制骨架或源码对照。',
            'order': 'Follow slide, notes, and textbook headings.',
        }

    # -- setup -------------------------------------------------------------
    def initialize(self):
        """Initialize the selected workspace; legacy defaults stay compatible."""
        if self.workspace and self.workspace['seed'] != 'legacy':
            if self.workspace['seed'] == 'demo':
                from .workspace import seed_demo
                return seed_demo(self)
            return {'seeded': False, 'courses': graph.list_courses(self.conn)}
        seeded = seed_mod.seed(self.conn)
        result = {"seeded": seeded,
                  "courses": [c["id"] for c in graph.list_courses(self.conn)]}
        from . import seed_a2a
        a2a = seed_a2a.seed(self.conn, self.a2a_root)
        result["a2a"] = a2a
        from . import seed_bagu
        result["bagu"] = seed_bagu.seed(self.conn, self.bagu_root)
        from . import seed_a2a_org
        result["a2a_org"] = seed_a2a_org.seed(self.conn)
        return result

    def realign_a2a_records(self):
        """2026-09-24 讲解重构：把 A2A 旧记录挂到 plan v2 教学小项，
        并按 讲授≠验证 语义把误标的 done 降为 presented。
        幂等、带证据校验；不在 initialize 内自动跑（只动真实库）。"""
        from . import seed_a2a_org
        return seed_a2a_org.realign_records(self.conn)

    def restructure_plugin_unit(self):
        """2026-09-25 节层上线：插件单元 3 节 × 4 小节结构清理。
        作废重复项留痕、正式 12 小节去硬序号并归位；幂等、带证据校验。"""
        from . import seed_a2a_org
        return seed_a2a_org.restructure_plugin_unit(self.conn)

    # -- interview question bank (R2, 2026-09-24) ---------------------------
    def migrate_interview_questions(self):
        """一次性幂等迁移：24 题组 → 结构化题库 + 素材池台账。显式服务入
        口，不进 initialize；先校验再写入。"""
        from . import seed_interview_questions
        return seed_interview_questions.migrate(self.conn)

    def query_questions(self, course_id, text=None, group=None, point_id=None,
                        project_ref=None):
        """结构化题库检索入口。新面经先查这里再决定登记；查不到再扫素材
        池（material_pool）。"""
        from . import questions
        return questions.search_questions(self.conn, course_id, text, group,
                                          point_id, project_ref)

    def get_question_detail(self, question_id):
        """单题全貌：题干/问法/上下文/答案依据/来源/知识归属/项目/判断状
        态。判断状态只是最新一行判断记录；没有记录 = 未判断。"""
        from . import questions
        return questions.get_question(self.conn, question_id)

    def add_interview_question(self, course_id, stem, group_key='',
                               variants=None, context='', answer_basis='',
                               source_lines=None, points=None, projects=None,
                               origin='manual'):
        """登记新面经题。先去重：题干或问法命中已有题则补充
        variants/source_ref（合并不新建）；确实没有才建新题（手工题用
        q-x- 前缀，避开迁移题的 q-n*/q-c*）。等级与掌握独立，登记不推断
        掌握。"""
        from . import questions
        matches = questions.search_questions(self.conn, course_id, text=stem)
        if not matches:
            for v in variants or []:
                matches = questions.search_questions(self.conn, course_id,
                                                     text=v)
                if matches:
                    break
        if matches:
            hit = matches[0]
            result = questions.merge_variants(
                self.conn, hit['id'],
                variants=[stem] + list(variants or []),
                source_lines=source_lines, origin=origin)
            result['created'] = False
            return result
        seq = self.conn.execute(
            "SELECT COUNT(*) FROM questions WHERE id LIKE 'q-x-%'"
        ).fetchone()[0] + 1
        qid = 'q-x-%03d' % seq
        while self.conn.execute('SELECT 1 FROM questions WHERE id=?',
                                (qid,)).fetchone():
            seq += 1
            qid = 'q-x-%03d' % seq
        source_ref = {'file': '面经.txt',
                      'lines': sorted(source_lines or [])} if source_lines \
            else {}
        return questions.add_question(
            self.conn, course_id, stem, qid, group_key=group_key,
            variants=variants, context=context, answer_basis=answer_basis,
            source_ref=source_ref, points=points, projects=projects,
            origin=origin)

    def upgrade_firsthand(self, question_id, interviewed_at,
                          actual_wording='', followups=''):
        """亲历题升级：复用原条目（不重复建题），记录日期、实际问法与追
        问。只改等级，不触碰判断记录——亲历≠掌握。"""
        from . import questions
        return questions.upgrade_firsthand(self.conn, question_id,
                                           interviewed_at, actual_wording,
                                           followups)

    def record_question_judgment(self, question_id, result, gap_note='',
                                 origin='', answer_summary='', teaching_item_id=None):
        """题目判断（pass/deepen），append-only，当前判断=最新一行。服务
        层留口；判断只能来自用户实际作答，不由工具推断。"""
        from . import questions
        return questions.record_judgment(self.conn, question_id, result,
                                         gap_note, origin, answer_summary, teaching_item_id)

    def link_teaching_knowledge(self, item_id, knowledge_course_id, point_id, note=''):
        from . import questions
        return questions.link_teaching_knowledge(self.conn, item_id, knowledge_course_id, point_id, note)

    def knowledge_connections(self, knowledge_course_id, point_id):
        from . import questions
        return questions.knowledge_connections(self.conn, knowledge_course_id, point_id)

    def append_knowledge(self, **kwargs):
        from . import knowledge
        return knowledge.append(self.conn, **kwargs)

    def get_knowledge_block(self, block_id, include_history=False):
        from . import knowledge
        return knowledge.read(self.conn, block_id, include_history)

    def place_knowledge(self, block_id, view_key, path, seq=0):
        from . import knowledge
        return knowledge.place(self.conn, block_id, view_key, path, seq)

    def consolidate_knowledge(self, block_id, content, covered_entry_ids):
        from . import knowledge
        return knowledge.consolidate(self.conn, block_id, content, covered_entry_ids)

    def relate_knowledge(self, from_id, to_id, relation='related', note=''):
        from . import knowledge
        return knowledge.relate(self.conn, from_id, to_id, relation, note)

    def knowledge_library(self):
        from . import knowledge
        return knowledge.library(self.conn)

    def search_knowledge_points(self, query, limit=20):
        from . import knowledge_points
        return knowledge_points.search(self.conn, query, limit)

    def get_knowledge_point(self, point_id):
        from . import knowledge_points
        result = knowledge_points.read(self.conn, point_id)
        from . import content
        relocated = content.resolve(self.conn, {'type': 'knowledge_point', 'id': point_id})
        if relocated['body']:
            result['text'] = relocated['body']
            result['resolved_content_ref'] = relocated['content_ref']
        from . import review_graph
        result['review_connections'] = review_graph.connections(self.conn, point_id)
        return result

    def relate_knowledge_points(self, from_id, to_id, relation='related', note=''):
        from . import knowledge_points
        return knowledge_points.relate(self.conn, from_id, to_id, relation, note)

    # -- interview knowledge graph: one facade for MCP and page --------------
    def resolve_review_mentions(self, mentions, project_id=None, limit_per_mention=5):
        from . import review_graph
        return review_graph.resolve(self.conn, mentions, project_id, limit_per_mention)

    def commit_review_map(self, **kwargs):
        from .workflow_compat import invoke
        return invoke(self, 'graph.commit', **kwargs)

    def get_review_map(self, **kwargs):
        from . import review_graph
        return review_graph.get_map(self.conn, **kwargs)

    def get_review_node(self, node_id, context_edge_id=None, include_content=False):
        from . import review_graph
        return review_graph.get_node(self.conn, node_id, context_edge_id, include_content)

    def get_review_detail(self, node_id, project_id=None, top_k=5):
        """Published body, direct relations and questions in the selected scope."""
        from . import review_views
        return review_views.detail(self.conn, node_id, project_id, top_k)

    def list_content_strategies(self):
        return [s for s in self._strategies.describe(include_instructions=True)
                if s.get('operation') in ('note.publish', 'lesson.publish')]

    def register_workflow_strategy(self, strategy_id, operation, instructions,
                                   prepare=None, transform=None, profile=None):
        self._strategies.register(strategy_id, operation, instructions, prepare, transform, profile)

    def get_workflow_contract(self, operation=None):
        from . import workflow
        return workflow.available(self, operation)

    def get_workflow_board(self, project_id=''):
        from . import workflow_board
        return workflow_board.board(self, project_id)

    def save_workflow_controls(self, **kwargs):
        from . import workflow_board
        return workflow_board.save(self, **kwargs)

    def save_constraint_module(self, **kwargs):
        from . import workflow_board
        return workflow_board.save_module(self, **kwargs)

    def save_workflow_task(self, **kwargs):
        from . import workflow_board
        return workflow_board.save_task(self, **kwargs)

    def get_workflow_task(self, document_id):
        from . import workflow_board
        return workflow_board.read_task(self, document_id)

    def list_documents(self, **kwargs):
        from . import documents
        return documents.listing(self, **kwargs)

    def save_document(self, **kwargs):
        from . import documents
        return documents.save(self, **kwargs)

    def read_document(self, **kwargs):
        from . import documents
        return documents.read(self, **kwargs)

    def document_versions(self, document_id):
        from . import documents
        return documents.versions(self, document_id)

    def register_curriculum(self, **kwargs):
        from .workflow_compat import invoke
        return invoke(self, 'curriculum.register', **kwargs)

    def prepare_workflow(self, **kwargs):
        from . import workflow
        return workflow.prepare(self, **kwargs)

    def commit_workflow(self, **kwargs):
        from . import workflow
        return workflow.commit(self, **kwargs)

    def prepare_content_task(self, **kwargs):
        from . import production
        return production.prepare(self, **kwargs)

    def commit_content_task(self, **kwargs):
        from .workflow_compat import invoke
        return invoke(self, kwargs['ticket']['operation'] + '.publish', **kwargs)

    def relocate_node_content(self, **kwargs):
        from . import content
        return content.relocate(self.conn, **kwargs)

    def save_review_batch(self, **kwargs):
        from .workflow_compat import invoke
        return invoke(self, 'review.save', **kwargs)

    def commit_question_batch(self, **kwargs):
        from .workflow_compat import invoke
        return invoke(self, 'questions.commit', **kwargs)

    def list_review_batches(self, project_id=None):
        from . import review_batches
        return review_batches.listing(self.conn, project_id)

    def get_review_batch(self, batch_id):
        from . import review_batches
        return review_batches.read(self.conn, batch_id)

    def export_review_batch(self, batch_id, node_ids=None, include_answers=False):
        from . import review_batches
        return review_batches.export(self.conn, batch_id, node_ids, include_answers)

    def prepare_review_record(self, batch_id, transcript, source_key='pasted-chat'):
        from . import review_batches
        return review_batches.prepare_record(self.conn, batch_id, transcript, source_key)

    def commit_review_record(self, **kwargs):
        from .workflow_compat import invoke
        return invoke(self, 'record.review', **kwargs)

    def record_review_assessment(self, **kwargs):
        from .workflow_compat import invoke
        return invoke(self, 'assessment.record', **kwargs)

    def review_graph_today(self, project_id=None, domains=None, limit=15):
        from . import review_graph
        return review_graph.today(self.conn, project_id, domains, limit)

    def question_pool_status(self, source_id=None):
        """素材池迁移台账：每个 (source, section) 的迁移状态与已迁出的题
        id 列表。"""
        from . import questions
        return questions.pool_status(self.conn, source_id)

    def review_cockpit(self, course_id):
        """复习座舱装配（R1）：基础八股分组 + 项目模块与通路 + 题目三档
        判断（未判断/基本通过/需要深入）。页面事实源，不维护第二份副本。"""
        from . import cockpit
        return cockpit.cockpit(self.conn, course_id)

    # -- review (M3) ---------------------------------------------------------
    def review_today(self, course_id, limit=15, on=None):
        """Today's review menu (cap, not quota): due items most-overdue
        first, then unknown points to fill capacity."""
        from . import review
        return review.today(self.conn, course_id, limit, on)

    def review_overview(self, course_id):
        from . import review
        return review.overview(self.conn, course_id)

    def prepare_review(self, review_item_id):
        """The point's own knowledge-block chunk for building a closed-book
        question. Index files/snippets are not the textbook."""
        from . import review
        return review.prepare(self.conn, review_item_id)

    def record_review(self, review_item_id, result, hint_level=0, note='',
                      when=None):
        """correct(hint<=1)→level+1; partial/hinted→level-1; wrong→0, next
        day. No overdue penalty; unfinished rolls over."""
        from . import review
        return review.record(self.conn, review_item_id, result, hint_level,
                             note, when)

    # -- skeletons (M2, TODO §8.1) -------------------------------------------
    def register_skeleton(self, course_id, node_id, path, title=None):
        """Register one complete skeleton file for a unit (imports it as a
        code source, attaches it to the node, opens state 'prepared')."""
        from . import skeletons
        return skeletons.register(self.conn, course_id, node_id, path,
                                  self.source_roots, title)

    def set_skeleton_state(self, skeleton_id, state, note=''):
        from . import skeletons
        return skeletons.set_state(self.conn, skeleton_id, state, note)

    def add_skeleton_map(self, skeleton_id, entries):
        """Skeleton→real-source index rows: {skeleton_anchor, claim_id?,
        real_ref, note} — note carries the boundary declaration."""
        from . import skeletons
        return skeletons.add_map(self.conn, skeleton_id, entries)

    def list_skeletons(self, course_id=None, node_id=None):
        from . import skeletons
        return skeletons.list_skeletons(self.conn, course_id, node_id)

    # -- read views --------------------------------------------------------
    def list_courses(self):
        from . import presentation
        from . import curricula
        rows = graph.list_courses(self.conn)
        for r in rows:
            r['display_title'] = presentation.course_title(r['id'], r['title'])
            r['kind'] = curricula.kind(self.conn, r['id'])
            r['library_view_key'] = r['kind'] + ':' + r['id']
        return rows

    def meta(self):
        """Diagnostics: which database file this process actually serves.

        Surfaces wrong-DB / stale-process mixups (TODO §1) without exposing
        anything beyond what a local single-user dashboard already shows.
        """
        row = self.conn.execute("PRAGMA database_list").fetchone()
        return {"db_path": row["file"] if row else "", "pid": os.getpid()}

    def get_graph(self, course_id, edge_types=None):
        from . import presentation
        result = graph.get_graph(self.conn, course_id, edge_types)
        for node in result['nodes']:
            if node['type'] == 'course':
                node['display_title'] = presentation.course_title(node['id'], node['title'])
        return result

    def get_dashboard(self, course_id):
        return progress.dashboard(self.conn, course_id)

    def suggest_next_action(self, course_id):
        return progress.suggest_next_action(self.conn, course_id)

    def get_node_detail(self, node_id):
        node = graph.get_node(self.conn, node_id)
        from . import organize
        links = organize.links_for(self.conn, node["course_id"],
                                   'node', node_id)
        recent = dicts(self.conn.execute(
            "SELECT ts, type, payload FROM events WHERE node_id = ?"
            " ORDER BY id DESC LIMIT 10", (node_id,)))
        for r in recent:
            r["payload"] = json.loads(r["payload"])
        misc = dicts(self.conn.execute(
            "SELECT id, text, signature, status, created_at"
            " FROM misconceptions WHERE node_id = ? ORDER BY id DESC LIMIT 10",
            (node_id,)))
        return {
            "node": node,
            "published_note": bool(self.conn.execute(
                "SELECT 1 FROM review_graph_nodes WHERE id=? AND json_extract(payload,'$.content_ref') IS NOT NULL",
                (node_id,)).fetchone()),
            "parents": graph.parents_of(self.conn, node_id),
            "prerequisites": graph.prerequisites_of(self.conn, node_id),
            "sources": sources.sources_for_node(self.conn, node_id),
            "misconceptions": misc,
            "claims": graph.list_claims(self.conn, node_id=node_id),
            "links": links,
            "recent_events": recent,
            "lesson_artifacts": {
                m: self.get_lesson_artifact(node_id, m)
                for m in ("intro", "clarify", "review")
            },
        }

    # -- sessions ----------------------------------------------------------
    def start_session(self, course_id, root_node_id, mode, goal=""):
        sid = sessions.start_session(self.conn, course_id, root_node_id,
                                     mode, goal)
        return sessions.resume_session(self.conn, session_id=sid)

    def resume_session(self, course_id=None):
        res = sessions.resume_session(self.conn, course_id=course_id)
        if res is None:
            return {"active_session": None,
                    "suggestion": self.suggest_next_action(course_id)
                    if course_id else None}
        return {"active_session": res}

    def push_node(self, session_id, node_id, reason=""):
        return sessions.push_node(self.conn, session_id, node_id, reason)

    def pop_node(self, session_id, reason=""):
        return sessions.pop_node(self.conn, session_id, reason)

    def finish_session(self, session_id, summary="", abandon=False):
        return sessions.finish_session(self.conn, session_id, summary, abandon)

    def record_source_coverage(self, session_id, node_id, source_id, anchor=""):
        sessions.record_source_coverage(self.conn, session_id, node_id,
                                        source_id, anchor)
        return {"recorded": True}

    def record_attempt(self, session_id, node_id, result, hint_level=0,
                       response_summary="", mistake_signatures=None,
                       batch_id=None, record_kind=None):
        sessions.record_attempt(self.conn, session_id, node_id, result,
                                hint_level, response_summary,
                                mistake_signatures, batch_id, record_kind)
        return {"recorded": True}

    def record_note(self, session_id, node_id, text, batch_id=None,
                    record_kind=None):
        """Process record attached to a node (TODO §8.5: questions while
        copying, time spent — reviewable per node afterwards)."""
        sessions.record_note(self.conn, session_id, node_id, text,
                             batch_id, record_kind)
        return {"recorded": True}

    def record_misconception(self, session_id, node_id, text, signature=""):
        mid = sessions.record_misconception(self.conn, session_id, node_id,
                                            text, signature)
        return {"misconception_id": mid}

    def resolve_misconception(self, misconception_id):
        sessions.resolve_misconception(self.conn, misconception_id)
        return {"resolved": True}

    def session_timeline(self, session_id, limit=50):
        return sessions.session_timeline(self.conn, session_id, limit)

    def recent_sessions(self, course_id=None, limit=10):
        return sessions.recent_sessions(self.conn, course_id, limit)

    # -- context / lessons ---------------------------------------------------
    def _teaching_lesson_background(self, course_id, state, scope):
        """One-time background from the existing plan/lessons, not a new pack.

        A range-level saved lesson wins; otherwise collect prepared descendant
        lessons in tree order. Neither case changes the subsection cursor.
        """
        from . import teaching
        cursor = teaching._cursor(self.conn, course_id)
        if not cursor or not cursor['plan_id']:
            return None
        items = [i for i in teaching._items(self.conn, cursor['plan_id'])
                 if i['status'] != 'retracted' and i['kind'] != 'question']
        by_id = {i['id']: i for i in items}
        current_id = state['current_item']['id']
        outline = teaching.unit_outline(items, current_id)
        root_id = (outline['unit']['id'] if outline else current_id)
        if scope == 'section' and outline and outline['current_section']:
            root_id = outline['current_section']
        root = by_id.get(root_id)
        if root is None:
            return None
        children = {}
        for item in items:
            children.setdefault(item['parent_id'], []).append(item)
        for siblings in children.values():
            siblings.sort(key=lambda item: (item['seq'], item['id']))
        ordered = []
        def walk(item, depth=0):
            ordered.append(dict(item, depth=depth))
            for child in children.get(item['id'], []):
                walk(child, depth + 1)
        walk(root)
        lessons, missing, covered = [], [], set()
        for item in ordered:
            if item['parent_id'] in covered:
                covered.add(item['id'])
                continue
            artifact = self.get_lesson_artifact(
                state['section_id'], teaching_item_id=item['id'])
            if artifact:
                lessons.append({'item_id': item['id'], 'title': item['title'], **artifact})
                covered.add(item['id'])
            elif not children.get(item['id']):
                missing.append(item['id'])
        return {'scope': scope, 'item_id': root_id, 'title': root['title'],
                'outline': [{k: i[k] for k in ('id', 'parent_id', 'kind', 'title', 'status', 'depth')}
                            for i in ordered],
                'lessons': lessons, 'missing_item_ids': missing}

    def build_context_pack(self, node_id, mode, focused_question=None):
        return context_mod.build_context_pack(self.conn, node_id, mode,
                                              focused_question)

    def _lesson_key(self, node_id, mode, teaching_item_id):
        if mode not in ('intro', 'clarify', 'review'):
            raise ValidationError('invalid mode: %r' % mode)
        graph.get_node(self.conn, node_id)
        if teaching_item_id is not None:
            row = self.conn.execute('SELECT p.section_id FROM teaching_items i JOIN teaching_plans p'
                                    ' ON p.id=i.plan_id WHERE i.id=?', (teaching_item_id,)).fetchone()
            if row is None or row['section_id'] != node_id:
                raise ValidationError('Lesson item must belong to this section')
        return mode

    def save_lesson_artifact(self, node_id, mode, content, teaching_item_id=None):
        if mode not in ("intro", "clarify", "review"):
            raise ValidationError("invalid mode: %r" % mode)
        key = self._lesson_key(node_id, mode, teaching_item_id)
        if not content or not content.strip():
            raise ValidationError("lesson content must not be empty")
        if teaching_item_id is not None:
            # Reuse the append-only teaching record store. Whole-node lessons
            # retain their original table/schema and no migration is needed.
            course_id = graph.get_node(self.conn, node_id)['course_id']
            payload = {'lesson_artifact': {'item_id': teaching_item_id,
                                          'mode': mode, 'content': content}}
            with transaction(self.conn):
                row = self.conn.execute(
                    'INSERT INTO teaching_updates(course_id,section_id,role,payload,ts)'
                    ' VALUES(?,?,?,?,?)',
                    (course_id, node_id, 'main', json.dumps(payload, ensure_ascii=False), now_iso()))
            return {'saved': True, 'node_id': node_id, 'mode': mode,
                    'teaching_item_id': teaching_item_id, 'record_id': row.lastrowid}
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO lesson_artifacts (node_id, mode, content,"
                " created_at) VALUES (?,?,?,?)"
                " ON CONFLICT(node_id, mode) DO UPDATE SET"
                " content = excluded.content, created_at = excluded.created_at",
                (node_id, key, content, now_iso()),
            )
        return {"saved": True, "node_id": node_id, "mode": mode,
                "teaching_item_id": teaching_item_id}

    def get_lesson_artifact(self, node_id, mode="intro", teaching_item_id=None):
        if not graph.node_exists(self.conn, node_id) and teaching_item_id is None:
            from . import production, review_graph
            review_graph._node(self.conn, node_id)
            return production.lesson(self.conn, node_id) if mode == 'intro' else None
        key = self._lesson_key(node_id, mode, teaching_item_id)
        if teaching_item_id is not None:
            row = self.conn.execute(
                "SELECT json_extract(payload,'$.lesson_artifact.content') AS content,"
                ' ts AS created_at FROM teaching_updates WHERE section_id=?'
                " AND json_extract(payload,'$.lesson_artifact.item_id')=?"
                " AND json_extract(payload,'$.lesson_artifact.mode')=? ORDER BY id DESC LIMIT 1",
                (node_id, teaching_item_id, mode)).fetchone()
            return dict(row) if row else None
        row = self.conn.execute(
            "SELECT content, created_at FROM lesson_artifacts"
            " WHERE node_id = ? AND mode = ?", (node_id, key),
        ).fetchone()
        return dict(row) if row else None

    # -- sources -------------------------------------------------------------
    def register_url(self, source_id, course_id, url, title, lecture_ref=""):
        sources.register_url(self.conn, source_id, course_id, url, title,
                             lecture_ref)
        return {"source_id": source_id}

    def register_source_file(self, course_id, path, title=None,
                             lecture_ref=""):
        return sources.register_file(self.conn, course_id, path,
                                     self.source_roots, title, lecture_ref)

    def attach_source(self, node_id, source_id, anchor=""):
        sources.attach_source(self.conn, node_id, source_id, anchor)
        return {"attached": True}

    def list_sources(self, course_id):
        return sources.list_sources(self.conn, course_id)

    def search_sources(self, course_id, query, limit=5):
        return sources.search_chunks(self.conn, course_id, query, limit)

    # -- claims (implementation status of resume/project statements) --------
    def add_claim(self, course_id, text, status, node_id=None, evidence=""):
        cid = graph.add_claim(self.conn, course_id, text, status, node_id,
                              evidence)
        return {"claim_id": cid, "status": status}

    def list_claims(self, course_id=None, node_id=None, status=None):
        return graph.list_claims(self.conn, course_id, node_id, status)

    def set_claim_status(self, claim_id, status, evidence=None):
        graph.set_claim_status(self.conn, claim_id, status, evidence)
        return {"claim_id": claim_id, "status": status}

    # -- proposals -----------------------------------------------------------
    def propose_change(self, kind, payload, rationale=""):
        pid = graph.propose_change(self.conn, kind, payload, rationale)
        return {"proposal_id": pid, "status": "pending"}

    def list_proposals(self, status=None):
        return graph.list_proposals(self.conn, status)

    def approve_proposal(self, proposal_id):
        graph.approve_proposal(self.conn, proposal_id)
        return {"proposal_id": proposal_id, "status": "approved",
                "graph_version": graph.graph_version(self.conn)}

    def reject_proposal(self, proposal_id, reason=""):
        graph.reject_proposal(self.conn, proposal_id, reason)
        return {"proposal_id": proposal_id, "status": "rejected"}

    def graph_version(self):
        return graph.graph_version(self.conn)
