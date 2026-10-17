"""Read-only project and interview views over the Agent1 note sources.

Project blocks still derive from the registered Markdown chunks. Interview
question blocks come from the structured question bank (questions.py, R2
2026-09-24) — the old 08-interview-question-index.md parsing was replaced by
it; the Markdown file remains as archive/pointer only. Neither project
anchors nor interview questions enter review scheduling.
"""

import re

from . import questions, seed_bagu


_POINT = re.compile(r'\]\([^)]*#([NDTSHRU]\d{2})\)')
_PROJECT = re.compile(r'^(M\d{2})\s+')


def _source(conn, source_id):
    return conn.execute('SELECT * FROM sources WHERE id=? AND course_id=?',
                        (source_id, seed_bagu.COURSE_ID)).fetchone()


def _questions(conn):
    """One block per structured question, grouped by 题组 (the original
    N1..C12 source structure — group count is NOT the question count)."""
    rows = []
    for q in questions.search_questions(conn, seed_bagu.COURSE_ID):
        note = ('待补：' + q['answer_basis']) if '待补' in q['answer_basis'] \
            else '答案已有依据；尚未验证掌握'
        rows.append({'id': 'question:' + q['id'], 'kind': 'interview-question',
                     'title': q['stem'],
                     'group': '面经题库 · ' + q['group_key'],
                     'ref': '题库 ' + q['id'],
                     'note': note,
                     'points': set(q['points']),
                     'question': q})
    return rows


def _projects(conn):
    if not _source(conn, 'bagu-s1-kb-project'):
        return []
    rows = conn.execute(
        'SELECT anchor, text FROM chunks WHERE source_id=? ORDER BY id',
        ('bagu-s1-kb-project',)).fetchall()
    out = []
    for row in rows:
        match = _PROJECT.match(row['anchor'])
        if not match:
            continue
        name = match.group(1)
        out.append({'id': 'project:' + name, 'kind': 'project-anchor',
                    'title': row['anchor'],
                    'group': '项目实现 · muduo / HttpServer',
                    'ref': '知识块/08-muduo-httpserver.md#' + name,
                    'note': '项目实现对接；不计入已有 72 点的复习分母',
                    'points': set(_POINT.findall(row['text'])),
                    'chunk': dict(row)})
    return out


def blocks(conn):
    return _projects(conn) + _questions(conn)


def related(conn, point_id):
    """Links from explicit anchors / question_knowledge rows, never guessed
    by title."""
    return [
        {'kind': 'knowledge', 'id': b['id'], 'basis': 'manual',
         'note': '引用 ' + point_id, 'dir': 'out'}
        for b in blocks(conn) if point_id in b['points']
    ]


def _question_text(q):
    parts = ['题干：' + q['stem']]
    if q['variants']:
        parts.append('不同问法：\n' + '\n'.join('- ' + v
                                                for v in q['variants']))
    if q['context']:
        parts.append('上下文与答题边界：' + q['context'])
    parts.append('答案依据：' + (q['answer_basis'] or '待补'))
    ref = q['source_ref']
    if ref:
        parts.append('来源：%s 行 %s'
                     % (ref.get('file', ''),
                        ', '.join(str(n) for n in ref.get('lines', []))))
    if q['level'] == 'firsthand':
        seen = ['%s：%s（追问：%s）' % (f['interviewed_at'],
                                      f['actual_wording'], f['followups'])
                for f in q['firsthand']]
        parts.append('亲历记录：\n' + '\n'.join(seen))
    # 判断状态如实展示；没有判断行 = 未判断，不等于掌握
    if q['judgment']:
        parts.append('当前判断：%s（%s）%s'
                     % (q['judgment']['result'], q['judgment']['judged_at'],
                        q['judgment']['gap_note']))
    else:
        parts.append('当前判断：未判断')
    return '\n\n'.join(parts)


def detail(conn, item_id):
    block = next((b for b in blocks(conn) if b['id'] == item_id), None)
    if block is None:
        return None
    if block.get('question') is not None:
        q = questions.get_question(conn, block['question']['id'])
        chunk = {'anchor': q['stem'], 'text': _question_text(q)}
    else:
        chunk = block.get('chunk') or {'anchor': block['title'],
                                       'text': block.get('text', '')}
    review_ids = {r['point_id']: r['id'] for r in conn.execute(
        'SELECT id, point_id FROM review_items WHERE course_id=?',
        (seed_bagu.COURSE_ID,))}
    links = [{'kind': 'knowledge', 'id': 'review:%s' % review_ids[p],
              'basis': 'manual', 'note': '引用 ' + p, 'dir': 'in'}
             for p in sorted(block['points']) if p in review_ids]
    return {'id': item_id, 'kind': block['kind'], 'chunks': [chunk],
            'links': links}
