"""复习座舱装配（R1, 2026-09-25）：基础八股 + 项目模块 + 通路 + 题目判断。

信息组织（需求 docs/requirements/2026-09-24-座舱与素材库整理.md R1）：
- 基础八股按专题知识块分组（知识正文一份，在知识块文件里，这里只装索引）。
- 项目内容依托核心模块（M01–M08 项目锚点），正常/异常通路把模块串起来。
- 基础知识 ↔ 项目双向关联：point→模块来自笔记正文里的锚点引用
  （bagu_catalog 同一套解析），question→知识点/项目来自题库挂接表。
- 题目三档判断：未判断（无记录）/ 基本通过(pass) / 需要深入(deepen)+缺口；
  当前判断=最新一行。单题判断不代表整个模块掌握（页面文案口径）。
- 当前不新增每日复习安排；本模块只做信息组织与可视化数据。
"""

from . import bagu_catalog, questions, review, seed_bagu, presentation

# Agent1 HttpServer 通路（依 知识块/08-muduo-httpserver.md 各块首段编排；
# 转场描述照笔记原意，不新造机制）。module 用 catalog 的 project:M 锚点 id。
PATHWAYS = [
    {'key': 'normal', 'title': '正常请求通路',
     'steps': [
         {'module': 'project:M01', 'note': 'muduo 交字节，onMessage 进 HTTP 层'},
         {'module': 'project:M02', 'note': '每连接一份 HttpContext 保存解析进度'},
         {'module': 'project:M03', 'note': '三态状态机增量解析到 kGotAll'},
         {'module': 'project:M04', 'note': 'Method+Path 联合键路由'},
         {'module': 'project:M05', 'note': '同步路径：中间件→处理器→填响应'},
         {'module': 'project:M06', 'note': 'appendToBuffer 序列化后发送'},
         {'module': 'project:M08', 'note': 'reset 等下一条；Connection 头定去留'},
     ]},
    {'key': 'async', 'title': '异步支线（慢业务不拖 loop）',
     'steps': [
         {'module': 'project:M05', 'note': '异步路径：拿走 responder 转工作线程'},
         {'module': 'project:M07', 'note': 'CAS 争一次性完成权；回投再查连接'},
     ]},
    {'key': 'exception', 'title': '异常与边界通路',
     'steps': [
         {'module': 'project:M03', 'note': '半包等下一波（不完整≠错误）；格式错单独处理'},
         {'module': 'project:M07', 'note': '断连收尾：连接已断/对象已销毁不重复响应'},
     ]},
]

JUDGE_LABELS = {'pass': '基本通过', 'deepen': '需要深入'}


def _latest_judgments(conn, course_id):
    """每题最新一条判断（无行=未判断）。"""
    rows = conn.execute(
        'SELECT j.question_id, j.result, j.gap_note, j.judged_at,'
        ' e.answer_summary, e.teaching_item_id'
        ' FROM question_judgments j'
        ' JOIN questions q ON q.id = j.question_id'
        ' LEFT JOIN question_judgment_evidence e ON e.judgment_id=j.id'
        ' WHERE q.course_id=?'
        ' ORDER BY j.id', (course_id,)).fetchall()
    latest = {}
    for r in rows:  # id 升序，后者覆盖前者 = 最新
        latest[r['question_id']] = {'result': r['result'],
                                    'gap_note': r['gap_note'],
                                    'judged_at': r['judged_at'],
                                    'answer_summary': r['answer_summary'],
                                    'teaching_item_id': r['teaching_item_id']}
    return latest


def _q_brief(q, latest):
    j = latest.get(q['id'])
    return {'id': q['id'], 'stem': q['stem'], 'group_key': q['group_key'],
            'level': q['level'],
            'answer_pending': q['answer_basis'].startswith('待补'),
            'judgment': (j['result'] if j else 'unjudged'),
            'gap_note': (j['gap_note'] if j else ''),
            'answer_summary': (j['answer_summary'] if j else ''),
            'teaching_item_id': (j['teaching_item_id'] if j else None)}


def cockpit(conn, course_id):
    latest = _latest_judgments(conn, course_id)
    qs = [dict(r) for r in conn.execute(
        'SELECT id, stem, group_key, level, answer_basis FROM questions'
        ' WHERE course_id=? ORDER BY id', (course_id,))]
    q_by_point, q_by_project = {}, {}
    for r in conn.execute('SELECT question_id, point_id FROM question_knowledge'):
        q_by_point.setdefault(r['point_id'], []).append(r['question_id'])
    for r in conn.execute('SELECT question_id, project_ref FROM question_projects'):
        q_by_project.setdefault(r['project_ref'], []).append(r['question_id'])
    q_by_id = {q['id']: q for q in qs}

    def _qs(ids):
        out = [_q_brief(q_by_id[i], latest) for i in ids or [] if i in q_by_id]
        out.sort(key=lambda b: b['id'])
        return out

    # 项目模块与锚点引用（与知识目录同一份解析，正文一份在笔记里）
    blocks = bagu_catalog.blocks(conn) if course_id == seed_bagu.COURSE_ID else []
    modules, point_modules = [], {}
    for b in blocks:
        if b['kind'] != 'project-anchor':
            continue
        mref = b['id'].split(':', 1)[1]
        modules.append({
            'id': b['id'], 'ref': mref, 'title': b['title'],
            'points': sorted(b['points']),
            'questions': _qs(q_by_project.get(mref))})
        modules[-1].update(presentation.module_name(b['id'], b['title']))
        for p in b['points']:
            point_modules.setdefault(p, []).append(b['id'])

    # 基础八股：按专题知识块分组；题目判断只汇总到题目，不冒充模块掌握
    groups = {}
    for r in review.iter_items(conn, course_id):
        name = presentation.source_name(r['source_id'], r['source_title'] or '未分组')['title']
        g = groups.setdefault(name, [])
        g.append({
            'id': 'review:%s' % r['id'], 'point_id': r['point_id'],
            'title': r['title'], 'anchor': r['anchor'],
            'review_status': r['status'],
            'questions': _qs(q_by_point.get(r['point_id'])),
            'modules': sorted(point_modules.get(r['point_id'], []))})
    knowledge = []
    for title, points in groups.items():
        all_q = list({q['id']: q for p in points for q in p['questions']}.values())
        knowledge.append({
            'group': title, 'points': points,
            'q_total': len(all_q),
            'q_pass': sum(1 for q in all_q if q['judgment'] == 'pass'),
            'q_deepen': sum(1 for q in all_q if q['judgment'] == 'deepen')})
    return {'course_id': course_id,
            'pathways': PATHWAYS if course_id == seed_bagu.COURSE_ID else [],
            'knowledge': knowledge, 'modules': modules,
            'judge_labels': JUDGE_LABELS,
            'note': '题目判断只代表该题覆盖内容，不代表整个模块掌握。'}
