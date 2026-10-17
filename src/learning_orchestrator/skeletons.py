"""Skeleton registration and learning-state markers (M2, TODO §8.1).

Spec (2026-09-22): one content = ONE complete self-contained skeleton file
covering all functionality — no V0..Vn incremental versions, no preparing the
next version while learning the current one. Learning flow:
看骨架 → 看源代码 → 核对简历细节 / 回答题目.

- Lifecycle states (prepared/runnable/copied/understood/verified) are
  lightweight markers, not gates — same philosophy as the teaching tree.
  State changes are recorded as note events (record_kind='skeleton_state')
  on the owning node so review can see where time went.
- The skeleton→real-source index (skeleton_map) keeps skeleton anchors,
  resume claims and real file:line references queryable, so review can walk
  skeleton → source → claim chains (TODO §8.4).
"""
import hashlib
import json
import re
from pathlib import Path

from . import sources as sources_mod
from .db import dicts, transaction
from .graph import ValidationError, get_node, now_iso

STATES = ('prepared', 'runnable', 'copied', 'understood', 'verified')

# §8.1: 备课已生成 / 代码可运行 / 用户已抄写 / 用户理解 / 通过验证
STATE_LABELS = {'prepared': '备课已生成', 'runnable': '代码可运行',
                'copied': '用户已抄写', 'understood': '用户理解',
                'verified': '通过验证'}


