"""Shared chapter workspace + lightweight teaching plan tree (M1.1).

Design rules (TODO §8, final wording 2026-09-22):
- Plans are milestones set by the main window; the detail window splits the
  current milestone into sub items as it teaches; follow-up questions hang
  under whatever item they arose in. One self-referential tree, three kinds.
- Statuses are lightweight markers, NOT gates. No forced order, no "clear all
  questions before continuing". The only hard rules: only the main window
  creates plans, marks milestones done and submits chapter decisions; course
  ownership is always checked; cursor updates carry a state_version so a
  stale window cannot silently overwrite a newer position.
- Solving a child item never completes its parent; question items never
  affect formal progress denominators.
- Writes return minimal state (success + state_version + cursor). Full state
  is available via get_state(full=True) for review/acceptance only.
'clarify' is accepted as a legacy alias of 'detail'.
"""
import json
import hashlib
from datetime import datetime, timezone
from .db import transaction
from .graph import get_node, ValidationError

# 层级命名（2026-09-25 与用户定稿）：大阶段(课程简纲) → 阶段(milestone)
# → 单元(带子项的 sub) → 节(section，单元内的分组标题) → 小节(学习条目 sub)
# → 小项(追问/过程记录，kind=question 或 teaching_updates topics)。
# 树天然支持嵌套；section 只是给"单元内的分组标题"一个明确种类。
ITEM_KINDS = ('milestone', 'section', 'sub', 'question')
# Informational markers only; no transition is ever rejected for order.
# 'presented' (2026-09-24 语义校准): 讲义已输出/内容已讲解，但未经用户理解
# 确认或验证。生成回复不等于学会；只有 main 能标 done（讲过的≠通过的）。
# 'retracted' (2026-09-25): 作废留痕——被替代/误登记的项，不进正式顺序与
# 统计，不物理删除。结构修改（改名/排序/换父级/作废/分节）仅 main 可执行。
ITEM_STATUSES = ('pending', 'active', 'presented', 'done', 'deferred',
                 'open', 'resolved', 'retracted', 'awaiting_confirmation',
                 'self_reported_understood')

ROLES = ('main', 'detail', 'control')
LEGACY_ROLES = {'clarify': 'detail'}

# Consecutive non-progress process records on one node before prepare_teaching
# surfaces a stagnation hint (TODO §5, tunable).
STAGNATION_THRESHOLD = 3


def _ts():
    return datetime.now(timezone.utc).isoformat()


