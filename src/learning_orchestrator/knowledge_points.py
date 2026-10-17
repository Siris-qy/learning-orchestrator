"""Derived heading index. Bodies remain in the append-only knowledge wiki."""
import hashlib
import re
import uuid

from .db import dicts, transaction
from .graph import ValidationError

ORGANIZATION = re.compile(r'^(?:自查|自测|练习|复习题|参考答案|参考资料|资料来源|来源|参考文献|相关阅读|相关知识|回看代码时问这几件事|Flashcards)(?:$|[：:\s])', re.I)


def organizational(title):
    # Old notes often prefix headings with numbering or decorative emoji.
    plain = re.sub(r'^[\W\d_]+', '', title, flags=re.UNICODE)
    return bool(ORGANIZATION.match(plain))


def setup(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS knowledge_point_index(
      id TEXT PRIMARY KEY, block_id TEXT NOT NULL,
      parent_id TEXT, title TEXT NOT NULL, level INTEGER NOT NULL,
      start_line INTEGER NOT NULL, end_line INTEGER NOT NULL,
      fingerprint TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
    CREATE INDEX IF NOT EXISTS idx_kpi_block ON knowledge_point_index(block_id,active);
    CREATE TABLE IF NOT EXISTS knowledge_point_versions(
      block_id TEXT PRIMARY KEY, body_hash TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS knowledge_point_links(
      from_id TEXT NOT NULL REFERENCES knowledge_point_index(id),
      to_id TEXT NOT NULL REFERENCES knowledge_point_index(id),
      relation TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
      PRIMARY KEY(from_id,to_id,relation));
    ''')


def headings(text):
    lines = text.splitlines()
    found, fence = [], None
    for i, line in enumerate(lines):
        f = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if f:
            if fence is None:
                fence = f[1]
            elif f[1][0] == fence[0] and len(f[1]) >= len(fence):
                fence = None
            continue
        if fence:
            continue
        m = re.match(r'^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$', line)
        if m:
            found.append({'title': m[2], 'level': len(m[1]), 'start_line': i})
    result, stack = [], []
    for pos, h in enumerate(found):
        end = next((x['start_line'] for x in found[pos+1:] if x['level'] <= h['level']), len(lines))
        while stack and stack[-1]['level'] >= h['level']:
            stack.pop()
        excluded = organizational(h['title']) or bool(stack and stack[-1]['excluded'])
        parent = next((x['index'] for x in reversed(stack) if x['index'] is not None), None)
        index = None
        if not excluded:
            index = len(result)
            # Only local prose: renaming a parent doesn't change its children.
            local_end = found[pos+1]['start_line'] if pos+1 < len(found) else len(lines)
            local = '\n'.join(lines[h['start_line']+1:local_end]).strip()
            result.append(dict(h, end_line=end, parent_index=parent,
                fingerprint=hashlib.sha256(local.encode()).hexdigest() if local else ''))
        stack.append(dict(h, excluded=excluded, index=index))
    return result


def body(conn, block_id):
    last = conn.execute('SELECT content FROM knowledge_syntheses WHERE block_id=? ORDER BY id DESC LIMIT 1', (block_id,)).fetchone()
    if last:
        return last[0]
    # Until consolidation, index entries in their visible insertion order.
    entries = conn.execute('SELECT content FROM knowledge_entries WHERE block_id=? ORDER BY rowid', (block_id,)).fetchall()
    return '\n\n'.join(e[0] for e in entries)


def sync(conn, block_id):
    text = body(conn, block_id)
    digest = hashlib.sha256(('heading-index-v1\n' + text).encode()).hexdigest()
    version = conn.execute('SELECT body_hash FROM knowledge_point_versions WHERE block_id=?', (block_id,)).fetchone()
    if version and version[0] == digest:
        return
    old = dicts(conn.execute('SELECT * FROM knowledge_point_index WHERE block_id=? ORDER BY active DESC,start_line', (block_id,)))
    used, current = set(), []
    for h in headings(text):
        parent = current[h['parent_index']]['id'] if h['parent_index'] is not None else None
        matches = [p for p in old if p['id'] not in used and p['title'] == h['title'] and p['parent_id'] == parent]
        if len(matches) != 1 and h['fingerprint']:
            matches = [p for p in old if p['id'] not in used and p['fingerprint'] == h['fingerprint']]
        previous = matches[0] if len(matches) == 1 else None
        pid = previous['id'] if previous else 'kp-' + uuid.uuid4().hex
        used.add(pid)
        current.append(dict(h, id=pid, parent_id=parent))
    with transaction(conn):
        conn.execute('UPDATE knowledge_point_index SET active=0 WHERE block_id=?', (block_id,))
        for p in current:
            conn.execute('INSERT INTO knowledge_point_index VALUES(?,?,?,?,?,?,?,?,1) '
                'ON CONFLICT(id) DO UPDATE SET parent_id=excluded.parent_id,title=excluded.title,'
                'level=excluded.level,start_line=excluded.start_line,end_line=excluded.end_line,'
                'fingerprint=excluded.fingerprint,active=1',
                (p['id'], block_id, p['parent_id'], p['title'], p['level'], p['start_line'], p['end_line'], p['fingerprint']))
        conn.execute('INSERT INTO knowledge_point_versions VALUES(?,?) ON CONFLICT(block_id) DO UPDATE SET body_hash=excluded.body_hash', (block_id, digest))


def listing(conn, block_id):
    return dicts(conn.execute('SELECT id,block_id,parent_id,title,level,start_line,end_line FROM knowledge_point_index '
                             'WHERE block_id=? AND active=1 ORDER BY start_line', (block_id,)))


def read(conn, point_id):
    p = conn.execute('SELECT * FROM knowledge_point_index WHERE id=?', (point_id,)).fetchone()
    if not p:
        raise ValidationError('Unknown knowledge point: ' + point_id)
    result = dict(p)
    result.pop('fingerprint')
    result['text'] = '\n'.join(body(conn, p['block_id']).splitlines()[p['start_line']:p['end_line']]) if p['active'] else None
    result['links'] = dicts(conn.execute('SELECT l.*,p.title AS target_title,p.block_id AS target_block_id,p.active AS target_active,'
        'p.id AS target_id FROM knowledge_point_links l JOIN knowledge_point_index p ON '
        'p.id=CASE WHEN l.from_id=? THEN l.to_id ELSE l.from_id END WHERE l.from_id=? OR l.to_id=?',
        (point_id,point_id,point_id)))
    return result


def search(conn, query, limit=20):
    q = query.strip()
    if not q:
        return []
    # Escape LIKE metacharacters; this searches titles, not an extra body copy.
    pattern = '%' + q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_') + '%'
    from . import knowledge
    replaced = knowledge.canonical_replacements(conn)
    curated = set()
    promoted = set()
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='review_graph_nodes'").fetchone():
        import json
        for row in conn.execute('SELECT payload FROM review_graph_nodes'):
            n = json.loads(row[0])
            if n.get('provenance', {}).get('curated_index'):
                curated.add(n.get('content_ref', {}).get('id'))
        promoted = {r[0] for r in conn.execute("SELECT ref_id FROM review_graph_bindings WHERE ref_type='node' AND course_id=''")}
    rows = dicts(conn.execute("SELECT p.id,p.block_id,p.title,p.parent_id,p.level,b.title AS block_title "
        "FROM knowledge_point_index p JOIN knowledge_blocks b ON b.id=p.block_id "
        "WHERE p.active=1 AND p.title LIKE ? ESCAPE '\\' ORDER BY b.title,p.start_line", (pattern,)))
    return [r for r in rows if r['block_id'] not in replaced
            and (r['block_id'] not in curated or r['id'] in promoted)][:max(1,min(int(limit),100))]


def relate(conn, from_id, to_id, relation='related', note=''):
    for pid in (from_id,to_id):
        if not conn.execute('SELECT 1 FROM knowledge_point_index WHERE id=?', (pid,)).fetchone():
            raise ValidationError('Unknown knowledge point: ' + pid)
    if from_id == to_id or relation not in ('related','prerequisite','used_in','contrasts_with'):
        raise ValidationError('Invalid knowledge point relation')
    with transaction(conn):
        conn.execute('INSERT INTO knowledge_point_links VALUES(?,?,?,?) ON CONFLICT(from_id,to_id,relation) DO UPDATE SET note=excluded.note',
                     (from_id,to_id,relation,note))
    return {'success': True}
