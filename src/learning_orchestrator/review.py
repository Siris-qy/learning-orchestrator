"""Knowledge-point review scheduling (M3).

Closed loop: 今日清单 → 按需取材料出题 → 回答后记录 → 更新下次日期.
Fixed Ebbinghaus intervals with level rules (TODO §8.5): correct (hint<=1)
→ level+1; partial → level-1 (floor 0); wrong → level 0, next day; 起算点 =
last review action; overdue never penalised; daily cap 15 by most-overdue
first; unfinished rolls over.

口径 (2026-09-22, see TODO milestones):
1. Review items are knowledge POINTS (e.g. TCP 握手 vs 可靠传输 are tracked
   separately); the body text stays in its knowledge-block file.
2. Legacy entries without dates/verification stay 'unknown' — never defaulted
   to mastered, never mass-converted into overdue tasks.
3. The daily 15 is a cap, not a quota. No penalty, no blocking new learning.

Material for quiz building comes from the point's own knowledge-block chunk
(lecture_ref='知识块正文'); index files are for locating only — search
snippets are not the textbook.
"""
import json
import re
from datetime import date, datetime, timedelta, timezone

from .db import dicts, transaction
from .graph import ValidationError, now_iso

INTERVALS = (1, 2, 4, 7, 15, 30)  # days; top level repeats
DAILY_CAP = 15
RESULTS = ('correct', 'partial', 'wrong')

# | [T02 三次握手与状态机](知识块/03-tcp.md#T02) | 02 | 先练 | 已学习记录，待复述 | — | — |
_ROW = re.compile(
    r'^\|\s*\[([A-Z]+\d+)\s+([^\]]+)\]\(([^)#]+)#([A-Z]+\d+)\)'
    r'\s*\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|')
_DATE = re.compile(r'(\d{4})-(\d{1,2})-(\d{1,2})')