def setup(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS teaching_workspace (
      course_id TEXT PRIMARY KEY, section_id TEXT NOT NULL,
      focus TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'learning');
    CREATE TABLE IF NOT EXISTS teaching_updates (
      id INTEGER PRIMARY KEY, course_id TEXT NOT NULL, section_id TEXT NOT NULL,
      role TEXT NOT NULL, payload TEXT NOT NULL, ts TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS teaching_plans (
      id INTEGER PRIMARY KEY, course_id TEXT NOT NULL, section_id TEXT NOT NULL,
      version INTEGER NOT NULL,
      status TEXT NOT NULL CHECK (status IN ('active','superseded','finished')),
      created_by TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS teaching_items (
      id INTEGER PRIMARY KEY, plan_id INTEGER NOT NULL REFERENCES teaching_plans(id),
      parent_id INTEGER REFERENCES teaching_items(id),
      seq INTEGER NOT NULL DEFAULT 0,
      kind TEXT NOT NULL CHECK (kind IN ('milestone','section','sub','question')),
      title TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
      node_id TEXT, material_ref TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT 'pending',
      created_by TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_items_plan ON teaching_items(plan_id, parent_id);
    CREATE TABLE IF NOT EXISTS teaching_cursor (
      course_id TEXT PRIMARY KEY, plan_id INTEGER, item_id INTEGER,
      return_stack TEXT NOT NULL DEFAULT '[]',
      state_version INTEGER NOT NULL DEFAULT 0,
      updated_by TEXT, updated_at TEXT);
    ''')
    # M1.1 restructuring: the first-cut tables were superseded before any real
    # data existed. Drop them only when empty; keep a hard error otherwise.
    for legacy in ('teaching_batches', 'open_questions'):
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (legacy,)).fetchone()
        if exists:
            n = conn.execute('SELECT COUNT(*) FROM %s' % legacy).fetchone()[0]
            if n == 0:
                conn.execute('DROP TABLE %s' % legacy)
            else:  # pragma: no cover - safety net, never expected
                raise RuntimeError('%s is not empty; manual migration needed'
                                   % legacy)
    # M1 cursor table lacked item_id/state_version. Rebuild it in place,
    # carrying over whatever position data exists (item_id starts NULL).
    cur_cols = [r[1] for r in conn.execute('PRAGMA table_info(teaching_cursor)')]
    if cur_cols and 'item_id' not in cur_cols:
        with transaction(conn):
            conn.execute('ALTER TABLE teaching_cursor RENAME TO teaching_cursor_m1')
            conn.execute('''CREATE TABLE teaching_cursor (
              course_id TEXT PRIMARY KEY, plan_id INTEGER, item_id INTEGER,
              return_stack TEXT NOT NULL DEFAULT '[]',
              state_version INTEGER NOT NULL DEFAULT 0,
              updated_by TEXT, updated_at TEXT)''')
            conn.execute(
                'INSERT INTO teaching_cursor(course_id,plan_id,item_id,'
                'return_stack,state_version,updated_by,updated_at)'
                " SELECT course_id,plan_id,NULL,COALESCE(return_stack,'[]'),0,"
                'updated_by,updated_at FROM teaching_cursor_m1')
            conn.execute('DROP TABLE teaching_cursor_m1')
    # 2026-09-25: kind 增加 'section'（节层）。SQLite 不能改 CHECK，旧表就地
    # 重建：改名→建新表→整表复制（id 保留）→删旧表。行数很小，一次性完成。
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table'"
        " AND name='teaching_items'").fetchone()
    if row and "'section'" not in (row['sql'] or ''):
        with transaction(conn):
            conn.execute(
                'ALTER TABLE teaching_items RENAME TO teaching_items_pre_section')
            conn.execute('''CREATE TABLE teaching_items (
              id INTEGER PRIMARY KEY,
              plan_id INTEGER NOT NULL REFERENCES teaching_plans(id),
              parent_id INTEGER REFERENCES teaching_items(id),
              seq INTEGER NOT NULL DEFAULT 0,
              kind TEXT NOT NULL
                CHECK (kind IN ('milestone','section','sub','question')),
              title TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
              node_id TEXT, material_ref TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'pending',
              created_by TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')
            conn.execute(
                'INSERT INTO teaching_items SELECT * FROM teaching_items_pre_section')
            conn.execute('DROP TABLE teaching_items_pre_section')
            conn.execute(
                'CREATE INDEX IF NOT EXISTS idx_items_plan'
                ' ON teaching_items(plan_id, parent_id)')


def _norm_role(role):
    role = LEGACY_ROLES.get(role, role)
    if role not in ROLES:
        raise ValidationError('Invalid teacher role: %r' % role)
    return role


# ---------------------------------------------------------------- workspace
def read(conn, course_id, section_id=None):
    row = conn.execute('SELECT * FROM teaching_workspace WHERE course_id=?', (course_id,)).fetchone()
    workspace = dict(row) if row else None
    position_plan = current_plan(conn, course_id) if section_id is None else None
    sid = section_id or (position_plan['section_id'] if position_plan else
                         workspace['section_id'] if workspace else None)
    updates = [dict(r) for r in conn.execute(
        'SELECT id,course_id,section_id,role,ts,'
        " json_remove(payload,'$.turn_record','$.lesson_artifact','$.record_analysis') AS payload"
        ' FROM teaching_updates WHERE course_id=? AND section_id=? ORDER BY id', (course_id, sid))]
    topics, assessment, handoff = {}, None, None
    for item in updates:
        item['role'] = LEGACY_ROLES.get(item['role'], item['role'])
        p = json.loads(item['payload']); item['payload'] = p
        for topic in p.get('topics', []): topics[topic['title']] = topic
        if p.get('assessment'): assessment = p['assessment']
        if p.get('handoff'): handoff = p['handoff']
    lesson = conn.execute("SELECT content FROM lesson_artifacts WHERE node_id=? AND mode='intro'", (sid,)).fetchone()
    return dict(workspace=workspace, section_id=sid, topics=list(topics.values()),
                assessment=assessment, handoff=handoff, recent_updates=updates[-6:],
                lesson=lesson['content'] if lesson else None)


# ---------------------------------------------------------------- cursor
def _cursor(conn, course_id):
    row = conn.execute('SELECT * FROM teaching_cursor WHERE course_id=?',
                       (course_id,)).fetchone()
    if row is None:
        return None
    cur = dict(row)
    cur['return_stack'] = json.loads(cur['return_stack'])
    return cur


def _bump_cursor(conn, course_id, role, plan_id=None, item_id=None,
                 return_stack=None):
    # The selected item owns the plan/section; callers should not coordinate
    # three independent writes when moving to another existing chapter.
    if item_id is not None:
        target = conn.execute(
            'SELECT p.id,p.section_id FROM teaching_items i JOIN teaching_plans p'
            ' ON p.id=i.plan_id WHERE i.id=? AND p.course_id=?',
            (item_id, course_id)).fetchone()
        if target is None:
            raise ValidationError('Unknown teaching item in this course')
        plan_id = target['id']
        conn.execute(
            "INSERT INTO teaching_workspace(course_id,section_id,focus,status)"
            " VALUES(?,?,'','learning') ON CONFLICT(course_id) DO UPDATE SET"
            " focus=CASE WHEN teaching_workspace.section_id=excluded.section_id"
            " THEN teaching_workspace.focus ELSE '' END,"
            " status=CASE WHEN teaching_workspace.section_id=excluded.section_id"
            " THEN teaching_workspace.status ELSE 'learning' END,"
            ' section_id=excluded.section_id', (course_id, target['section_id']))
    cur = _cursor(conn, course_id)
    version = (cur['state_version'] if cur else 0) + 1
    if return_stack is None:
        return_stack = cur['return_stack'] if cur else []
    conn.execute(
        'INSERT INTO teaching_cursor(course_id,plan_id,item_id,return_stack,'
        'state_version,updated_by,updated_at) VALUES(?,?,?,?,?,?,?)'
        ' ON CONFLICT(course_id) DO UPDATE SET'
        ' plan_id=COALESCE(excluded.plan_id, teaching_cursor.plan_id),'
        ' item_id=COALESCE(excluded.item_id, teaching_cursor.item_id),'
        ' return_stack=excluded.return_stack,'
        ' state_version=excluded.state_version,'
        ' updated_by=excluded.updated_by, updated_at=excluded.updated_at',
        (course_id, plan_id, item_id, json.dumps(return_stack, ensure_ascii=False),
         version, role, _ts()))
    return version


def _check_fresh(conn, course_id, base_state_version):
    """Optimistic concurrency (kept per final wording): a window holding an
    older snapshot must not silently overwrite a newer position."""
    cur = _cursor(conn, course_id)
    if cur and base_state_version is not None \
            and cur['state_version'] != base_state_version:
        raise ValidationError(
            'Stale teaching state (version %s, current %s; call '
            'get_teaching_state to refresh)'
            % (base_state_version, cur['state_version']))


# ---------------------------------------------------------------- plans/items
def _active_plan(conn, course_id, section_id=None):
    row = None
    if section_id:
        row = conn.execute(
            "SELECT * FROM teaching_plans WHERE course_id=? AND section_id=?"
            " AND status='active' ORDER BY version DESC LIMIT 1",
            (course_id, section_id)).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT * FROM teaching_plans WHERE course_id=? AND status='active'"
            " ORDER BY version DESC, id DESC LIMIT 1", (course_id,)).fetchone()
    return dict(row) if row else None


def current_plan(conn, course_id):
    """One read-side position resolver, including legacy mismatched cursors.

    Item membership is stronger evidence than a stale cached plan ID. Reads
    never repair or rewrite learning evidence, and pending questions do not
    select a different current chapter.
    """
    cursor = _cursor(conn, course_id)
    if cursor and cursor['item_id']:
        row = conn.execute(
            'SELECT p.* FROM teaching_items i JOIN teaching_plans p ON p.id=i.plan_id'
            ' WHERE i.id=? AND p.course_id=?', (cursor['item_id'], course_id)).fetchone()
        if row:
            return dict(row)
    if cursor and cursor['plan_id']:
        row = conn.execute('SELECT * FROM teaching_plans WHERE id=? AND course_id=?',
                           (cursor['plan_id'], course_id)).fetchone()
        if row:
            return dict(row)
    workspace = conn.execute('SELECT section_id FROM teaching_workspace WHERE course_id=?',
                             (course_id,)).fetchone()
    return _active_plan(conn, course_id, workspace['section_id'] if workspace else None)


def _items(conn, plan_id):
    return [dict(r) for r in conn.execute(
        'SELECT * FROM teaching_items WHERE plan_id=?'
        ' ORDER BY COALESCE(parent_id, id), parent_id IS NOT NULL, seq, id',
        (plan_id,))]


def _children_of(items, parent_id):
    return [i for i in items if i['parent_id'] == parent_id]


def save_plan(conn, course_id, section_id, milestones, created_by='main', stage_key=None):
    """Create a new plan version: the main window anchors milestone-level
    items. Old versions are superseded, evidence kept. Item names, count and
    depth are never hardcoded — milestones are whatever the section needs."""
    if _norm_role(created_by) != 'main':
        raise ValidationError('Only the main window sets the teaching plan')
    node = get_node(conn, section_id)
    if node['course_id'] != course_id:
        raise ValidationError('Section does not belong to this course')
    if not milestones:
        raise ValidationError('A plan needs at least one milestone')
    for m in milestones:
        if not m.get('title'):
            raise ValidationError('Each milestone needs a title')
        if m.get('node_id'):
            get_node(conn, m['node_id'])  # validates id
    stage = None
    if stage_key is not None:
        stage = conn.execute('SELECT node_ids FROM course_outline WHERE course_id=? AND stage_key=?',
                             (course_id, stage_key)).fetchone()
        if stage is None:
            raise ValidationError('Unknown course outline stage')
    with transaction(conn):
        if stage is not None:
            node_ids = json.loads(stage['node_ids'] or '[]')
            if section_id not in node_ids:
                node_ids.append(section_id)
            conn.execute('UPDATE course_outline SET node_ids=? WHERE course_id=? AND stage_key=?',
                         (json.dumps(node_ids), course_id, stage_key))
        prev = conn.execute(
            "SELECT MAX(version) AS v FROM teaching_plans"
            " WHERE course_id=? AND section_id=?", (course_id, section_id)).fetchone()['v']
        conn.execute(
            "UPDATE teaching_plans SET status='superseded'"
            " WHERE course_id=? AND section_id=? AND status='active'",
            (course_id, section_id))
        cur = conn.execute(
            'INSERT INTO teaching_plans(course_id,section_id,version,status,created_by,created_at)'
            ' VALUES(?,?,?,?,?,?)',
            (course_id, section_id, (prev or 0) + 1, 'active', created_by, _ts()))
        plan_id = cur.lastrowid
        first = None
        for seq, m in enumerate(milestones):
            cur = conn.execute(
                "INSERT INTO teaching_items(plan_id,parent_id,seq,kind,title,node_id,"
                "material_ref,status,created_by,created_at,updated_at)"
                " VALUES(?,NULL,?,'milestone',?,?,?,'pending',?,?,?)",
                (plan_id, seq, m['title'], m.get('node_id'), m.get('material_ref', ''),
                 created_by, _ts(), _ts()))
            if first is None:
                first = cur.lastrowid
        version = _bump_cursor(conn, course_id, created_by,
                               plan_id=plan_id, item_id=first, return_stack=[])
    return {'success': True, 'plan_id': plan_id, 'version': (prev or 0) + 1,
            'state_version': version, 'current_item_id': first}


def _navigation(items, cursor):
    """Compact local navigation (final wording 2026-09-22 §2): parent path,
    return position, next planned item inside the current stage, and only
    then the next milestone. Advisory for the teaching AI — never a gate."""
    if not cursor or not cursor['item_id']:
        return None
    by_id = {i['id']: i for i in items}
    cur = by_id.get(cursor['item_id'])
    if cur is None:
        return None
    path = []
    p = cur['parent_id']
    while p is not None:
        node = by_id.get(p)
        if node is None:
            break
        path.append({'id': node['id'], 'title': node['title'],
                     'kind': node['kind']})
        p = node['parent_id']
    path.reverse()
    milestone_id = path[0]['id'] if path else cur['id']
    siblings = sorted((i for i in items
                       if i['parent_id'] == cur['parent_id']
                       and i['kind'] != 'question'
                       and i['status'] != 'retracted'),
                      key=lambda x: (x['seq'], x['id']))
    next_item = None
    seen = False
    for s in siblings:
        if s['id'] == cur['id']:
            seen = True
        elif seen and s['status'] in ('pending', 'active', 'deferred', 'presented'):
            next_item = {'id': s['id'], 'title': s['title'],
                         'status': s['status']}
            break
    if next_item is None:
        # 当前节/单元内没有下一个了：看一眼下一个节（或同级分组）的第一项，
        # 仍只是导航建议，不自动跳转（2026-09-25 节层适配）。
        parent = by_id.get(cur['parent_id'])
        if parent is not None:
            p_siblings = sorted((i for i in items
                                 if i['parent_id'] == parent['parent_id']
                                 and i['kind'] != 'question'
                                 and i['status'] != 'retracted'),
                                key=lambda x: (x['seq'], x['id']))
            seen = False
            for ps in p_siblings:
                if ps['id'] == parent['id']:
                    seen = True
                elif seen and ps['status'] in ('pending', 'active', 'deferred', 'presented'):
                    first_kid = next(
                        (k for k in sorted(
                            (i for i in items
                             if i['parent_id'] == ps['id']
                             and i['kind'] != 'question'
                             and i['status'] != 'retracted'),
                            key=lambda x: (x['seq'], x['id']))
                         if k['status'] in ('pending', 'active', 'deferred', 'presented')),
                        None)
                    if first_kid:
                        next_item = {'id': first_kid['id'],
                                     'title': first_kid['title'],
                                     'status': first_kid['status'],
                                     'via': ps['title']}
                    else:
                        next_item = {'id': ps['id'], 'title': ps['title'],
                                     'status': ps['status']}
                    break
    next_ms = None
    seen = False
    for m in sorted((i for i in items
                     if i['parent_id'] is None and i['status'] != 'retracted'),
                    key=lambda x: (x['seq'], x['id'])):
        if m['id'] == milestone_id:
            seen = True
        elif seen and m['status'] in ('pending', 'active'):
            next_ms = {'id': m['id'], 'title': m['title']}
            break
    ret = None
    if cursor['return_stack']:
        top = cursor['return_stack'][-1]
        ret = dict(top)
        ref = by_id.get(top.get('item_id'))
        if ref:
            ret['title'] = ref['title']
    return {'parent_path': path, 'milestone_id': milestone_id,
            'return_position': ret, 'next_item': next_item,
            'next_milestone': next_ms}


def question_reminders(items, cursor, limit=8):
    """Bounded unfinished branches, breadth-first so a deep dive can't hide siblings.

    Include carryovers outside the current subsection. This is navigation,
    never an advancement gate or a declaration that the learner cannot answer.
    """
    by_id = {i['id']: i for i in items}
    current_id = cursor.get('item_id') if cursor else None
    rows = []
    for q in items:
        if q['kind'] != 'question' or q['status'] not in (
                'open', 'awaiting_confirmation', 'deferred'):
            continue
        path, node, seen = [], q, set()
        while node and node['id'] not in seen:
            seen.add(node['id'])
            if node['status'] == 'retracted':
                break
            path.append({k: node[k] for k in ('id', 'title', 'kind')})
            node = by_id.get(node['parent_id'])
        if node and node['status'] == 'retracted':
            continue
        path.reverse()
        rows.append(dict(id=q['id'], parent_id=q['parent_id'], title=q['title'],
                         status=q['status'], note=q['note'][:240], path=path,
                         under_current=current_id in seen, seq=q['seq']))
    rows.sort(key=lambda r: (not r['under_current'], len(r['path']), r['seq'], r['id']))
    return dict(count=len(rows),
                awaiting_confirmation_count=sum(r['status'] == 'awaiting_confirmation' for r in rows),
                deferred_count=sum(r['status'] == 'deferred' for r in rows),
                items=[{k: v for k, v in r.items() if k != 'seq'} for r in rows[:limit]],
                has_more=len(rows) > limit)


def local_state(conn, course_id):
    """Position and local questions only. No lesson, history or global topics."""
    cursor = _cursor(conn, course_id)
    plan = current_plan(conn, course_id)
    items = _items(conn, plan['id']) if plan else []
    current = next((i for i in items if cursor and i['id'] == cursor['item_id']), None)
    # Cursor stays at a subsection. Questions may nest freely underneath it.
    ids = {current['id']} if current else set()
    for _ in range(len(items)):
        added = {i['id'] for i in items if i['parent_id'] in ids} - ids
        if not added:
            break
        ids.update(added)
    questions = [i for i in items if i['id'] in ids and i['kind'] == 'question'
                 and i['status'] in ('open', 'awaiting_confirmation', 'deferred')]
    brief = lambda i: {k: i[k] for k in ('id', 'parent_id', 'kind', 'title', 'status', 'note')}
    workspace = conn.execute('SELECT section_id FROM teaching_workspace WHERE course_id=?',
                             (course_id,)).fetchone()
    return {'section_id': plan['section_id'] if plan else (workspace['section_id'] if workspace else None),
            'state_version': cursor['state_version'] if cursor else 0,
            'cursor': {'item_id': cursor['item_id'], 'state_version': cursor['state_version']} if cursor else None,
            'current_item': brief(current) if current else None,
            'navigation': _navigation(items, cursor),
            'questions': {'count': len(questions), 'items': [brief(i) for i in questions[:5]]},
            'reminders': question_reminders(items, cursor)}


def records_for_item(conn, course_id, item_id, after_id=0, limit=5):
    """Explicit, paginated raw-record read for handoff organization, not each reply."""
    item = conn.execute('SELECT p.section_id FROM teaching_items i JOIN teaching_plans p'
                        ' ON p.id=i.plan_id WHERE i.id=? AND p.course_id=?',
                        (item_id, course_id)).fetchone()
    if item is None:
        raise ValidationError('Unknown item in this course')
    limit = max(1, min(int(limit), 20))
    rows = conn.execute(
        'SELECT id,role,ts,payload FROM teaching_updates WHERE course_id=? AND section_id=?'
        ' AND id>? AND (json_extract(payload,\'$.turn_record.item_id\')=?'
        ' OR json_extract(payload,\'$.handoff.item_id\')=?) ORDER BY id LIMIT ?',
        (course_id, item['section_id'], after_id, item_id, item_id, limit + 1)).fetchall()
    records = []
    for row in rows[:limit]:
        payload = json.loads(row['payload'])
        records.append({'id': row['id'], 'role': row['role'], 'ts': row['ts'],
                        'turn_record': payload.get('turn_record'), 'handoff': payload.get('handoff')})
    return {'item_id': item_id, 'records': records, 'has_more': len(rows) > limit,
            'next_after_id': records[-1]['id'] if records else after_id}


def get_state(conn, course_id, full=False):
    """Teaching state for window recovery. Compact by default: milestone
    outline with child counts, cursor, open questions. full=True adds every
    item and untrimmed updates (acceptance/review only)."""
    shared = read(conn, course_id)
    sid = shared['section_id']
    plan = current_plan(conn, course_id)
    if plan:
        sid = plan['section_id']
    items = _items(conn, plan['id']) if plan else []
    cursor = _cursor(conn, course_id)
    if plan and cursor:
        cursor = dict(cursor, plan_id=plan['id'])
    if shared['workspace'] and sid != shared['workspace']['section_id']:
        shared['workspace'] = dict(shared['workspace'], section_id=sid, focus='')
    milestones, current = [], None
    live = [i for i in items if i['status'] != 'retracted']

    def _descendants(root_id):
        desc = []
        stack = [root_id]
        while stack:
            pid = stack.pop()
            for k in _children_of(live, pid):
                desc.append(k)
                stack.append(k['id'])
        return desc

    def _teach_leaves(root_id):
        """小节口径：root 下所有"可教学叶子"= 不带 sub/section 子级的 sub。
        单元（插件系统等）一旦分了节/小节就不再自己计数，由叶子承担分母；
        未拆分的单元暂时自己算一项。retracted 已排除。"""
        return [d for d in _descendants(root_id) if d['kind'] == 'sub'
                and not any(c['kind'] in ('sub', 'section')
                            for c in _children_of(live, d['id']))]

    for m in _children_of(live, None):
        desc = _descendants(m['id'])
        leaves = [d for d in desc if d['kind'] == 'sub'
                  and not any(c['kind'] in ('sub', 'section')
                              for c in _children_of(live, d['id']))]
        entry = {'id': m['id'], 'seq': m['seq'], 'title': m['title'],
                 'status': m['status'], 'node_id': m['node_id'],
                 'material_ref': m['material_ref'],
                 'subs': {'total': len(leaves),
                          'done': sum(1 for k in leaves if k['status'] == 'done'),
                          'presented': sum(1 for k in leaves
                                           if k['status'] == 'presented'),
                          'open_questions': sum(
                              1 for k in desc
                              if k['kind'] == 'question'
                              and k['status'] in ('open', 'awaiting_confirmation')),
                          'self_reported_understood': sum(
                              1 for k in leaves if k['status'] == 'self_reported_understood')}}
        milestones.append(entry)
    if cursor and cursor['item_id']:
        cur_item = next((i for i in items if i['id'] == cursor['item_id']), None)
        if cur_item:
            kids = _children_of(items, cur_item['id'])
            current = dict(cur_item)
            current['children'] = kids if full else [
                {'id': k['id'], 'kind': k['kind'], 'title': k['title'],
                 'status': k['status']} for k in kids]
    def _brief(q):
        parent = next((i for i in items if i['id'] == q['parent_id']), None)
        return {'id': q['id'], 'title': q['title'], 'note': q['note'], 'status': q['status'],
                'parent_id': q['parent_id'],
                'parent_title': parent['title'] if parent else ''}
    q_all = [q for q in items if q['kind'] == 'question']
    q_open = [q for q in q_all if q['status'] in ('open', 'awaiting_confirmation')]
    q_deferred = [q for q in q_all if q['status'] == 'deferred']
    questions = {'open_count': len(q_open), 'deferred_count': len(q_deferred),
                 'open': [_brief(q) for q in q_open[:5]],
                 'deferred': [_brief(q) for q in q_deferred[:5]]}
    state = {
        'course_id': course_id, 'section_id': sid,
        'state_version': cursor['state_version'] if cursor else 0,
        'workspace': shared['workspace'],
        'plan': plan, 'milestones': milestones, 'cursor': cursor,
        'current_item': current,
        'navigation': _navigation(items, cursor),
        'questions': questions,
        'reminders': question_reminders(items, cursor),
        'handoff': shared['handoff'],
        'topics': [{'title': t['title'], 'status': t['status']}
                   for t in shared['topics']],
        'assessment': shared['assessment'],
        'recent_updates': [
            {'role': u['role'], 'ts': u['ts'],
             'keys': sorted(k for k, v in u['payload'].items() if v)}
            for u in shared['recent_updates'][-3:]],
    }
    if full:
        state['items'] = items
        state['recent_updates_full'] = shared['recent_updates']
        state['lesson'] = shared['lesson']
    return state


def get_tree(conn, course_id):
    """The active plan's full item tree for the page's current-learning view.
    Page-side data (TODO: 页面需要全局信息不代表教学 AI 每次也读全局) —
    teaching windows keep using the compact get_state/profiles instead.
    Items are small rows (id/parent/seq/kind/title/note/status); the tree
    renders collapsed by default on the page."""
    plan = current_plan(conn, course_id)
    items = []
    if plan:
        items = [
            {'id': i['id'], 'parent_id': i['parent_id'], 'seq': i['seq'],
             'kind': i['kind'], 'title': i['title'], 'note': i['note'],
             'status': i['status']}
            for i in _items(conn, plan['id'])]
    cursor = _cursor(conn, course_id)
    section = plan['section_id'] if plan else None
    if plan and cursor:
        cursor = dict(cursor, plan_id=plan['id'])
    topic_groups = None
    if section:
        # 本次树与全局树读同一份整理结果（organize 覆盖层；原始记录不改写）
        from . import organize
        topic_groups = organize.organized_topics(conn, course_id, section)
    return {
        'course_id': course_id,
        'section_id': section,
        'plan': plan,
        'items': items,
        'cursor': cursor,
        'navigation': _navigation(items, cursor),
        'topic_groups': topic_groups,
        'reminders': question_reminders(items, cursor),
    }


def unit_outline(conn_or_items, current_item_id):
    """当前单元的 节→小节 两级目录（2026-09-25 节层）。

    单元 = 游标项的深度 1 祖先（或直接子级即单元的情形）；节 = 单元下
    kind='section' 的分组标题；小节 = 节下的 sub。未分节的单元的直属 sub
    进 loose_subs。retracted 一律不进目录。返回 None 表示游标不在单元内。
    """
    items = conn_or_items
    by_id = {i['id']: i for i in items}
    cur = by_id.get(current_item_id)
    if cur is None:
        return None
    live = [i for i in items if i['status'] != 'retracted']

    def _kids(pid, kinds=None):
        return [i for i in live if i['parent_id'] == pid
                and i['kind'] != 'question'
                and (kinds is None or i['kind'] in kinds)]

    # 向上找：当前节（最近的 section 祖先/自身）与单元（深度 1 节点）。
    unit, section, node = None, None, cur
    while node is not None:
        if section is None and node['kind'] == 'section' and node is not cur:
            section = node
        parent = by_id.get(node['parent_id'])
        if parent is not None and parent['parent_id'] is None:
            unit = node if node['kind'] != 'milestone' else None
            break
        if parent is None:
            unit = node if node['kind'] != 'milestone' else None
            break
        node = parent
    if cur['kind'] == 'section':
        section = cur
        if unit is None:
            unit = by_id.get(cur['parent_id'])
    if unit is None:
        return None
    sections = []
    for s in _kids(unit['id'], ('section',)):
        sections.append({
            'id': s['id'], 'title': s['title'], 'status': s['status'],
            'subs': [{'id': k['id'], 'title': k['title'], 'status': k['status']}
                     for k in _kids(s['id'], ('sub',))]})
    loose = [{'id': k['id'], 'title': k['title'], 'status': k['status']}
             for k in _kids(unit['id'], ('sub',))]
    return {'unit': {'id': unit['id'], 'title': unit['title'],
                     'status': unit['status']},
            'current_section': section['id'] if section else None,
            'sections': sections, 'loose_subs': loose}


# ---------------------------------------------------------------- commit
def commit(conn, course_id, section_id, role, topics=None, focus=None,
           assessment=None, handoff=None, decision=None, next_section_id=None,
           current_item_id=None, items_add=None, items_update=None,
           base_state_version=None,
           push_return_position=None, pop_return_position=False,
           verbose=False, turn_record=None, record_analysis=None,
           current_item_key=None):
    """One merged write per reply (final wording §四): topic updates, item
    tree edits, cursor move and chapter handoff in a single call. Returns
    minimal state unless verbose=True."""
    role = _norm_role(role)
    node = get_node(conn, section_id)
    if node['course_id'] != course_id:
        raise ValidationError('Invalid course or section')
    analysis_key = None
    analysis_only = False
    if record_analysis is not None:
        if not isinstance(record_analysis, dict) or not record_analysis.get('source_ref') \
                or not record_analysis.get('summary'):
            raise ValidationError('record_analysis needs source_ref and summary')
        # Exact repeated imports reuse the receipt, including after a cursor move.
        # A changed report or changed sync operations is a new deliberate update.
        receipt = dict(report=record_analysis, role=role, topics=topics or [],
                       focus=focus, assessment=assessment, handoff=handoff,
                       decision=decision, next_section_id=next_section_id,
                       current_item_id=current_item_id, current_item_key=current_item_key,
                       items_add=items_add or [],
                       items_update=items_update or [], turn_record=turn_record,
                       push_return_position=push_return_position,
                       pop_return_position=pop_return_position)
        analysis_key = hashlib.sha256(json.dumps(receipt, sort_keys=True,
            ensure_ascii=False).encode('utf-8')).hexdigest()
        previous = conn.execute(
            "SELECT id,payload FROM teaching_updates WHERE course_id=? AND section_id=?"
            " AND json_extract(payload,'$.analysis_key')=? ORDER BY id DESC LIMIT 1",
            (course_id, section_id, analysis_key)).fetchone()
        if previous:
            return dict(success=True, reused=True, record_id=previous['id'],
                        item_refs=json.loads(previous['payload']).get('item_refs', {}),
                        state_version=(_cursor(conn, course_id) or {}).get('state_version', 0))
        analysis_only = not any((topics, focus is not None, assessment, handoff,
                                 decision, next_section_id, current_item_id is not None,
                                 current_item_key is not None,
                                 items_add, items_update, turn_record,
                                 push_return_position, pop_return_position))
    topics = topics or []
    for t in topics:
        if not t.get('title') or t.get('status') not in (
                'untouched', 'self_reported_understood', 'explained',
                'question', 'revisit'):
            raise ValidationError('Each topic needs title and a valid learning status')
    if role == 'control' and (assessment or decision or next_section_id):
        raise ValidationError('The control window records evidence only; it never judges')
    if assessment and (assessment.get('result') not in ('passed', 'revisit') or not assessment.get('evidence')):
        raise ValidationError('Assessment needs result and question/answer evidence')
    if decision not in (None, 'passed', 'revisit'):
        raise ValidationError('Invalid chapter decision')
    if role != 'main' and (decision or next_section_id):
        raise ValidationError('Only the main teacher advances the course')
    _check_fresh(conn, course_id, base_state_version)
    current = read(conn, course_id, section_id)
    evidence = assessment or current['assessment']
    if decision == 'passed' and (not evidence or evidence['result'] != 'passed'):
        raise ValidationError('Passing requires a chapter assessment')
    if next_section_id:
        if decision != 'passed' or get_node(conn, next_section_id)['course_id'] != course_id:
            raise ValidationError('Advance only after chapter approval in this course')

    plan = _active_plan(conn, course_id, section_id)
    items_add = [dict(item) for item in (items_add or [])]
    items_update = items_update or []
    if (items_add or items_update or current_item_id is not None or current_item_key is not None) and not plan:
        raise ValidationError('No active plan; the main window must call'
                              ' save_teaching_plan first')
    plan_items = {i['id']: i for i in _items(conn, plan['id'])} if plan else {}
    cursor_now = _cursor(conn, course_id)
    default_parent = current_item_id or (cursor_now['item_id'] if cursor_now else None)
    if turn_record is not None:
        if not isinstance(turn_record, dict):
            raise ValidationError('turn_record must be an object')
        turn_record = dict(turn_record)
        turn_record.setdefault('item_id', default_parent)
        if turn_record.get('item_id') not in plan_items:
            raise ValidationError('turn_record needs an item in the current plan')
        if turn_record.get('question_id') is not None:
            q = plan_items.get(turn_record['question_id'])
            if not q or q['kind'] != 'question':
                raise ValidationError('Unknown question for turn_record')
        for key in ('user_text', 'assistant_text', 'user_confirmation'):
            if key in turn_record and not isinstance(turn_record[key], str):
                raise ValidationError('turn_record %s must be text' % key)
    known_keys = set()
    seen_record_refs = set()
    record_matches = {i['material_ref']: i for i in plan_items.values()
                      if i['material_ref'].startswith('learning-record:')}
    for a in items_add:
        if not a.get('title'):
            raise ValidationError('Each new item needs a title')
        if a.get('kind', 'sub') not in ('section', 'sub', 'question'):
            raise ValidationError("items_add kind must be 'section', 'sub' or"
                                  " 'question' (milestones come from"
                                  ' save_teaching_plan)')
        # 分节是结构修改，归 main（2026-09-25 权限定稿：细节窗口讲解时产生
        # 小节/追问，结构层变动发消息请 main 执行）。
        if a.get('kind') == 'section' and role != 'main':
            raise ValidationError('Only the main window adds sections')
        key = a.get('key')
        if key is not None and (not isinstance(key, str) or not key or key in known_keys):
            raise ValidationError('Each item key must be unique non-empty text')
        parent_key = a.get('parent_key')
        if parent_key is not None and (parent_key not in known_keys or a.get('parent_id') is not None):
            raise ValidationError('parent_key must reference an earlier item in this commit')
        parent = a.get('parent_id') or default_parent
        if parent is None and parent_key is None:
            raise ValidationError('items_add needs parent_id or an active cursor'
                                  ' position (call get_teaching_state first)')
        if parent_key is None and plan_items and parent not in plan_items:
            raise ValidationError('Unknown parent item: %r' % parent)
        if parent_key is None:
            a['parent_id'] = parent
        status = a.get('status', 'open' if a.get('kind') == 'question' else 'pending')
        if status not in ITEM_STATUSES or status == 'retracted':
            raise ValidationError('Invalid initial item status')
        if status == 'done' and role != 'main':
            raise ValidationError('Only the main teacher marks an item done')
        a['status'] = status
        if a.get('record_key'):
            if not record_analysis or not isinstance(a['record_key'], str):
                raise ValidationError('record_key needs a learning-record analysis source')
            source_key = hashlib.sha256(record_analysis['source_ref'].encode('utf-8')).hexdigest()
            a['material_ref'] = 'learning-record:' + source_key + ':' + a['record_key']
            if a['material_ref'] in seen_record_refs:
                raise ValidationError('Repeated record_key within this import')
            seen_record_refs.add(a['material_ref'])
            match = record_matches.get(a['material_ref'])
            if match:
                if match['kind'] != a.get('kind', 'sub') or match['status'] == 'retracted':
                    raise ValidationError('record_key refers to an incompatible item; align existing IDs first')
                a['_existing_id'] = match['id']
        if key is not None:
            known_keys.add(key)
    _STRUCT_KEYS = ('title', 'seq', 'parent_id')
    for u in items_update:
        it = plan_items.get(u.get('id'))
        if it is None:
            raise ValidationError('Unknown item: %r' % u.get('id'))
        if u.get('status') and u['status'] not in ITEM_STATUSES:
            raise ValidationError('Invalid item status: %r' % u['status'])
        # done 是验证通过；detail 可另记用户自述理解，但不生成掌握证据。
        if u.get('status') == 'done' and role != 'main':
            raise ValidationError('Only the main window marks an item done')
        # 结构修改（改名/排序/换父级/作废）仅 main；已作废项的翻动也仅 main。
        structural = any(u.get(k) is not None for k in _STRUCT_KEYS) \
            or u.get('status') == 'retracted' or it['status'] == 'retracted'
        if structural and role != 'main':
            raise ValidationError(
                'Only the main window edits item structure'
                ' (title/seq/parent/retract); detail asks main first')
        if u.get('title') is not None and not str(u['title']).strip():
            raise ValidationError('Item title cannot be empty')
        if u.get('parent_id') is not None:
            np_ = plan_items.get(u['parent_id'])
            if np_ is None:
                raise ValidationError('Unknown parent item: %r' % u['parent_id'])
            # 防环：新父级不能是自己或自己的后代
            walk, seen_ids = np_, set()
            while walk is not None:
                if walk['id'] == it['id'] or walk['id'] in seen_ids:
                    raise ValidationError('parent_id would create a cycle')
                seen_ids.add(walk['id'])
                walk = plan_items.get(walk['parent_id'])
    if current_item_id is not None and current_item_id not in plan_items:
        raise ValidationError('Unknown item: %r' % current_item_id)
    if current_item_key is not None and (current_item_key not in known_keys or current_item_id is not None):
        raise ValidationError('current_item_key must reference this commit and cannot accompany current_item_id')
    if push_return_position is not None:
        # 进入递归追问必须留 brief：父问题/停留位置/未完成内容。
        # 解决子问题后据此返回，不凭记忆找回父项（2026-09-24 讲解纪律）。
        if not isinstance(push_return_position, dict) \
                or push_return_position.get('item_id') not in plan_items \
                or not str(push_return_position.get('brief', '')).strip():
            raise ValidationError(
                'push_return_position needs a known item_id and a non-empty'
                ' brief (父问题、停留位置、未完成内容)')

    changed = {'items_added': [], 'items_updated': []}
    item_refs = {}
    with transaction(conn):
        payload = dict(topics=topics, assessment=assessment, handoff=handoff,
                       decision=decision, current_item_id=current_item_id,
                       items_add=items_add, items_update=items_update,
                       turn_record=turn_record)
        if record_analysis is not None:
            payload.update(record_analysis=record_analysis, analysis_key=analysis_key)
        update = conn.execute('INSERT INTO teaching_updates(course_id,section_id,role,payload,ts) VALUES(?,?,?,?,?)',
                     (course_id, section_id, role, json.dumps(payload, ensure_ascii=False), _ts()))
        row = current['workspace']
        if not analysis_only and (row is None or role == 'main'):
            status = decision or ('awaiting_review' if assessment else 'learning')
            conn.execute('INSERT INTO teaching_workspace VALUES(?,?,?,?) ON CONFLICT(course_id) DO UPDATE SET section_id=excluded.section_id,focus=excluded.focus,status=excluded.status',
                         (course_id, next_section_id or section_id, '' if next_section_id else (focus or ''), 'learning' if next_section_id else status))
        elif not analysis_only and row['section_id'] == section_id:
            conn.execute('UPDATE teaching_workspace SET focus=?,status=? WHERE course_id=?',
                         (focus if focus is not None else row['focus'], 'awaiting_review' if assessment else row['status'], course_id))
        if decision:
            conn.execute("INSERT INTO events(node_id,ts,type,payload) VALUES(?,?,'attempt',?)",
                         (section_id, _ts(), json.dumps(dict(
                             result='correct' if decision == 'passed' else 'partial',
                             hint_level=evidence.get('hint_level', 0) if evidence else 0,
                             response_summary=evidence, mistake_signatures=[],
                             record_kind='chapter_decision'), ensure_ascii=False)))
        bumped = False
        for a in items_add:
            kind = a.get('kind', 'sub')
            parent_id = item_refs[a['parent_key']] if a.get('parent_key') is not None else a['parent_id']
            if a.get('_existing_id'):
                item_id = a['_existing_id']
                old = plan_items[item_id]
                if old['parent_id'] != parent_id:
                    raise ValidationError('Existing record parent differs; use explicit structural update')
                # Reanalysis never downgrades verified/user-confirmed evidence.
                preserve = old['status'] == 'done' or (
                    old['status'] in ('resolved', 'self_reported_understood')
                    and a['status'] in ('pending', 'active', 'open', 'presented', 'awaiting_confirmation'))
                if not preserve:
                    conn.execute('UPDATE teaching_items SET status=?,note=?,updated_at=? WHERE id=?',
                                 (a['status'], a.get('note', old['note']), _ts(), item_id))
                changed['items_updated'].append(item_id)
                bumped = True
                if a.get('key') is not None:
                    item_refs[a['key']] = item_id
                continue
            cur = conn.execute(
                'INSERT INTO teaching_items(plan_id,parent_id,seq,kind,title,note,'
                'node_id,material_ref,status,created_by,created_at,updated_at)'
                ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (plan['id'], parent_id,
                 a.get('seq', 0), kind, a['title'], a.get('note', ''),
                 a.get('node_id'), a.get('material_ref', ''), a['status'],
                 role, _ts(), _ts()))
            changed['items_added'].append(cur.lastrowid)
            if a.get('key') is not None:
                item_refs[a['key']] = cur.lastrowid
            bumped = True
        for u in items_update:
            conn.execute(
                'UPDATE teaching_items SET status=COALESCE(?,status),'
                ' note=COALESCE(?,note),'
                ' title=COALESCE(?,title), seq=COALESCE(?,seq),'
                ' parent_id=COALESCE(?,parent_id), updated_at=? WHERE id=?',
                (u.get('status'), u.get('note'),
                 u.get('title'), u.get('seq'), u.get('parent_id'),
                 _ts(), u['id']))
            changed['items_updated'].append(u['id'])
            bumped = True
        version = None
        returned_to = None
        if bumped or current_item_id is not None or current_item_key is not None or push_return_position \
                or pop_return_position:
            stack = None
            move_to = item_refs[current_item_key] if current_item_key is not None else current_item_id
            if push_return_position or pop_return_position:
                cur = _cursor(conn, course_id)
                stack = cur['return_stack'] if cur else []
                if push_return_position:
                    stack = stack + [push_return_position]
                else:
                    popped = stack[-1] if stack else None
                    stack = stack[:-1]
                    # 追问结束返回原位置；显式 current_item_id 优先于弹出位置
                    if popped:
                        returned_to = popped
                        if move_to is None and popped.get('item_id'):
                            move_to = popped['item_id']
            version = _bump_cursor(conn, course_id, role,
                                   item_id=move_to, return_stack=stack)
        if item_refs:
            payload['item_refs'] = item_refs
            conn.execute('UPDATE teaching_updates SET payload=? WHERE id=?',
                         (json.dumps(payload, ensure_ascii=False), update.lastrowid))
    result = {'success': True, 'course_id': course_id, 'section_id': section_id,
              'record_id': update.lastrowid,
              'state_version': version if version is not None
              else (_cursor(conn, course_id) or {'state_version': 0})['state_version'],
              'changed': changed,
              'item_refs': item_refs,
              'open_question_count': sum(
                  1 for i in (_items(conn, plan['id']) if plan else [])
                  if i['kind'] == 'question' and i['status'] in ('open', 'awaiting_confirmation'))}
    cur = _cursor(conn, course_id)
    if cur:
        result['cursor'] = {'item_id': cur['item_id'],
                            'state_version': cur['state_version'],
                            'return_depth': len(cur['return_stack'])}
    if returned_to:
        ref = plan_items.get(returned_to.get('item_id'))
        result['returned_to'] = {
            'item_id': returned_to.get('item_id'),
            'title': ref['title'] if ref else '',
            'brief': returned_to.get('brief', '')}
    if verbose:
        result['state'] = get_state(conn, course_id, full=True)
    return result


# ---------------------------------------------------------------- stagnation
def stagnation_hint(conn, course_id, node_id, threshold=STAGNATION_THRESHOLD):
    """Stagnation exit (TODO §5): N consecutive process records on one node
    without progress -> suggest checking upstream/downstream instead of
    re-explaining the same local detail."""
    rows = conn.execute(
        'SELECT type, payload FROM events WHERE node_id=? ORDER BY id DESC LIMIT ?',
        (node_id, threshold)).fetchall()
    if len(rows) < threshold:
        return None
    for r in rows:
        p = json.loads(r['payload'])
        if r['type'] == 'attempt' and p.get('result') == 'correct':
            return None
    from .graph import parents_of, prerequisites_of
    upstream = ([n['title'] for n in parents_of(conn, node_id)]
                + [n['title'] for n in prerequisites_of(conn, node_id)])
    downstream = [dict(id=r['dst'], title=r['title']) for r in conn.execute(
        "SELECT e.dst, n.title FROM edges e JOIN nodes n ON n.id=e.dst"
        " WHERE e.src=? AND e.type='sequence'", (node_id,))]
    return {
        'triggered': True,
        'consecutive_records': len(rows),
        'node_id': node_id,
        'suggestion': ('该节点已连续 %d 条记录无推进。不要继续换措辞重复局部细节；'
                       '先检查：最终要完成什么、输入从哪来、输出交给谁，'
                       '必要时回退上游或先看下游真实用途。' % len(rows)),
        'upstream': upstream,
        'downstream': downstream,
    }
