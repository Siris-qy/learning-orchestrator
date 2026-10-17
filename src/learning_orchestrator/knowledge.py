"""Incremental knowledge wiki. Entries and syntheses are append-only;
placements and links organize the same block from different perspectives.
No learning cursor, mastery judgment or review schedule is updated here.
"""
import json
import uuid

from .db import dicts, transaction
from .graph import ValidationError, now_iso

AREAS = {'backend': '网络与后端基础', 'cpp': 'C++',
         'algorithms': '数据结构与算法', 'database': '数据库', 'other': '其他基础'}


def setup(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS knowledge_blocks(
      id TEXT PRIMARY KEY, title TEXT NOT NULL, area TEXT NOT NULL,
      created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS knowledge_entries(
      id TEXT PRIMARY KEY, block_id TEXT NOT NULL REFERENCES knowledge_blocks(id),
      heading TEXT NOT NULL, content TEXT NOT NULL, kind TEXT NOT NULL,
      source_refs TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_ke_block ON knowledge_entries(block_id);
    CREATE TABLE IF NOT EXISTS knowledge_syntheses(
      id INTEGER PRIMARY KEY, block_id TEXT NOT NULL REFERENCES knowledge_blocks(id),
      content TEXT NOT NULL, covered_entries TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS knowledge_placements(
      block_id TEXT NOT NULL REFERENCES knowledge_blocks(id),
      view_key TEXT NOT NULL, path TEXT NOT NULL, seq INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(block_id,view_key,path));
    CREATE TABLE IF NOT EXISTS knowledge_relations(
      from_id TEXT NOT NULL REFERENCES knowledge_blocks(id),
      to_id TEXT NOT NULL REFERENCES knowledge_blocks(id),
      relation TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
      PRIMARY KEY(from_id,to_id,relation));
    ''')
    from . import knowledge_points
    knowledge_points.setup(conn)
    for r in conn.execute('SELECT id FROM knowledge_blocks').fetchall():
        knowledge_points.sync(conn, r[0])


def _block(conn, block_id):
    r = conn.execute('SELECT * FROM knowledge_blocks WHERE id=?', (block_id,)).fetchone()
    if r is None:
        if block_id.startswith('source:'):
            source = conn.execute('SELECT title FROM sources WHERE id=?', (block_id[7:],)).fetchone()
            if source:
                return {'id': block_id, 'title': source['title'], 'area': 'backend', 'created_at': ''}
        raise ValidationError('Unknown knowledge block: ' + block_id)
    return dict(r)


def _placement(conn, block_id, view_key, path, seq=0):
    if not isinstance(path, list) or not path or any(not isinstance(p, str) or not p.strip() for p in path):
        raise ValidationError('path must be a nonempty list of titles')
    if view_key != 'foundations':
        prefix, _, course = view_key.partition(':')
        course_exists = conn.execute("SELECT 1 FROM nodes WHERE id=? AND type='course'", (course,)).fetchone()
        graph_root = None
        if prefix == 'project' and not course_exists and conn.execute("SELECT 1 FROM sqlite_master WHERE name='review_graph_nodes'").fetchone():
            graph_root = conn.execute('SELECT payload FROM review_graph_nodes WHERE id=?', (course,)).fetchone()
        project_exists = graph_root and json.loads(graph_root[0]).get('kind') == 'project'
        if prefix not in ('project', 'course') or not (course_exists or project_exists):
            raise ValidationError('view_key must be foundations, project:<course_id> or course:<course_id>')
    conn.execute('INSERT INTO knowledge_placements VALUES(?,?,?,?) '
                 'ON CONFLICT(block_id,view_key,path) DO UPDATE SET seq=excluded.seq',
                 (block_id, view_key, json.dumps(path, ensure_ascii=False), seq))


def _materialize(conn, block_id):
    b = _block(conn, block_id)
    conn.execute('INSERT OR IGNORE INTO knowledge_blocks VALUES(?,?,?,?)',
                 (block_id, b['title'], b['area'], now_iso()))


def append(conn, block_id, title, heading, content, area='backend', kind='explanation',
           source_refs=None, placements=None, entry_id=None):
    """One call stores an increment and its placement. Use a stable entry_id
    when retrying: replay is a no-op, conflicting replay is reported explicitly.
    Each source ref can identify a file/slide, source_id+anchor or teaching item.
    """
    if not block_id.strip() or not title.strip() or not heading.strip() or (not content.strip() and kind != 'reference'):
        raise ValidationError('block_id, title, heading and content are required')
    if area not in AREAS or kind not in ('explanation', 'example', 'question', 'correction', 'reference'):
        raise ValidationError('Invalid area or entry kind')
    if block_id.startswith('source:'):
        _block(conn, block_id)
    refs = source_refs or []
    if not isinstance(refs, list) or any(not isinstance(r, dict) for r in refs):
        raise ValidationError('source_refs must be a list of source descriptions')
    if kind == 'reference' and not any(r.get('source_id') and r.get('anchor') for r in refs):
        raise ValidationError('reference requires a registered source_id and exact anchor')
    for r in refs:
        if r.get('teaching_item_id') is not None and not conn.execute(
                'SELECT 1 FROM teaching_items WHERE id=?', (r['teaching_item_id'],)).fetchone():
            raise ValidationError('Unknown teaching_item_id')
        if r.get('source_id') and not conn.execute('SELECT 1 FROM sources WHERE id=?', (r['source_id'],)).fetchone():
            raise ValidationError('Unknown source_id')
        if kind == 'reference' and r.get('source_id') and not conn.execute(
                'SELECT 1 FROM chunks WHERE source_id=? AND anchor=?', (r['source_id'], r.get('anchor'))).fetchone():
            raise ValidationError('Unknown source anchor; inspect search_sources before linking')
    eid = entry_id or 'ke-' + uuid.uuid4().hex
    refs_json = json.dumps(refs, ensure_ascii=False, sort_keys=True)
    old = conn.execute('SELECT * FROM knowledge_entries WHERE id=?', (eid,)).fetchone()
    if old:
        if (old['block_id'], old['heading'], old['content'], old['kind'], old['source_refs']) != (
                block_id, heading, content, kind, refs_json):
            raise ValidationError('entry_id already stores different content; append a correction with a new id')
        return {'success': True, 'block_id': block_id, 'entry_id': eid, 'reused': True}
    with transaction(conn):
        conn.execute('INSERT OR IGNORE INTO knowledge_blocks VALUES(?,?,?,?)',
                     (block_id, title, area, now_iso()))
        conn.execute('INSERT INTO knowledge_entries VALUES(?,?,?,?,?,?,?)',
                     (eid, block_id, heading, content, kind, refs_json, now_iso()))
        if not placements and not conn.execute('SELECT 1 FROM knowledge_placements WHERE block_id=?', (block_id,)).fetchone():
            _placement(conn, block_id, 'foundations', [AREAS[area]])
        for p in placements or []:
            _placement(conn, block_id, p['view_key'], p['path'], p.get('seq', 0))
    from . import knowledge_points
    knowledge_points.sync(conn, block_id)
    return {'success': True, 'block_id': block_id, 'entry_id': eid, 'reused': False}


def place(conn, block_id, view_key, path, seq=0):
    _block(conn, block_id)
    with transaction(conn):
        _materialize(conn, block_id)
        _placement(conn, block_id, view_key, path, seq)
    return {'success': True, 'block_id': block_id}


def consolidate(conn, block_id, content, covered_entry_ids):
    """Save a synthesized body without deleting input entries. A later
    synthesis includes the previously covered ids, so unmerged content stays visible.
    """
    _block(conn, block_id)
    if not content.strip() or not isinstance(covered_entry_ids, list) or not covered_entry_ids:
        raise ValidationError('content and covered_entry_ids are required')
    known = {r[0] for r in conn.execute('SELECT id FROM knowledge_entries WHERE block_id=?', (block_id,))}
    if not set(covered_entry_ids) <= known:
        raise ValidationError('covered entries must belong to this block')
    last = conn.execute('SELECT id,content,covered_entries FROM knowledge_syntheses WHERE block_id=? ORDER BY id DESC LIMIT 1', (block_id,)).fetchone()
    if last and not set(json.loads(last['covered_entries'])) <= set(covered_entry_ids):
        raise ValidationError('Include previously covered entries when revising the synthesized body')
    ids = json.dumps(sorted(set(covered_entry_ids)))
    if last and last['content'] == content and last['covered_entries'] == ids:
        return {'success': True, 'block_id': block_id, 'synthesis_id': last['id'], 'reused': True}
    with transaction(conn):
        cur = conn.execute('INSERT INTO knowledge_syntheses(block_id,content,covered_entries,created_at) VALUES(?,?,?,?)',
                           (block_id, content, ids, now_iso()))
    from . import knowledge_points
    knowledge_points.sync(conn, block_id)
    return {'success': True, 'block_id': block_id, 'synthesis_id': cur.lastrowid}


def relate(conn, from_id, to_id, relation='related', note=''):
    _block(conn, from_id); _block(conn, to_id)
    if from_id == to_id or relation not in ('related', 'prerequisite', 'used_in', 'contrasts_with'):
        raise ValidationError('Invalid relation')
    with transaction(conn):
        _materialize(conn, from_id); _materialize(conn, to_id)
        conn.execute('INSERT INTO knowledge_relations VALUES(?,?,?,?) '
                     'ON CONFLICT(from_id,to_id,relation) DO UPDATE SET note=excluded.note',
                     (from_id, to_id, relation, note))
    return {'success': True}


def read(conn, block_id, include_history=False):
    b = _block(conn, block_id)
    from . import knowledge_points
    b['points'] = knowledge_points.listing(conn, block_id)
    if block_id.startswith('source:'):
        from . import presentation
        b.update(presentation.source_name(block_id[7:], b['title']))
    entries = dicts(conn.execute('SELECT * FROM knowledge_entries WHERE block_id=? ORDER BY rowid', (block_id,)))
    for e in entries:
        e['source_refs'] = json.loads(e['source_refs'])
        if e['kind'] == 'reference':
            e['reference_body'] = [{'anchor': r['anchor'], 'text': c['text']}
                for r in e['source_refs'] if r.get('source_id') and r.get('anchor')
                for c in conn.execute('SELECT text FROM chunks WHERE source_id=? AND anchor=?', (r['source_id'], r['anchor']))]
    last = conn.execute('SELECT * FROM knowledge_syntheses WHERE block_id=? ORDER BY id DESC LIMIT 1', (block_id,)).fetchone()
    synthesis = dict(last) if last else None
    covered = set(json.loads(last['covered_entries'])) if last else set()
    if synthesis:
        synthesis['covered_entries'] = sorted(covered)
    b.update(synthesis=synthesis, additions=[e for e in entries if e['id'] not in covered],
             entry_count=len(entries), source_refs=[r for e in entries for r in e['source_refs']])
    b['placements'] = dicts(conn.execute('SELECT view_key,path,seq FROM knowledge_placements WHERE block_id=? ORDER BY seq,path', (block_id,)))
    for p in b['placements']:
        p['path'] = json.loads(p['path'])
    b['links'] = dicts(conn.execute(
        'SELECT r.*, b.title AS target_title, b.id AS target_id FROM knowledge_relations r '
        'JOIN knowledge_blocks b ON b.id=CASE WHEN r.from_id=? THEN r.to_id ELSE r.from_id END '
        'WHERE r.from_id=? OR r.to_id=?', (block_id, block_id, block_id)))
    if block_id.startswith('source:'):
        b['legacy_sections'] = dicts(conn.execute('SELECT anchor,text FROM chunks WHERE source_id=? ORDER BY id', (block_id[7:],)))
        source = conn.execute('SELECT uri,title FROM sources WHERE id=?', (block_id[7:],)).fetchone()
        if source:
            b['source_refs'].insert(0, {'source_id': block_id[7:], 'path': source['uri'], 'label': source['title']})
        b['practice_links'] = dicts(conn.execute(
            'SELECT id,title,course_id FROM review_items WHERE source_id=? ORDER BY point_id', (block_id[7:],)))
    if include_history:
        b['entries'] = entries
        b['synthesis_history'] = dicts(conn.execute('SELECT * FROM knowledge_syntheses WHERE block_id=? ORDER BY id', (block_id,)))
    return b


def catalog(conn, view_key=None):
    sql = ('SELECT b.*,p.view_key,p.path,p.seq, '
           'EXISTS(SELECT 1 FROM knowledge_syntheses s WHERE s.block_id=b.id) AS has_synthesis, '
           '(SELECT COUNT(*) FROM knowledge_entries e WHERE e.block_id=b.id) AS entry_count '
           'FROM knowledge_blocks b JOIN knowledge_placements p ON p.block_id=b.id')
    rows = dicts(conn.execute(sql + (' WHERE p.view_key=?' if view_key else '') + ' ORDER BY p.seq,p.path,b.title',
                             (view_key,) if view_key else ()))
    for r in rows:
        r['path'] = json.loads(r['path'])
        r['id'] = 'wiki:' + r['id']
        if r['id'].startswith('wiki:source:'):
            from . import presentation
            r.update(presentation.source_name(r['id'][12:], r['title']))
    return rows


def canonical_replacements(conn):
    """Display replacement only; old bodies/IDs and learning records survive.

    A source may be split across several formal blocks. Do not guess one new
    identity for the whole old block or copy its assessment to every child.
    """
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='review_graph_nodes'").fetchone():
        return {}
    result = {}
    for row in conn.execute('SELECT id,payload FROM review_graph_nodes'):
        node = json.loads(row['payload'])
        provenance = node.get('provenance') or {}
        if not provenance.get('canonical'):
            continue
        for block_id in provenance.get('supersedes_blocks', []):
            result.setdefault(block_id, []).append(row['id'])
    return result


def library(conn):
    """Organize existing notes by reference. No migration/copying of their bodies."""
    from . import review, seed_bagu, bagu_catalog, presentation
    replacements = canonical_replacements(conn)
    rows = [r for r in catalog(conn) if r['id'].removeprefix('wiki:') not in replacements]
    courses = dicts(conn.execute("SELECT id,title FROM nodes WHERE type='course' ORDER BY sort_order,title"))
    titles = {c['id']: c['title'] for c in courses}
    from . import curricula
    course_types = {c['id']: curricula.kind(conn, c['id']) for c in courses}
    for c in courses:
        grouped = {}
        for r in review.iter_items(conn, c['id']):
            grouped.setdefault(r['source_id'] or r['source_title'], []).append(r)
        for sid, points in grouped.items():
            title = points[0]['source_title'] or '未分类笔记'
            area = 'backend' if c['id'] == seed_bagu.COURSE_ID else 'database' if c['id'] == 'cmu-15-445-f2025' else 'other'
            if 'source:' + str(sid) in replacements:
                continue
            rows.append({'id': 'wiki:source:' + str(sid), 'title': title, 'view_key': 'foundations',
                         'path': [AREAS[area]], 'seq': 0, 'entry_count': len(points),
                         'legacy_points': [{'id': 'review:%s' % p['id'], 'title': p['title'], 'point_id': p['point_id']} for p in points],
                         'course_id': c['id'], 'reference_only': True})
            rows[-1].update(presentation.source_name(sid, title))
            rows.append(dict(rows[-1], view_key=course_types[c['id']] + ':' + c['id'], path=['关联的基础知识']))
    for b in bagu_catalog.blocks(conn):
        if b['kind'] == 'project-anchor':
            rows.append({'id': b['id'], 'title': b['title'], 'view_key': 'project:' + seed_bagu.COURSE_ID,
                         'path': ['HttpServer 核心模块'], 'seq': 0, 'entry_count': 0,
                         'course_id': seed_bagu.COURSE_ID, 'reference_only': True})
            rows[-1].update(presentation.module_name(b['id'], b['title']))
    views = [{'key': 'foundations', 'title': '基础能力', 'kind': 'foundations'}]
    # Shared knowledge systems use the same entry/rendering mechanism as projects.
    # Do not invent course progress or import old notes when registering an entry.
    knowledge_roots = {}
    for row in conn.execute('SELECT id,payload FROM review_graph_nodes'):
        node = json.loads(row['payload'])
        if node.get('kind') == 'project' and node.get('owner_ref', {}).get('type') == 'knowledge_system':
            knowledge_roots['project:' + row['id']] = node
    keys = {r['view_key'] for r in rows} | {course_types[c['id']] + ':' + c['id'] for c in courses}
    keys.update(knowledge_roots)
    for key in sorted(keys - {'foundations'}):
        kind, _, cid = key.partition(':')
        if key in knowledge_roots:
            node = knowledge_roots[key]
            views.append({'key': key, 'title': node['title'], 'kind': kind,
                          'root_node_id': node['id'], 'knowledge_system': True})
        else:
            views.append({'key': key, 'title': presentation.course_title(cid, titles.get(cid, cid)), 'kind': kind, 'course_id': cid})
    # An authored increment on an existing source-backed block extends that
    # same identity. Prefer explicit placements over its legacy fallback index.
    deduped = []
    seen = set()
    for r in rows:
        key = (r['id'], r['view_key'])
        if r.get('reference_only') and key in seen:
            continue
        seen.add(key); deduped.append(r)
    return {'views': views, 'items': deduped, 'areas': AREAS}