def setup(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS review_items(
      id INTEGER PRIMARY KEY,
      course_id TEXT NOT NULL,
      point_id TEXT NOT NULL,
      title TEXT NOT NULL,
      source_id TEXT REFERENCES sources(id),
      anchor TEXT NOT NULL DEFAULT '',
      priority TEXT NOT NULL DEFAULT '',
      weak_candidate INTEGER NOT NULL DEFAULT 0,
      status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (status IN ('unknown','active')),
      level INTEGER NOT NULL DEFAULT 0,
      last_reviewed TEXT,
      next_due TEXT,
      created_at TEXT NOT NULL,
      UNIQUE(course_id, point_id));
    CREATE INDEX IF NOT EXISTS idx_review_course
      ON review_items(course_id, status, next_due);
    ''')


def _parse_date(text):
    m = _DATE.search(text or '')
    if not m:
        return None
    return '%04d-%02d-%02d' % (int(m.group(1)), int(m.group(2)),
                               int(m.group(3)))


def seed_from_sheet(conn, course_id, sheet_path, source_by_file):
    """Parse the review sheet (markdown table) into review_items. Idempotent:
    INSERT OR IGNORE — re-seeding never overwrites scheduling state.
    Rows whose dates are empty stay 'unknown' (口径 2). Rows that do carry
    dates (the user filled the sheet) become active at level 0 from those
    dates; nothing is marked mastered."""
    text = open(sheet_path, encoding='utf-8').read()
    parsed = []
    for line in text.splitlines():
        m = _ROW.match(line.strip())
        if not m:
            continue
        point_id, title, rel_file, frag, _chain, priority, state, last, nxt = \
            (g.strip() for g in m.groups())
        if frag != point_id:
            continue  # link anchor must match the row id
        parsed.append({
            'point_id': point_id, 'title': title,
            'source_id': source_by_file.get(rel_file),
            'anchor': '%s %s' % (point_id, title),
            'priority': priority,
            'weak': 1 if '薄弱候选' in state else 0,
            'last': _parse_date(last), 'due': _parse_date(nxt),
        })
    inserted = 0
    with transaction(conn):
        for p in parsed:
            cur = conn.execute(
                'INSERT OR IGNORE INTO review_items(course_id,point_id,title,'
                'source_id,anchor,priority,weak_candidate,status,level,'
                'last_reviewed,next_due,created_at)'
                ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (course_id, p['point_id'], p['title'], p['source_id'],
                 p['anchor'], p['priority'], p['weak'],
                 'active' if p['due'] else 'unknown', 0,
                 p['last'], p['due'], now_iso()))
            inserted += cur.rowcount
    return {'parsed': len(parsed), 'inserted': inserted,
            'without_source': sum(1 for p in parsed if not p['source_id'])}


def _get(conn, item_id):
    row = conn.execute('SELECT * FROM review_items WHERE id=?',
                       (item_id,)).fetchone()
    if row is None:
        raise ValidationError('Unknown review item: %r' % item_id)
    return dict(row)


def iter_items(conn, course_id):
    """All review knowledge points with their note source titles, for the
    knowledge catalog (page view; scheduling fields stay in today/overview)."""
    return dicts(conn.execute(
        'SELECT r.id, r.point_id, r.title, r.anchor, r.status, r.priority, r.source_id,'
        ' s.title AS source_title'
        ' FROM review_items r LEFT JOIN sources s ON s.id = r.source_id'
        ' WHERE r.course_id=? ORDER BY r.point_id', (course_id,)))


def overview(conn, course_id):
    rows = dicts(conn.execute(
        'SELECT status, next_due, weak_candidate FROM review_items'
        ' WHERE course_id=?', (course_id,)))
    today_s = date.today().isoformat()
    return {
        'total': len(rows),
        'unknown': sum(1 for r in rows if r['status'] == 'unknown'),
        'active': sum(1 for r in rows if r['status'] == 'active'),
        'due_today': sum(1 for r in rows if r['status'] == 'active'
                         and r['next_due'] and r['next_due'] <= today_s),
        'weak_candidates': sum(1 for r in rows if r['weak_candidate']),
        'daily_cap': DAILY_CAP,
    }


def today(conn, course_id, limit=DAILY_CAP, on=None):
    """Today's review menu: due active items (most overdue first), then
    unknown points to fill the remaining capacity (先练 priority and weak
    candidates first). The cap is a ceiling, not a quota (口径 3)."""
    today_s = (on or date.today()).isoformat()
    due = dicts(conn.execute(
        "SELECT * FROM review_items WHERE course_id=? AND status='active'"
        ' AND next_due IS NOT NULL AND next_due <= ?'
        ' ORDER BY next_due, point_id LIMIT ?',
        (course_id, today_s, limit)))
    for d in due:
        d['overdue_days'] = (
            date.fromisoformat(today_s)
            - date.fromisoformat(d['next_due'])).days
        d['kind'] = 'due'
    remaining = limit - len(due)
    fresh = []
    if remaining > 0:
        fresh = dicts(conn.execute(
            "SELECT * FROM review_items WHERE course_id=? AND status='unknown'"
            " ORDER BY (priority='先练') DESC, weak_candidate DESC, point_id"
            ' LIMIT ?', (course_id, remaining)))
        for f in fresh:
            f['overdue_days'] = 0
            f['kind'] = 'new'
    return {'date': today_s, 'cap': limit, 'items': due + fresh,
            'due_total': conn.execute(
                "SELECT COUNT(*) FROM review_items WHERE course_id=?"
                " AND status='active' AND next_due IS NOT NULL"
                ' AND next_due <= ?', (course_id, today_s)).fetchone()[0],
            'unknown_total': conn.execute(
                "SELECT COUNT(*) FROM review_items WHERE course_id=?"
                " AND status='unknown'", (course_id,)).fetchone()[0]}


def prepare(conn, item_id):
    """Material for building a closed-book question: the point's OWN chunk
    from its knowledge-block source — never an index file, never a search
    snippet (M2.5 review note). The AI reads this to quiz; it is not shown
    to the learner before they answer."""
    item = _get(conn, item_id)
    chunk = None
    node_id = None
    # Canonical knowledge bodies are authoritative when this review point is
    # bound to one. Keep source/chunk behavior for unbound legacy review points.
    from . import content, question_links, review_graph
    if question_links.exists(conn, 'review_graph_nodes'):
        binding = conn.execute("SELECT node_id FROM review_graph_bindings WHERE ref_type='review_point' "
                               'AND course_id=? AND ref_id=?', (item['course_id'], item['point_id'])).fetchone()
        node_id = binding['node_id'] if binding else item['point_id']
        node_id = review_graph._canonical(conn, node_id)
        row = conn.execute('SELECT payload FROM review_graph_nodes WHERE id=?', (node_id,)).fetchone()
        ref = json.loads(row['payload']).get('content_ref') if row else None
        if ref and ref.get('type') in ('knowledge_point', 'knowledge_block'):
            resolved = content.resolve(conn, ref)
            chunk = {'anchor': item['title'], 'text': resolved['body'],
                     'node_id': node_id, 'content_ref': ref,
                     'synthesis_id': resolved['synthesis_id']} if resolved['body'] else None
            return {
                'review_item_id': item['id'], 'point_id': item['point_id'],
                'node_id': node_id, 'title': item['title'], 'priority': item['priority'],
                'weak_candidate': bool(item['weak_candidate']),
                'status': item['status'], 'level': item['level'],
                'material': chunk, 'source_missing': not bool(chunk),
            }
    if item['source_id']:
        chunk = conn.execute(
            'SELECT anchor, text FROM chunks WHERE source_id=? AND anchor=?'
            ' ORDER BY id LIMIT 1',
            (item['source_id'], item['anchor'])).fetchone()
        if chunk is None:  # anchor drifted: fall back to point-id prefix
            chunk = conn.execute(
                "SELECT anchor, text FROM chunks WHERE source_id=?"
                " AND anchor LIKE ? ORDER BY id LIMIT 1",
                (item['source_id'], item['point_id'] + ' %')).fetchone()
    return {
        'review_item_id': item['id'], 'point_id': item['point_id'],
        'title': item['title'], 'priority': item['priority'],
        'weak_candidate': bool(item['weak_candidate']),
        'status': item['status'], 'level': item['level'],
        'material': dict(chunk) if chunk else None,
        'source_missing': item['source_id'] is None,
    }


def record(conn, item_id, result, hint_level=0, note='', when=None):
    """Record one review action and advance the schedule. 起算点 = this
    action; overdue days never factor in (口径 3). First record flips the
    item from unknown to active. Also writes an attempt event
    (record_kind='review') so weakness assessment has evidence."""
    if result not in RESULTS:
        raise ValidationError('Invalid review result: %r (one of %s)'
                              % (result, '/'.join(RESULTS)))
    item = _get(conn, item_id)
    day = when or date.today()
    # Only a clean correct advances; a heavily-hinted correct reads as partial.
    effective = 'partial' if (result == 'correct' and hint_level > 1) else result
    if effective == 'correct':
        level = item['level'] + 1 if item['status'] == 'active' else 0
    elif effective == 'partial':
        level = max(0, item['level'] - 1) if item['status'] == 'active' else 0
    else:  # wrong → 归零次日再来
        level = 0
    interval = INTERVALS[min(level, len(INTERVALS) - 1)]
    next_due = (day + timedelta(days=interval)).isoformat()
    with transaction(conn):
        conn.execute(
            "UPDATE review_items SET status='active', level=?,"
            ' last_reviewed=?, next_due=? WHERE id=?',
            (level, now_iso(), next_due, item_id))
        conn.execute(
            "INSERT INTO events(node_id,ts,type,payload) VALUES(NULL,?,"
            "'attempt',?)",
            (now_iso(), json.dumps({
                'record_kind': 'review', 'course_id': item['course_id'],
                'review_item_id': item_id, 'point_id': item['point_id'],
                'result': result, 'hint_level': hint_level, 'note': note,
                'level_after': level}, ensure_ascii=False)))
    return {'review_item_id': item_id, 'point_id': item['point_id'],
            'level': level, 'next_due': next_due, 'interval_days': interval}