def setup(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS skeletons(
      id INTEGER PRIMARY KEY, course_id TEXT NOT NULL, node_id TEXT NOT NULL,
      source_id TEXT NOT NULL REFERENCES sources(id),
      title TEXT NOT NULL,
      state TEXT NOT NULL DEFAULT 'prepared' CHECK (state IN
        ('prepared','runnable','copied','understood','verified')),
      created_by TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_skeletons_course ON skeletons(course_id, node_id);
    CREATE TABLE IF NOT EXISTS skeleton_map(
      id INTEGER PRIMARY KEY,
      skeleton_id INTEGER NOT NULL REFERENCES skeletons(id),
      skeleton_anchor TEXT NOT NULL,
      claim_id INTEGER REFERENCES claims(id),
      real_ref TEXT NOT NULL DEFAULT '',
      note TEXT NOT NULL DEFAULT '');
    CREATE INDEX IF NOT EXISTS idx_skeleton_map ON skeleton_map(skeleton_id);
    ''')


def _get(conn, skeleton_id):
    row = conn.execute('SELECT * FROM skeletons WHERE id=?',
                       (skeleton_id,)).fetchone()
    if row is None:
        raise ValidationError('Unknown skeleton: %r' % skeleton_id)
    return dict(row)


def _canonical_path_key(path):
    """Identity key for a skeleton file. The same DB is written from WSL
    (/mnt/e/...) and Windows (E:\\...) processes (TODO §0.1 mixed paths); both
    spellings must hash to one skeleton, or a cross-OS re-register would
    duplicate it. String-level only — never resolved against the local FS."""
    s = str(path).replace('\\', '/').rstrip('/')
    m = re.match(r'^/mnt/([a-zA-Z])/(.*)$', s)
    if m:
        s = '%s:/%s' % (m.group(1).lower(), m.group(2))
    return s.lower()


def register(conn, course_id, node_id, path, source_roots, title=None,
             created_by='main'):
    """Register one complete skeleton file for a unit: import it as a source
    (code-chunked, so sections stay searchable), attach it to the node, and
    open a skeletons row in state 'prepared'. Re-registering the same file
    returns the existing row instead of duplicating."""
    node = get_node(conn, node_id)
    if node['course_id'] != course_id:
        raise ValidationError('Node does not belong to this course')
    # Deterministic source id from the canonical path key; check BEFORE the
    # import so a re-register from the other OS path spelling short-circuits
    # without touching the filesystem (which would fail the roots check).
    source_id = 'skel-' + hashlib.sha1(
        _canonical_path_key(path).encode('utf-8')).hexdigest()[:10]
    existing = conn.execute('SELECT * FROM skeletons WHERE source_id=?',
                            (source_id,)).fetchone()
    if existing:
        return {'skeleton_id': existing['id'], 'source_id': source_id,
                'state': existing['state'], 'reused': True}
    sources_mod.register_file(conn, course_id, path, source_roots,
                              title=title, source_id=source_id)
    sources_mod.attach_source(conn, node_id, source_id, anchor='skeleton')
    if not title:
        title = conn.execute('SELECT title FROM sources WHERE id=?',
                             (source_id,)).fetchone()['title']
    with transaction(conn):
        cur = conn.execute(
            'INSERT INTO skeletons(course_id,node_id,source_id,title,state,'
            'created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
            (course_id, node_id, source_id, title, 'prepared', created_by,
             now_iso(), now_iso()))
    return {'skeleton_id': cur.lastrowid, 'source_id': source_id,
            'state': 'prepared', 'reused': False}


def set_state(conn, skeleton_id, state, note='', updated_by='main'):
    """Advance a lifecycle marker. Not a gate: any order is allowed, but the
    value must be one of STATES. Every change is recorded as a note event on
    the owning node (record_kind='skeleton_state') for later review."""
    if state not in STATES:
        raise ValidationError('Invalid skeleton state: %r (one of %s)'
                              % (state, '/'.join(STATES)))
    sk = _get(conn, skeleton_id)
    with transaction(conn):
        conn.execute('UPDATE skeletons SET state=?, updated_at=? WHERE id=?',
                     (state, now_iso(), skeleton_id))
        conn.execute(
            "INSERT INTO events(node_id,ts,type,payload) VALUES(?,?,'note',?)",
            (sk['node_id'], now_iso(), json.dumps({
                'text': note or STATE_LABELS[state],
                'record_kind': 'skeleton_state', 'skeleton_id': skeleton_id,
                'state': state}, ensure_ascii=False)))
    return {'skeleton_id': skeleton_id, 'state': state}


def add_map(conn, skeleton_id, entries):
    """Bulk-add skeleton→real-source index rows. Each entry:
    {skeleton_anchor, claim_id?, real_ref?, note?}. skeleton_anchor names the
    skeleton class/section (e.g. 'PluginHost'); real_ref is the real-source
    evidence ('src/server/Server.cpp:L34-L58; src/main.cpp:L112-L119'); note
    carries the boundary declaration (§8.1: what the skeleton deliberately
    does NOT cover). claim_id must belong to the skeleton's course."""
    sk = _get(conn, skeleton_id)
    if not entries:
        raise ValidationError('add_map needs at least one entry')
    for e in entries:
        if not e.get('skeleton_anchor'):
            raise ValidationError('Each map entry needs a skeleton_anchor')
        if e.get('claim_id') is not None:
            claim = conn.execute('SELECT course_id FROM claims WHERE id=?',
                                 (e['claim_id'],)).fetchone()
            if claim is None or claim['course_id'] != sk['course_id']:
                raise ValidationError(
                    'Claim %r does not belong to this course' % e['claim_id'])
    ids = []
    with transaction(conn):
        for e in entries:
            ref = e.get('real_ref') or ''
            if isinstance(ref, (list, tuple)):
                ref = '; '.join(ref)
            cur = conn.execute(
                'INSERT INTO skeleton_map(skeleton_id,skeleton_anchor,'
                'claim_id,real_ref,note) VALUES(?,?,?,?,?)',
                (skeleton_id, e['skeleton_anchor'], e.get('claim_id'),
                 ref, e.get('note', '')))
            ids.append(cur.lastrowid)
    return {'skeleton_id': skeleton_id, 'added': ids}


def _with_map(conn, row):
    sk = dict(row)
    sk['state_label'] = STATE_LABELS[sk['state']]
    sk['map'] = dicts(conn.execute(
        'SELECT id, skeleton_anchor, claim_id, real_ref, note'
        ' FROM skeleton_map WHERE skeleton_id=? ORDER BY id', (sk['id'],)))
    return sk


def list_skeletons(conn, course_id=None, node_id=None):
    """Skeletons with their source index, optionally filtered. Review and the
    teaching windows read this; page display is deliberately deferred."""
    sql, params = 'SELECT * FROM skeletons', []
    if course_id:
        sql += ' WHERE course_id=?'
        params.append(course_id)
        if node_id:
            sql += ' AND node_id=?'
            params.append(node_id)
    elif node_id:
        sql += ' WHERE node_id=?'
        params.append(node_id)
    return [_with_map(conn, r)
            for r in conn.execute(sql + ' ORDER BY id', params)]


def brief_for_node(conn, node_id):
    """Compact skeleton pointer for prepare_teaching profiles (id/title/state
    only — the full index stays in list_skeletons to keep responses small)."""
    row = conn.execute(
        'SELECT id, title, state FROM skeletons WHERE node_id=? ORDER BY id',
        (node_id,)).fetchone()
    if row is None:
        return None
    return {'id': row['id'], 'title': row['title'], 'state': row['state'],
            'state_label': STATE_LABELS[row['state']]}
