"""Structured interview question bank (R2, 2026-09-24).

正式题库是检索入口；面经大文件是临时素材池，已整理内容以本模块的表为
事实源。等级（normal/firsthand）与掌握程度独立：question_judgments 没有
行 = 未判断，不得从来源、笔记存在、材料登记推断用户已经掌握。亲历题升级
复用原条目（UPDATE level + 插一手记录），不重复建题。
"""

import json

from .db import dicts, transaction
from .graph import ValidationError, now_iso

LEVELS = ('normal', 'firsthand')
JUDGE_RESULTS = ('pass', 'deepen')
POOL_STATUSES = ('pending', 'partial', 'migrated')


def setup(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS questions(
      id TEXT PRIMARY KEY,
      course_id TEXT NOT NULL,
      group_key TEXT NOT NULL DEFAULT '',
      stem TEXT NOT NULL,
      variants TEXT NOT NULL DEFAULT '[]',
      context TEXT NOT NULL DEFAULT '',
      answer_basis TEXT NOT NULL DEFAULT '',
      level TEXT NOT NULL DEFAULT 'normal'
        CHECK (level IN ('normal','firsthand')),
      source_ref TEXT NOT NULL DEFAULT '{}',
      origin TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_questions_course
      ON questions(course_id, group_key);

    CREATE TABLE IF NOT EXISTS question_knowledge(
      question_id TEXT NOT NULL REFERENCES questions(id),
      point_id TEXT NOT NULL,
      PRIMARY KEY (question_id, point_id));

    CREATE TABLE IF NOT EXISTS question_projects(
      question_id TEXT NOT NULL REFERENCES questions(id),
      project_ref TEXT NOT NULL,
      PRIMARY KEY (question_id, project_ref));

    CREATE TABLE IF NOT EXISTS question_firsthand(
      question_id TEXT NOT NULL REFERENCES questions(id),
      interviewed_at TEXT NOT NULL,
      actual_wording TEXT NOT NULL DEFAULT '',
      followups TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL,
      PRIMARY KEY (question_id, interviewed_at));

    CREATE TABLE IF NOT EXISTS question_judgments(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      question_id TEXT NOT NULL REFERENCES questions(id),
      judged_at TEXT NOT NULL,
      result TEXT NOT NULL CHECK (result IN ('pass','deepen')),
      gap_note TEXT NOT NULL DEFAULT '',
      origin TEXT NOT NULL DEFAULT '');
    CREATE INDEX IF NOT EXISTS idx_qj_question
      ON question_judgments(question_id, id);

    CREATE TABLE IF NOT EXISTS teaching_knowledge_links(
      item_id INTEGER NOT NULL REFERENCES teaching_items(id),
      knowledge_course_id TEXT NOT NULL,
      point_id TEXT NOT NULL,
      note TEXT NOT NULL DEFAULT '',
      PRIMARY KEY(item_id, knowledge_course_id, point_id));
    CREATE TABLE IF NOT EXISTS question_judgment_evidence(
      judgment_id INTEGER PRIMARY KEY REFERENCES question_judgments(id),
      answer_summary TEXT NOT NULL,
      teaching_item_id INTEGER REFERENCES teaching_items(id));

    CREATE TABLE IF NOT EXISTS material_pool(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      source_id TEXT NOT NULL,
      section TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','partial','migrated')),
      question_ids TEXT NOT NULL DEFAULT '[]',
      note TEXT NOT NULL DEFAULT '',
      updated_at TEXT NOT NULL,
      UNIQUE(source_id, section));
    ''')
    from . import question_links
    question_links.setup(conn)
    from . import question_categories
    question_categories.setup(conn)


def _row(conn, qid):
    row = conn.execute('SELECT * FROM questions WHERE id=?', (qid,)).fetchone()
    if row is None:
        raise ValidationError('Unknown question: %r' % qid)
    return row


def _write_links(conn, qid, points, projects):
    conn.execute('DELETE FROM question_knowledge WHERE question_id=?', (qid,))
    conn.execute('DELETE FROM question_projects WHERE question_id=?', (qid,))
    for p in points or []:
        conn.execute(
            'INSERT OR IGNORE INTO question_knowledge(question_id, point_id)'
            ' VALUES(?,?)', (qid, p))
    for p in projects or []:
        conn.execute(
            'INSERT OR IGNORE INTO question_projects(question_id, project_ref)'
            ' VALUES(?,?)', (qid, p))


def import_questions(conn, entries, origin):
    """Bulk upsert by stable id; safe to replay (same data rewritten).
    Each entry: id, course_id?, group_key, stem, variants?, context?,
    answer_basis?, level?, source_ref?|source_lines?, points?, projects?."""
    seen = set()
    with transaction(conn):
        for e in entries:
            qid = e['id']
            if qid in seen:
                raise ValidationError('duplicate question id in batch: ' + qid)
            seen.add(qid)
            if not e.get('stem'):
                raise ValidationError('question %s has empty stem' % qid)
            level = e.get('level', 'normal')
            if level not in LEVELS:
                raise ValidationError('invalid level %r for %s' % (level, qid))
            source_ref = e.get('source_ref')
            if source_ref is None:
                source_ref = {'file': '面经.txt',
                              'lines': sorted(e.get('source_lines') or [])}
            now = now_iso()
            conn.execute(
                'INSERT INTO questions(id, course_id, group_key, stem,'
                ' variants, context, answer_basis, level, source_ref,'
                ' origin, created_at, updated_at)'
                ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?)'
                ' ON CONFLICT(id) DO UPDATE SET'
                ' course_id=excluded.course_id, group_key=excluded.group_key,'
                ' stem=excluded.stem, variants=excluded.variants,'
                ' context=excluded.context,'
                ' answer_basis=excluded.answer_basis, level=excluded.level,'
                ' source_ref=excluded.source_ref, origin=excluded.origin,'
                ' updated_at=excluded.updated_at',
                (qid, e.get('course_id', ''), e.get('group_key', ''),
                 e['stem'], json.dumps(e.get('variants') or [],
                                       ensure_ascii=False),
                 e.get('context', ''), e.get('answer_basis', ''), level,
                 json.dumps(source_ref, ensure_ascii=False), origin, now, now))
            _write_links(conn, qid, e.get('points'), e.get('projects'))
    return {'upserted': len(seen)}


def add_question(conn, course_id, stem, question_id, group_key='',
                 variants=None, context='', answer_basis='',
                 source_ref=None, points=None, projects=None,
                 origin='manual'):
    """Create ONE new question. Caller dedups first (search_questions);
    this function refuses an existing id instead of merging."""
    if conn.execute('SELECT 1 FROM questions WHERE id=?',
                    (question_id,)).fetchone():
        raise ValidationError('question id already exists: ' + question_id)
    import_questions(conn, [{'id': question_id, 'course_id': course_id,
                             'group_key': group_key, 'stem': stem,
                             'variants': variants, 'context': context,
                             'answer_basis': answer_basis,
                             'source_ref': source_ref or {},
                             'points': points, 'projects': projects}], origin)
    return {'question_id': question_id, 'created': True}


def merge_variants(conn, qid, variants=None, source_lines=None, origin='', source_ref=None):
    """Dedup path: an existing question matched the new material — append
    wordings and source lines instead of creating a duplicate."""
    row = _row(conn, qid)
    existing = json.loads(row['variants'])
    ref = json.loads(row['source_ref'])
    lines = ref.get('lines') or []
    added_v = [v for v in (variants or []) if v and v not in existing]
    added_l = [n for n in (source_lines or []) if n not in lines]
    sources=list(ref.get('sources') or [])
    added_sources=[]
    if source_ref:
        incoming=source_ref.get('sources') or [source_ref]
        for item in incoming:
            if item not in sources and item not in added_sources:added_sources.append(item)
    if not added_v and not added_l and not added_sources:
        return {'question_id': qid, 'merged': False}
    with transaction(conn):
        conn.execute(
            'UPDATE questions SET variants=?, source_ref=?, origin=?,'
            ' updated_at=? WHERE id=?',
            (json.dumps(existing + added_v, ensure_ascii=False),
             json.dumps({**ref, 'lines': sorted(lines + added_l), **({'sources':sources+added_sources} if sources or added_sources else {})},
                        ensure_ascii=False),
             origin or row['origin'], now_iso(), qid))
    return {'question_id': qid, 'merged': True,
            'added_variants': len(added_v), 'added_lines': len(added_l), 'added_sources':len(added_sources)}


def search_questions(conn, course_id, text=None, group=None, point_id=None,
                     project_ref=None):
    sql = ('SELECT DISTINCT q.* FROM questions q'
           ' LEFT JOIN question_knowledge k ON k.question_id = q.id'
           ' LEFT JOIN question_projects p ON p.question_id = q.id'
           ' WHERE q.course_id=?')
    args = [course_id]
    if text:
        sql += ' AND (q.stem LIKE ? OR q.variants LIKE ?)'
        args += ['%' + text + '%', '%' + text + '%']
    if group:
        sql += ' AND q.group_key=?'
        args.append(group)
    if point_id:
        # Canonical knowledge IDs and old identities share the review adapter.
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='review_graph_nodes'").fetchone():
            from . import question_links
            binding=conn.execute("SELECT node_id FROM review_graph_bindings WHERE ref_id=? AND (course_id=? OR course_id='') ORDER BY course_id DESC LIMIT 1",(point_id,course_id)).fetchone()
            nid=binding[0] if binding else point_id
            ids=[q['id'] for q in question_links.questions_for_node(conn,nid)]
            sql += ' AND q.id IN ('+','.join('?' for _ in ids)+')' if ids else ' AND 0'
            args.extend(ids)
        else:
            sql += ' AND k.point_id=?'
            args.append(point_id)
    if project_ref:
        sql += ' AND p.project_ref=?'
        args.append(project_ref)
    sql += ' ORDER BY q.id'
    rows = dicts(conn.execute(sql, args))
    for r in rows:
        r['variants'] = json.loads(r['variants'])
        r['source_ref'] = json.loads(r['source_ref'])
        r['points'] = [x[0] for x in conn.execute(
            'SELECT point_id FROM question_knowledge WHERE question_id=?'
            ' ORDER BY point_id', (r['id'],))]
        r['projects'] = [x[0] for x in conn.execute(
            'SELECT project_ref FROM question_projects WHERE question_id=?'
            ' ORDER BY project_ref', (r['id'],))]
    return rows


def _latest_judgment(conn, qid):
    row = conn.execute(
        'SELECT * FROM question_judgments WHERE question_id=?'
        ' ORDER BY id DESC LIMIT 1', (qid,)).fetchone()
    result = dict(row) if row else None
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='review_question_attempts'").fetchone():
        attempt = conn.execute("SELECT a.*,b.title AS batch_title FROM review_question_attempts a "
            "JOIN review_batches b ON b.id=a.batch_id WHERE a.question_id=? AND a.kind='answer' "
            "AND a.result IS NOT NULL ORDER BY julianday(a.created_at) DESC,a.rowid DESC LIMIT 1", (qid,)).fetchone()
        if attempt and (not row or conn.execute('SELECT julianday(?)>=julianday(?)',
                                               (attempt['created_at'], row['judged_at'])).fetchone()[0]):
            result = {'question_id': qid, 'result': attempt['result'], 'gap_note': attempt['gap_note'],
                      'judged_at': attempt['created_at'], 'origin': 'review_batch',
                      'attempt_id': attempt['id'], 'batch_id': attempt['batch_id'],
                      'batch_title': attempt['batch_title'], 'project_id': attempt['project_id']}
    return result


def get_question(conn, qid):
    row = dict(_row(conn, qid))
    from . import question_categories
    row['categories'] = question_categories.for_question(conn, qid, row['stem'])
    row['variants'] = json.loads(row['variants'])
    row['source_ref'] = json.loads(row['source_ref'])
    row['points'] = [x[0] for x in conn.execute(
        'SELECT point_id FROM question_knowledge WHERE question_id=?'
        ' ORDER BY point_id', (qid,))]
    row['projects'] = [x[0] for x in conn.execute(
        'SELECT project_ref FROM question_projects WHERE question_id=?'
        ' ORDER BY project_ref', (qid,))]
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='review_graph_nodes'").fetchone():
        from . import question_links
        row['sources']=question_links.sources(row['source_ref'])
        row['knowledge_nodes']=question_links.reverse(conn,qid)
        pending=conn.execute('SELECT reason FROM question_link_pending WHERE question_id=?',(qid,)).fetchone() if question_links.exists(conn,'question_link_pending') else None
        row['pending_reason']=pending[0] if pending else ''
        row['association_status']='partial' if row['knowledge_nodes'] and pending else 'linked' if row['knowledge_nodes'] else 'pending'
    row['firsthand'] = dicts(conn.execute(
        'SELECT * FROM question_firsthand WHERE question_id=?'
        ' ORDER BY interviewed_at', (qid,)))
    # 当前判断 = 最新一行；没有行 = 未判断（不推断掌握）
    row['judgment'] = _latest_judgment(conn, qid)
    evidence = conn.execute(
        'SELECT e.answer_summary,e.teaching_item_id FROM question_judgments j '
        'LEFT JOIN question_judgment_evidence e ON e.judgment_id=j.id '
        'WHERE j.question_id=? ORDER BY j.id DESC LIMIT 1', (qid,)).fetchone()
    row['judgment_evidence'] = dict(evidence) if evidence else None
    if row['judgment'] and row['judgment'].get('attempt_id'):
        answer = conn.execute('SELECT answer FROM review_question_attempts WHERE id=?',
                              (row['judgment']['attempt_id'],)).fetchone()
        row['judgment_evidence'] = {'answer_summary': answer[0], 'teaching_item_id': None}
    return row


def upgrade_firsthand(conn, qid, interviewed_at, actual_wording='',
                      followups=''):
    """亲历题升级：复用原条目（UPDATE level + 插一手记录），不重复建题。
    等级与掌握独立——升级不触碰 question_judgments。"""
    _row(conn, qid)
    with transaction(conn):
        conn.execute(
            "UPDATE questions SET level='firsthand', updated_at=? WHERE id=?",
            (now_iso(), qid))
        conn.execute(
            'INSERT OR IGNORE INTO question_firsthand(question_id,'
            ' interviewed_at, actual_wording, followups, created_at)'
            ' VALUES(?,?,?,?,?)',
            (qid, interviewed_at, actual_wording, followups, now_iso()))
    return {'question_id': qid, 'level': 'firsthand'}


def record_judgment(conn, qid, result, gap_note='', origin='',
                    answer_summary='', teaching_item_id=None):
    """Append one judgment; the current judgment is the latest row. 服务层
    留口——迁移不调用它，判断只能来自用户实际作答。"""
    if result not in JUDGE_RESULTS:
        raise ValidationError('Invalid judgment result: %r (one of %s)'
                              % (result, '/'.join(JUDGE_RESULTS)))
    if result == 'deepen' and not gap_note.strip():
        raise ValidationError('需要深入必须记录具体缺口（gap_note）')
    _row(conn, qid)
    if teaching_item_id is not None:
        _teaching_item(conn, teaching_item_id)
    with transaction(conn):
        cur = conn.execute(
            'INSERT INTO question_judgments(question_id, judged_at, result,'
            ' gap_note, origin) VALUES(?,?,?,?,?)',
            (qid, now_iso(), result, gap_note, origin))
        if answer_summary or teaching_item_id is not None:
            conn.execute('INSERT INTO question_judgment_evidence VALUES(?,?,?)',
                         (cur.lastrowid, answer_summary, teaching_item_id))
    return {'question_id': qid, 'result': result, 'judgment_id': cur.lastrowid}


def _teaching_item(conn, item_id):
    row = conn.execute('SELECT id FROM teaching_items WHERE id=?', (item_id,)).fetchone()
    if row is None:
        raise ValidationError('Unknown teaching item: %s' % item_id)
    return row


def link_teaching_knowledge(conn, item_id, knowledge_course_id, point_id, note=''):
    """Explicit cross-course references, not mastery/scheduling. Reuse existing
    course+point anchors; never copy their body into teaching history."""
    _teaching_item(conn, item_id)
    if not conn.execute('SELECT 1 FROM review_items WHERE course_id=? AND point_id=?',
                        (knowledge_course_id, point_id)).fetchone():
        raise ValidationError('Unknown knowledge anchor: %s/%s' % (knowledge_course_id, point_id))
    with transaction(conn):
        conn.execute('INSERT INTO teaching_knowledge_links VALUES(?,?,?,?) '
                     'ON CONFLICT(item_id,knowledge_course_id,point_id) DO UPDATE SET note=excluded.note',
                     (item_id, knowledge_course_id, point_id, note))
    return {'success': True, 'item_id': item_id, 'point_id': point_id}


def knowledge_connections(conn, knowledge_course_id, point_id):
    """On-demand links only; do not inject histories into every teaching turn."""
    items = dicts(conn.execute(
        'SELECT t.id, t.title, t.kind, t.status, p.course_id, l.note '
        'FROM teaching_knowledge_links l JOIN teaching_items t ON t.id=l.item_id '
        'JOIN teaching_plans p ON p.id=t.plan_id '
        'WHERE l.knowledge_course_id=? AND l.point_id=? ORDER BY t.id',
        (knowledge_course_id, point_id)))
    qs = dicts(conn.execute(
        'SELECT q.id,q.stem FROM questions q JOIN question_knowledge k ON k.question_id=q.id '
        'WHERE q.course_id=? AND k.point_id=? ORDER BY q.id', (knowledge_course_id, point_id)))
    return {'course_id': knowledge_course_id, 'point_id': point_id,
            'teaching_items': items, 'questions': qs}


def set_pool_status(conn, source_id, section, status, question_ids=None,
                    note=''):
    if status not in POOL_STATUSES:
        raise ValidationError('Invalid pool status: %r' % status)
    with transaction(conn):
        conn.execute(
            'INSERT INTO material_pool(source_id, section, status,'
            ' question_ids, note, updated_at) VALUES(?,?,?,?,?,?)'
            ' ON CONFLICT(source_id, section) DO UPDATE SET'
            ' status=excluded.status, question_ids=excluded.question_ids,'
            ' note=excluded.note, updated_at=excluded.updated_at',
            (source_id, section, status,
             json.dumps(question_ids or [], ensure_ascii=False), note,
             now_iso()))
    return {'source_id': source_id, 'section': section, 'status': status}


def pool_status(conn, source_id=None):
    sql = 'SELECT * FROM material_pool'
    args = []
    if source_id:
        sql += ' WHERE source_id=?'
        args.append(source_id)
    sql += ' ORDER BY section'
    rows = dicts(conn.execute(sql, args))
    for r in rows:
        r['question_ids'] = json.loads(r['question_ids'])
    return rows
