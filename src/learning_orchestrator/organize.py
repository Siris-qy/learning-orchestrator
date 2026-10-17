"""Overlay organization for legacy topic records + cross-view links.

Two lightweight, append-only, reversible layers (TODO 2026-09-23 可视化收敛):

- topic_org: assigns the flat per-section topic records (which live in the
  immutable teaching_updates stream) to later-authored theme groups. The
  original payloads are never rewritten; deleting an org row restores the
  flat/unassigned view, and `origin` marks these as 后补主题归类 so they stay
  distinguishable from real question parentage (teaching_items).
- links: many-to-many associations between code modules, learning nodes,
  knowledge anchors and themes. Maintained once; the reverse direction is a
  query, not a second copy. `basis` keeps 源码确认 / 配置示例 / 推断 / 人工整理
  apart, and rows without a natural counterpart are simply absent — never
  fabricated.
"""

import json

from .db import dicts
from .graph import now_iso

KINDS = ('code_module', 'node', 'knowledge', 'theme')
BASES = ('source-confirmed', 'config-example', 'inferred', 'manual')


def setup(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS topic_org(
      id INTEGER PRIMARY KEY,
      course_id TEXT NOT NULL,
      section_id TEXT NOT NULL,
      topic_title TEXT NOT NULL,
      group_key TEXT NOT NULL,
      group_title TEXT NOT NULL,
      kind TEXT NOT NULL DEFAULT 'theme' CHECK(kind IN ('theme','archive')),
      note TEXT NOT NULL DEFAULT '',
      origin TEXT NOT NULL,
      created_at TEXT NOT NULL,
      UNIQUE(course_id, section_id, topic_title));
    CREATE TABLE IF NOT EXISTS links(
      id INTEGER PRIMARY KEY,
      course_id TEXT NOT NULL,
      from_kind TEXT NOT NULL CHECK(from_kind IN ('code_module','node','knowledge','theme')),
      from_id TEXT NOT NULL,
      to_kind TEXT NOT NULL CHECK(to_kind IN ('code_module','node','knowledge','theme')),
      to_id TEXT NOT NULL,
      basis TEXT NOT NULL DEFAULT 'manual'
        CHECK(basis IN ('source-confirmed','config-example','inferred','manual')),
      note TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL,
      UNIQUE(from_kind, from_id, to_kind, to_id));
    CREATE TABLE IF NOT EXISTS code_maps(
      course_id TEXT PRIMARY KEY,
      title TEXT NOT NULL DEFAULT '',
      data TEXT NOT NULL,
      origin TEXT NOT NULL,
      updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS course_outline(
      course_id TEXT NOT NULL,
      stage_key TEXT NOT NULL,
      seq INTEGER NOT NULL DEFAULT 0,
      title TEXT NOT NULL,
      goal TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending','current','done')),
      note TEXT NOT NULL DEFAULT '',
      origin TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(course_id, stage_key));
    """)
    # 2026-09-24: topic_org gains item_id — 过程记录挂到教学小项（递归树）下，
    # 仍然只是组织覆盖层：清空该列即恢复主题级平铺，不触碰原始记录。
    cols = [r[1] for r in conn.execute('PRAGMA table_info(topic_org)')]
    if 'item_id' not in cols:
        conn.execute('ALTER TABLE topic_org ADD COLUMN item_id INTEGER')
    if 'node_ids' not in [r[1] for r in conn.execute('PRAGMA table_info(course_outline)')]:
        conn.execute('ALTER TABLE course_outline ADD COLUMN node_ids TEXT')


def add_topic_org(conn, course_id, section_id, group_key, group_title,
                  topic_titles, kind='theme', note='', origin='manual'):
    """Idempotent classification of existing topic titles into a group."""
    with conn:
        for t in topic_titles:
            conn.execute(
                'INSERT OR IGNORE INTO topic_org(course_id,section_id,'
                'topic_title,group_key,group_title,kind,note,origin,created_at)'
                ' VALUES(?,?,?,?,?,?,?,?,?)',
                (course_id, section_id, t, group_key, group_title, kind,
                 note, origin, now_iso()))


def organized_topics(conn, course_id, section_id):
    """The section's topics as theme groups + archive + unassigned.

    Statuses and first-seen timestamps come from the raw teaching_updates
    stream (latest status wins, like teaching.read); only the grouping comes
    from topic_org. A topic with no org row stays honestly unassigned."""
    rows = dicts(conn.execute(
        'SELECT payload, ts FROM teaching_updates'
        ' WHERE course_id=? AND section_id=? ORDER BY id',
        (course_id, section_id)))
    status, first_ts = {}, {}
    for r in rows:
        for t in json.loads(r['payload']).get('topics', []):
            status[t['title']] = t['status']
            first_ts.setdefault(t['title'], r['ts'])
    org = {r['topic_title']: r for r in dicts(conn.execute(
        'SELECT * FROM topic_org WHERE course_id=? AND section_id=?',
        (course_id, section_id)))}
    groups, unassigned = {}, []
    for title, st in status.items():
        item = {'title': title, 'status': st, 'first_ts': first_ts[title]}
        o = org.get(title)
        if o is None:
            unassigned.append(item)
            continue
        item['item_id'] = o['item_id']  # 记录级教学小项归属（空=未归位到小项）
        g = groups.setdefault(o['group_key'], {
            'key': o['group_key'], 'title': o['group_title'],
            'kind': o['kind'], 'note': o['note'], 'origin': o['origin'],
            'item_id': None, '_item_ids': set(), 'items': []})
        g['_item_ids'].add(o['item_id'])
        g['items'].append(item)
    for g in groups.values():
        ids = g.pop('_item_ids')
        # 组级归属只在全组每条记录都挂到同一小项时给出；部分未归属或跨小项
        # 时不假装单一归属，前端用记录级 item_id 折叠
        g['item_id'] = ids.pop() if len(ids) == 1 else None
        g['items'].sort(key=lambda i: (i['first_ts'], i['title']))
    ordered = sorted(groups.values(),
                     key=lambda g: (g['kind'] == 'archive',
                                    min(i['first_ts'] for i in g['items'])))
    return {'groups': ordered, 'unassigned': unassigned,
            # organized 只统计"记录流里确实存在、且有归类行"的标题；
            # org 表里多余的行（标题不在记录流中）不算归类完成
            'organized': sum(1 for t in status if t in org),
            'total': len(status)}


def add_links(conn, course_id, entries, origin_note=''):
    """entries: (from_kind, from_id, to_kind, to_id, basis, note). Idempotent."""
    for fk, fid, tk, tid, basis, note in entries:
        if fk not in KINDS or tk not in KINDS:
            raise ValueError('unknown link kind')
        if basis not in BASES:
            raise ValueError('unknown link basis: %r' % basis)
    with conn:
        for fk, fid, tk, tid, basis, note in entries:
            conn.execute(
                'INSERT OR IGNORE INTO links(course_id,from_kind,from_id,'
                'to_kind,to_id,basis,note,created_at) VALUES(?,?,?,?,?,?,?,?)',
                (course_id, fk, fid, tk, tid, basis,
                 (origin_note + ' ' + note).strip(), now_iso()))


def links_for(conn, course_id, kind, rid):
    """Both directions in one query — the reverse side is never stored twice."""
    out = []
    for r in dicts(conn.execute(
            'SELECT * FROM links WHERE course_id=? AND (from_kind=? AND from_id=?'
            ' OR to_kind=? AND to_id=?) ORDER BY id',
            (course_id, kind, rid, kind, rid))):
        if r['from_kind'] == kind and r['from_id'] == rid:
            out.append({'kind': r['to_kind'], 'id': r['to_id'],
                        'basis': r['basis'], 'note': r['note'], 'dir': 'out'})
        else:
            out.append({'kind': r['from_kind'], 'id': r['from_id'],
                        'basis': r['basis'], 'note': r['note'], 'dir': 'in'})
    return out


def save_code_map(conn, course_id, title, data, origin):
    with conn:
        conn.execute(
            'INSERT INTO code_maps(course_id,title,data,origin,updated_at)'
            ' VALUES(?,?,?,?,?)'
            ' ON CONFLICT(course_id) DO UPDATE SET'
            ' title=excluded.title, data=excluded.data,'
            ' origin=excluded.origin, updated_at=excluded.updated_at',
            (course_id, title, json.dumps(data, ensure_ascii=False), origin,
             now_iso()))


def get_code_map(conn, course_id):
    row = conn.execute('SELECT * FROM code_maps WHERE course_id=?',
                       (course_id,)).fetchone()
    if row is None:
        return None
    data = json.loads(row['data'])
    data['origin'] = row['origin']
    # Attach cross-view links per component (single-source, queried both ways)
    for comp in data.get('components', []):
        comp['links'] = links_for(conn, course_id, 'code_module', comp['id'])
    return data


def map_topics_to_item(conn, course_id, section_id, item_id, titles,
                       origin='manual'):
    """Attach already-classified topic records to a teaching item (2026-09-24).

    Organization only: the teaching_updates stream is never rewritten, and a
    title without an existing topic_org row is reported, not silently created
    (classification and item attachment stay separate, auditable steps)."""
    missing = []
    with conn:
        for t in titles:
            cur = conn.execute(
                'UPDATE topic_org SET item_id=?'
                ' WHERE course_id=? AND section_id=? AND topic_title=?',
                (item_id, course_id, section_id, t))
            if cur.rowcount == 0:
                missing.append(t)
    return {'mapped': len(titles) - len(missing), 'missing': missing,
            'origin': origin}


def save_outline(conn, course_id, stages, origin='manual'):
    """Course-level teaching outline: stage goals only, expandable later.

    stages: [{stage_key, seq, title, goal, status, note?}]. Organization layer
    per 2026-09-24 followup — far stages stay 'pending' with goals; no
    pre-generated items, no mastery claims. Upsert by (course_id, stage_key)."""
    with conn:
        for s in stages:
            if s.get('status', 'pending') not in ('pending', 'current', 'done'):
                raise ValueError('unknown outline status: %r' % s.get('status'))
            conn.execute(
                'INSERT INTO course_outline(course_id,stage_key,seq,title,goal,'
                'status,note,origin,updated_at,node_ids) VALUES(?,?,?,?,?,?,?,?,?,?)'
                ' ON CONFLICT(course_id,stage_key) DO UPDATE SET'
                ' seq=excluded.seq, title=excluded.title, goal=excluded.goal,'
                ' status=excluded.status, note=excluded.note,'
                ' origin=excluded.origin, updated_at=excluded.updated_at,'
                ' node_ids=COALESCE(excluded.node_ids,course_outline.node_ids)',
                (course_id, s['stage_key'], s.get('seq', 0), s['title'],
                 s.get('goal', ''), s.get('status', 'pending'),
                 s.get('note', ''), origin, now_iso(),
                 json.dumps(s['node_ids']) if 'node_ids' in s else None))
    return len(stages)


def get_outline(conn, course_id):
    stages = dicts(conn.execute(
        'SELECT stage_key,seq,title,goal,status,note,origin,node_ids FROM course_outline'
        ' WHERE course_id=? ORDER BY seq, stage_key', (course_id,)))
    from . import teaching
    plan = teaching.current_plan(conn, course_id)
    workspace = conn.execute('SELECT section_id FROM teaching_workspace WHERE course_id=?',
                             (course_id,)).fetchone()
    section = plan['section_id'] if plan else workspace['section_id'] if workspace else None
    distances, frontier = {}, [section] if section else []
    depth = 0
    while frontier:
        following = []
        for node in frontier:
            if node in distances:
                continue
            distances[node] = depth
            following.extend(r[0] for r in conn.execute(
                "SELECT e.dst FROM edges e JOIN nodes n ON n.id=e.dst"
                " WHERE e.src=? AND e.type='part_of' AND n.course_id=?", (node, course_id)))
        frontier, depth = following, depth + 1
    candidates = []
    for stage in stages:
        stage['node_ids'] = json.loads(stage['node_ids'] or '[]')
        match = [distances[n] for n in stage['node_ids'] if n in distances]
        if match:
            candidates.append((min(match), stage['seq'], stage['stage_key']))
    selected = min(candidates)[2] if candidates else None
    for stage in stages:
        stage['stored_status'] = stage['status']
        if section:
            # A navigation badge is not a mastery/completion decision.
            stage['status'] = 'current' if stage['stage_key'] == selected else (
                'pending' if stage['status'] == 'current' else stage['status'])
    return stages
