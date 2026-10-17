"""Interview knowledge graph over existing notes, questions and schedules.

Only graph metadata is new. Prose stays in knowledge.py; existing identities,
question levels and review history are reused. Reads never import or assess.
"""
import hashlib
import json
import uuid
from collections import deque

from . import knowledge, knowledge_points, review
from .db import dicts, transaction
from .graph import ValidationError, now_iso

KINDS = ('project', 'module', 'flow', 'step', 'knowledge', 'option', 'claim')
RELATIONS = ('contains', 'uses', 'requires', 'next', 'fails_to', 'supports',
             'alternative_to', 'upgrade_to', 'abstracts_to', 'analogous_to')
LEARNING = ('unknown', 'not_started', 'learning', 'learned')
MASTERY = ('unassessed', 'weak', 'usable', 'solid')
CORE = ('contains', 'uses', 'requires', 'next', 'fails_to', 'supports')
NODE_FIELDS = ('title', 'aliases', 'owner_ref', 'domains', 'summary', 'content_ref',
               'content_state', 'sources', 'evidence_status', 'feasibility',
               'presentation', 'provenance', 'revision_note')
EDGE_FIELDS = ('usage', 'used_parts', 'required_depth', 'default_expansion',
               'rationale', 'conditions', 'tradeoffs', 'seq', 'branch_label')


def setup(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS review_graph_nodes(
      id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS review_graph_edges(
      id TEXT PRIMARY KEY,
      from_id TEXT NOT NULL REFERENCES review_graph_nodes(id),
      to_id TEXT NOT NULL REFERENCES review_graph_nodes(id),
      relation TEXT NOT NULL, context_project_id TEXT NOT NULL DEFAULT '',
      inclusion TEXT NOT NULL DEFAULT 'core', payload TEXT NOT NULL,
      UNIQUE(from_id,to_id,relation,context_project_id));
    CREATE INDEX IF NOT EXISTS idx_rg_edges_from ON review_graph_edges(from_id);
    CREATE INDEX IF NOT EXISTS idx_rg_edges_to ON review_graph_edges(to_id);
    CREATE TABLE IF NOT EXISTS review_graph_bindings(
      ref_type TEXT NOT NULL, course_id TEXT NOT NULL DEFAULT '', ref_id TEXT NOT NULL,
      node_id TEXT NOT NULL REFERENCES review_graph_nodes(id),
      PRIMARY KEY(ref_type,course_id,ref_id));
    CREATE TABLE IF NOT EXISTS review_graph_findings(
      id TEXT PRIMARY KEY, project_id TEXT NOT NULL, payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS review_graph_questions(
      question_id TEXT NOT NULL REFERENCES questions(id),
      node_id TEXT NOT NULL REFERENCES review_graph_nodes(id),
      context_project_id TEXT NOT NULL DEFAULT '', payload TEXT NOT NULL,
      PRIMARY KEY(question_id,node_id,context_project_id));
    CREATE TABLE IF NOT EXISTS review_graph_assessments(
      id INTEGER PRIMARY KEY, node_id TEXT NOT NULL REFERENCES review_graph_nodes(id),
      context_edge_id TEXT REFERENCES review_graph_edges(id),
      mastery TEXT, learning_status TEXT, gap_note TEXT,
      basis TEXT NOT NULL DEFAULT '', question_id TEXT REFERENCES questions(id),
      assessed_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_rg_assess_node ON review_graph_assessments(node_id,id);
    CREATE TABLE IF NOT EXISTS review_graph_requests(
      id TEXT PRIMARY KEY, operation TEXT NOT NULL, fingerprint TEXT NOT NULL,
      receipt TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS review_graph_pending_links(
      id TEXT PRIMARY KEY, project_id TEXT NOT NULL, payload TEXT NOT NULL);
    ''')


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _choice(value, options, name):
    if value not in options:
        raise ValidationError('Invalid %s: %r' % (name, value))


def _limit(value, maximum=100):
    return max(1, min(int(value), maximum))


def _canonical(conn, node_id):
    row = conn.execute('SELECT node_id FROM review_graph_bindings '
                       "WHERE ref_type='node' AND course_id='' AND ref_id=?",
                       (node_id,)).fetchone()
    return row[0] if row else node_id


def _domain(area):
    return {'backend': ['network', 'os'], 'cpp': ['cpp'],
            'algorithms': ['algorithms'], 'database': ['database']}.get(area, [])


def _base(conn, node_id):
    """Read adapters, not copies of bodies or inferred mastery."""
    p = conn.execute('SELECT p.*,b.area FROM knowledge_point_index p '
                     'JOIN knowledge_blocks b ON b.id=p.block_id WHERE p.id=?',
                     (node_id,)).fetchone()
    if p:
        return {'id': node_id, 'kind': 'knowledge', 'title': p['title'],
                'owner_ref': {'type': 'knowledge_block', 'id': p['block_id']},
                'domains': _domain(p['area']), 'active': bool(p['active']),
                'content_ref': {'type': 'knowledge_point', 'id': node_id},
                'content_state': 'linked'}
    n = conn.execute('SELECT * FROM nodes WHERE id=?', (node_id,)).fetchone()
    if n:
        return {'id': node_id, 'kind': 'project' if n['type'] == 'course' else
                'module' if n['type'] in ('module', 'unit') else 'knowledge',
                'title': n['title'], 'summary': n['summary'],
                'owner_ref': {'type': 'course', 'id': n['course_id']},
                'content_state': 'outline' if n['summary'] else 'name_only'}
    b = conn.execute('SELECT * FROM knowledge_blocks WHERE id=?', (node_id,)).fetchone()
    if b:
        return {'id': node_id, 'kind': 'knowledge', 'title': b['title'],
                'domains': _domain(b['area']), 'content_state': 'linked',
                'content_ref': {'type': 'knowledge_block', 'id': node_id}}
    if isinstance(node_id, str) and node_id.startswith('review:'):
        r = conn.execute('SELECT * FROM review_items WHERE id=?',
                         (node_id[7:],)).fetchone()
        if r:
            return {'id': node_id, 'kind': 'knowledge', 'title': r['title'],
                    'content_state': 'linked' if r['source_id'] else 'name_only',
                    'content_ref': {'type': 'review_item', 'id': r['id']},
                    'legacy_refs': [{'type': 'review_point', 'course_id': r['course_id'],
                                     'id': r['point_id']}]}
    return None


def _node(conn, node_id):
    node_id = _canonical(conn, node_id)
    row = conn.execute('SELECT payload,updated_at FROM review_graph_nodes WHERE id=?',
                       (node_id,)).fetchone()
    base = _base(conn, node_id) or {}
    if not row and not base:
        raise ValidationError('Unknown graph node: %s' % node_id)
    result = {'id': node_id, 'aliases': [], 'domains': [], 'summary': '',
              'content_ref': None, 'content_state': 'name_only',
              'learning_status': 'unknown', 'mastery': 'unassessed', 'gaps': []}
    result.update(base)
    if row:
        result.update(json.loads(row['payload']))
        result['updated_at'] = row['updated_at']
    result['legacy_refs'] = dicts(conn.execute(
        'SELECT ref_type AS type,course_id,ref_id AS id FROM review_graph_bindings WHERE node_id=?',
        (node_id,))) + result.get('legacy_refs', [])
    return result


def _ensure(conn, node_id):
    node_id = _canonical(conn, node_id)
    if not conn.execute('SELECT 1 FROM review_graph_nodes WHERE id=?', (node_id,)).fetchone():
        base = _base(conn, node_id)
        if not base:
            raise ValidationError('Unknown graph node: %s' % node_id)
        # Preserve live title/body adapters instead of freezing a second copy.
        conn.execute('INSERT INTO review_graph_nodes VALUES(?,?,?)',
                     (node_id, '{}', now_iso()))
    return node_id


def _request(conn, request_id, operation, payload):
    if not request_id or not isinstance(request_id, str):
        raise ValidationError('request_id is required')
    digest = hashlib.sha256(_json(payload).encode('utf-8')).hexdigest()
    old = conn.execute('SELECT * FROM review_graph_requests WHERE id=?', (request_id,)).fetchone()
    if old:
        if old['operation'] != operation or old['fingerprint'] != digest:
            raise ValidationError('request_id was already used with different content')
        return digest, json.loads(old['receipt'])
    return digest, None


def _receipt(conn, request_id, operation, digest, result):
    conn.execute('INSERT INTO review_graph_requests VALUES(?,?,?,?)',
                 (request_id, operation, digest, _json(result)))
    return result


def commit(conn, request_id, project_id=None, nodes=None, edges=None,
           findings=None, question_links=None, legacy_bindings=None, flow_steps=None):
    """Incremental atomic upsert. Omitted fields preserve existing values."""
    payload = dict(project_id=project_id, nodes=nodes or [], edges=edges or [],
                   findings=findings or [], question_links=question_links or [],
                   legacy_bindings=legacy_bindings or [])
    if flow_steps:
        payload['flow_steps'] = flow_steps
    digest, previous = _request(conn, request_id, 'commit', payload)
    if previous is not None:
        return previous
    id_map, edge_map, reused = {}, {}, 0
    pending_content, pending_links = [], []
    with transaction(conn):
        if flow_steps:
            from .flow_steps import expand
            step_nodes, step_edges = expand(conn, flow_steps, project_id, nodes)
            nodes = list(nodes or []) + step_nodes
            edges = list(edges or []) + step_edges
        for data in nodes or []:
            key = data.get('client_key') or data.get('id')
            if not key or key in id_map:
                raise ValidationError('nodes require distinct id or client_key')
            node_id = _canonical(conn, data.get('id') or 'rv-' + uuid.uuid4().hex)
            row = conn.execute('SELECT payload FROM review_graph_nodes WHERE id=?', (node_id,)).fetchone()
            base = _base(conn, node_id)
            old = json.loads(row[0]) if row else {}
            if not row and not base and (not data.get('title') or not data.get('kind')):
                raise ValidationError('New nodes require title and kind')
            combined = dict(base or {}, **old)
            for name in NODE_FIELDS:
                if name in data:
                    combined[name] = data[name]
            combined['id'] = node_id
            combined['kind'] = data.get('kind', combined.get('kind', 'knowledge'))
            _choice(combined['kind'], KINDS, 'kind')
            if not isinstance(combined.get('title'), str) or not combined['title'].strip():
                raise ValidationError('title must be nonempty')
            for field in ('domains', 'aliases'):
                if not isinstance(combined.get(field, []), list):
                    raise ValidationError(field + ' must be a list')
            # Imports cannot overwrite assessments. State lives in the assessment log.
            combined.pop('mastery', None)
            combined.pop('learning_status', None)
            if data.get('content') is not None:
                block = (combined.get('content_ref') or {}).get('id')
                if (combined.get('content_ref') or {}).get('type') != 'knowledge_block':
                    block = 'review-body:' + node_id
                knowledge.append(conn, block, combined['title'], combined['title'],
                                 data['content'], area=data.get('area', 'other'),
                                 kind='correction' if row else 'explanation',
                                 entry_id='rg-' + hashlib.sha256((request_id + node_id).encode()).hexdigest())
                combined['content_ref'] = {'type': 'knowledge_block', 'id': block}
                combined['content_state'] = 'linked'
            combined.setdefault('content_state', 'linked' if combined.get('content_ref') else
                                'outline' if combined.get('summary') else 'name_only')
            _choice(combined['content_state'], ('name_only', 'outline', 'linked'), 'content_state')
            if combined.get('presentation') is not None:
                _choice(combined['presentation'], ('core', 'followup', 'extension'), 'presentation')
            conn.execute('INSERT INTO review_graph_nodes VALUES(?,?,?) ON CONFLICT(id) '
                         'DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at',
                         (node_id, _json(combined), now_iso()))
            id_map[key] = node_id
            reused += int(bool(row or base))
            if not combined.get('content_ref') and combined['kind'] != 'step':
                pending_content.append(node_id)

        def ref(value):
            return _ensure(conn, id_map.get(value, value))

        if project_id:
            project_id = ref(project_id)
        for data in edges or []:
            src, dst = ref(data['from']), ref(data['to'])
            relation = data['relation']
            _choice(relation, RELATIONS, 'relation')
            context = data.get('context_project_id', project_id) or ''
            if context:
                context = ref(context)
            old = conn.execute('SELECT * FROM review_graph_edges WHERE from_id=? AND to_id=? '
                               'AND relation=? AND context_project_id=?', (src, dst, relation, context)).fetchone()
            eid = data.get('id') or (old['id'] if old else 're-' + uuid.uuid4().hex)
            if old and data.get('id') and eid != old['id']:
                raise ValidationError('Existing relation has a different id')
            if not old and conn.execute('SELECT 1 FROM review_graph_edges WHERE id=?', (eid,)).fetchone():
                raise ValidationError('edge id already identifies another relation')
            values = json.loads(old['payload']) if old else {}
            values.update({k: data[k] for k in EDGE_FIELDS if k in data})
            values.setdefault('used_parts', [])
            if not isinstance(values['used_parts'], list):
                raise ValidationError('used_parts must be a list')
            if values.get('required_depth') is not None:
                _choice(values['required_depth'], ('concept', 'mechanism', 'implementation_tradeoff'), 'required_depth')
            if values.get('default_expansion') is not None:
                _choice(values['default_expansion'], ('reference', 'used_parts', 'full'), 'default_expansion')
            values['used_parts'] = [id_map.get(x, x) if isinstance(x, str) else x for x in values['used_parts']]
            inclusion = data.get('inclusion', old['inclusion'] if old else
                                 'core' if relation in CORE else 'extension')
            _choice(inclusion, ('core', 'extension'), 'inclusion')
            conn.execute('INSERT INTO review_graph_edges VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) '
                         'DO UPDATE SET inclusion=excluded.inclusion,payload=excluded.payload',
                         (eid, src, dst, relation, context, inclusion, _json(values)))
            edge_map[data.get('client_key') or eid] = eid
        for binding in legacy_bindings or []:
            node = ref(binding['node_id'])
            typ, course, rid = binding['type'], binding.get('course_id', ''), str(binding['id'])
            if typ == 'review_point':
                r = conn.execute('SELECT id FROM review_items WHERE course_id=? AND point_id=?', (course, rid)).fetchone()
                if not r:
                    raise ValidationError('Unknown legacy review point: %s/%s' % (course, rid))
                old_id = 'review:%s' % r[0]
                if old_id != node:
                    _bind(conn, 'node', '', old_id, node)
            _bind(conn, typ, course, rid, node)
        for data in findings or []:
            fid = data.get('id') or 'rf-' + uuid.uuid4().hex
            old = conn.execute('SELECT project_id,payload FROM review_graph_findings WHERE id=?', (fid,)).fetchone()
            if old and old['project_id'] != (project_id or ''):
                raise ValidationError('finding belongs to another project')
            value = json.loads(old['payload']) if old else {}
            value.update(data)
            value.update(id=fid, project_id=project_id)
            _choice(value.get('category'), ('flow_gap', 'design_gap', 'material_question'), 'finding category')
            _choice(value.get('state', 'open'), ('open', 'deferred', 'resolved'), 'finding state')
            value.setdefault('state', 'open')
            value['target_node_ids'] = [ref(x) for x in value.get('target_node_ids', [])]
            value['target_edge_ids'] = [edge_map.get(x, x) for x in value.get('target_edge_ids', [])]
            for eid in value['target_edge_ids']:
                if not conn.execute('SELECT 1 FROM review_graph_edges WHERE id=?', (eid,)).fetchone():
                    raise ValidationError('Unknown finding edge: ' + eid)
            conn.execute('INSERT INTO review_graph_findings VALUES(?,?,?) ON CONFLICT(id) '
                         'DO UPDATE SET payload=excluded.payload', (fid, project_id or '', _json(value)))
        for data in question_links or []:
            if not data.get('question_id'):
                pending_links.append(data)  # Local report labels are not global question IDs.
                pid = hashlib.sha256(_json([project_id, data]).encode()).hexdigest()
                conn.execute('INSERT OR IGNORE INTO review_graph_pending_links VALUES(?,?,?)',
                             (pid, project_id or '', _json(data)))
                continue
            qid, node = data['question_id'], ref(data['node_id'])
            if not conn.execute('SELECT 1 FROM questions WHERE id=?', (qid,)).fetchone():
                raise ValidationError('Unknown question: ' + qid)
            context = data.get('context_project_id', project_id) or ''
            if context:
                context = ref(context)
            if data.get('action') == 'unlink':
                conn.execute('DELETE FROM review_graph_questions WHERE question_id=? AND node_id=? '
                             'AND context_project_id=?', (qid, node, context))
                continue
            old_link = conn.execute('SELECT payload FROM review_graph_questions WHERE question_id=? '
                                    'AND node_id=? AND context_project_id=?', (qid, node, context)).fetchone()
            link_payload = json.loads(old_link[0]) if old_link else {}
            link_payload.update({k: v for k, v in data.items() if k not in
                                 ('question_id', 'node_id', 'context_project_id', 'action')})
            conn.execute('INSERT INTO review_graph_questions VALUES(?,?,?,?) ON CONFLICT '
                         '(question_id,node_id,context_project_id) DO UPDATE SET payload=excluded.payload',
                         (qid, node, context, _json(link_payload)))
            if data.get('pending_link_id'):
                conn.execute('DELETE FROM review_graph_pending_links WHERE id=? AND project_id=?',
                             (data['pending_link_id'], context))
        result = {'success': True, 'upserted': len(nodes or []), 'reused': reused,
                  'id_map': id_map, 'edge_map': edge_map, 'pending_content': pending_content,
                  'pending_links': pending_links, 'revision': now_iso()}
        return _receipt(conn, request_id, 'commit', digest, result)


def relocate_edges(conn, request_id, project_id, moves):
    """Guarded project restructuring; preserve edge IDs and attached assessments.

    Each move supplies id, expected_from, expected_to, from and to. This is
    deliberately not a delete/recreate operation and cannot edit public edges.
    """
    payload = dict(project_id=project_id, moves=moves)
    digest, previous = _request(conn, request_id, 'relocate_edges', payload)
    if previous is not None:
        return previous
    if not project_id or not moves:
        raise ValidationError('project_id and moves are required')
    with transaction(conn):
        if _node(conn, project_id)['kind'] != 'project':
            raise ValidationError('project_id must identify a project')
        seen = set()
        for move in moves:
            eid = move['id']
            if eid in seen:
                raise ValidationError('Duplicate edge move')
            seen.add(eid)
            row = conn.execute('SELECT * FROM review_graph_edges WHERE id=?', (eid,)).fetchone()
            if not row or row['context_project_id'] != project_id:
                raise ValidationError('Only edges belonging to this project can move')
            if row['relation'] not in ('contains', 'uses', 'next'):
                raise ValidationError('Only contains/uses/next edges can move')
            if (row['from_id'], row['to_id']) != (move['expected_from'], move['expected_to']):
                raise ValidationError('Edge changed since read; reload before restructuring')
            src, dst = _canonical(conn, move['from']), _canonical(conn, move['to'])
            source, target = _node(conn, src), _node(conn, dst)
            if row['relation'] == 'uses':
                if target['kind'] != 'knowledge' or source['kind'] not in ('module', 'flow'):
                    raise ValidationError('uses must connect a module/flow to knowledge')
            elif row['relation'] == 'next':
                if source['kind'] != 'flow' or target['kind'] != 'flow':
                    raise ValidationError('next must connect project flows')
            elif (source['kind'], target['kind']) not in (('project', 'module'), ('module', 'flow')):
                raise ValidationError('Project hierarchy must be project -> module -> flow')
            # The new source must already be structurally inside this project.
            ancestors, queue = set(), [src]
            while queue:
                current = queue.pop()
                if current in ancestors:
                    continue
                ancestors.add(current)
                queue.extend(r[0] for r in conn.execute(
                    "SELECT from_id FROM review_graph_edges WHERE to_id=? AND relation='contains' "
                    'AND context_project_id=?', (current, project_id)))
            if project_id not in ancestors or (row['relation'] == 'contains' and dst in ancestors):
                raise ValidationError('Destination parent is outside project or creates a cycle')
            if row['relation'] == 'next':
                pending, visited = [dst], set()
                while pending:
                    current = pending.pop()
                    if current in visited:
                        continue
                    visited.add(current)
                    pending.extend(r[0] for r in conn.execute(
                        "SELECT from_id FROM review_graph_edges WHERE to_id=? AND relation='contains' "
                        'AND context_project_id=?', (current, project_id)))
                if project_id not in visited:
                    raise ValidationError('next target is outside project')
            conflict = conn.execute('SELECT id FROM review_graph_edges WHERE from_id=? AND to_id=? '
                'AND relation=? AND context_project_id=? AND id<>?',
                (src, dst, row['relation'], project_id, eid)).fetchone()
            if conflict:
                raise ValidationError('Target relation already exists; refuse identity merge')
            if row['relation'] == 'contains' and conn.execute(
                "SELECT 1 FROM review_graph_edges WHERE to_id=? AND relation='contains' AND id<>?",
                (dst, eid)).fetchone():
                raise ValidationError('Flow already has another parent')
            conn.execute('UPDATE review_graph_edges SET from_id=?,to_id=? WHERE id=?', (src, dst, eid))
        return _receipt(conn, request_id, 'relocate_edges', digest,
                        {'success': True, 'moved_edge_ids': sorted(seen)})


def _bind(conn, typ, course, rid, node):
    old = conn.execute('SELECT node_id FROM review_graph_bindings WHERE ref_type=? AND course_id=? AND ref_id=?',
                       (typ, course, rid)).fetchone()
    if old and old[0] != node:
        raise ValidationError('Reference already bound to another node')
    conn.execute('INSERT OR IGNORE INTO review_graph_bindings VALUES(?,?,?,?)', (typ, course, rid, node))


def _assessed(conn, node_id, edge_id=None):
    rows = dicts(conn.execute('SELECT mastery,learning_status,gap_note,basis,assessed_at '
                              'FROM review_graph_assessments WHERE node_id=? AND '
                              'context_edge_id IS ? ORDER BY id DESC LIMIT 100', (node_id, edge_id)))
    result = {}
    for row in rows:
        for key, value in row.items():
            if value is not None and key not in result:
                result[key] = value
    return result


def _schedules(conn, node_id):
    node_id = _canonical(conn, node_id)
    rows = dicts(conn.execute('SELECT r.* FROM review_items r WHERE r.point_id=? OR '
        'EXISTS(SELECT 1 FROM review_graph_bindings b WHERE b.node_id=? AND '
        "b.ref_type='review_point' AND b.course_id=r.course_id AND b.ref_id=r.point_id)",
        (node_id, node_id)))
    if node_id.startswith('review:'):
        r = conn.execute('SELECT * FROM review_items WHERE id=?', (node_id[7:],)).fetchone()
        if r and all(x['id'] != r['id'] for x in rows):
            rows.append(dict(r))
    return rows


def get_node(conn, node_id, context_edge_id=None, include_content=False):
    result = _node(conn, node_id)
    general = _assessed(conn, result['id'])
    if context_edge_id:
        edge = conn.execute('SELECT to_id FROM review_graph_edges WHERE id=?', (context_edge_id,)).fetchone()
        if not edge or _canonical(conn, edge['to_id']) != result['id']:
            raise ValidationError('context_edge_id must point to the assessed node')
    local = _assessed(conn, result['id'], context_edge_id) if context_edge_id else {}
    result.update({k: general[k] for k in ('mastery', 'learning_status') if k in general})
    result['gaps'] = [general['gap_note']] if general.get('gap_note') else []
    result['general_mastery'] = result['mastery']
    result['context_mastery'] = local.get('mastery')
    result['effective_mastery'] = local.get('mastery', result['mastery'])
    result['assessment'] = general or None
    if local:
        result['context_assessment'] = local
        if local.get('gap_note'):
            result['context_gaps'] = [local['gap_note']]
    result['review_briefs'] = [{k: r[k] for k in ('id', 'course_id', 'point_id', 'status',
        'level', 'last_reviewed', 'next_due')} for r in _schedules(conn, result['id'])]
    if include_content:
        result['connections'] = connections(conn, result['id'])
        result['question_refs'] = _questions(conn, [result['id']])
        ref = result.get('content_ref') or {}
        typ, rid = ref.get('type'), ref.get('id')
        result['content'] = None
        if typ == 'knowledge_point':
            result['content'] = knowledge_points.read(conn, rid)
        elif typ == 'knowledge_block':
            result['content'] = knowledge.read(conn, rid)
        elif typ == 'review_item':
            result['content'] = review.prepare(conn, int(rid))
        elif typ == 'source_anchor':
            result['content'] = dicts(conn.execute('SELECT anchor,text FROM chunks WHERE source_id=? AND anchor=?',
                (rid, ref.get('anchor', ''))))
        elif typ == 'lesson':
            result['content'] = dicts(conn.execute('SELECT mode,content FROM lesson_artifacts WHERE node_id=?', (rid,)))
    return result


def _edges(conn, project_id=None):
    result = []
    sql = 'SELECT * FROM review_graph_edges'
    rows = conn.execute(sql + ' WHERE context_project_id IN (?,?)', ('', project_id)) if project_id else conn.execute(sql)
    for r in rows:
        e = json.loads(r['payload'])
        e.update(id=r['id'], **{'from': _canonical(conn, r['from_id']), 'to': _canonical(conn, r['to_id']),
                               'relation': r['relation'], 'context_project_id': r['context_project_id'] or None,
                               'inclusion': r['inclusion']})
        result.append(e)
    # Keep old link meaning and direction; don't turn a generic relation into
    # a project requirement. These can be shown through the extension switch.
    for table in ('knowledge_point_links', 'knowledge_relations'):
        for r in conn.execute('SELECT from_id,to_id,relation,note FROM ' + table):
            src, dst = _canonical(conn, r['from_id']), _canonical(conn, r['to_id'])
            if src == dst:
                continue
            if any(e['from'] == src and e['to'] == dst for e in result):
                continue
            result.append({'id': 'legacy:%s:%s:%s:%s' % (table, src, dst, r['relation']),
                           'from': src, 'to': dst, 'relation': r['relation'],
                           'legacy_relation': r['relation'], 'context_project_id': None,
                           'inclusion': 'extension', 'usage': r['note'], 'origin': 'legacy'})
    return result


def _children(conn, node_id):
    return [r[0] for r in conn.execute('SELECT id FROM knowledge_point_index WHERE parent_id=? AND active=1',
                                      (node_id,))] + [r[0] for r in conn.execute(
        "SELECT src FROM edges WHERE dst=? AND type='part_of'", (node_id,))] + [r[0] for r in conn.execute(
        'SELECT id FROM knowledge_point_index WHERE block_id=? AND parent_id IS NULL AND active=1', (node_id,))]


def _required_scope(conn, root_id, edges):
    """Required membership is independent of visible dependency expansion."""
    outgoing = {}
    for e in edges:
        if e['inclusion'] == 'core':
            outgoing.setdefault(e['from'], []).append(e)
    required, seen = set(), set()
    queue = deque([(_canonical(conn, root_id), True)])
    while queue:
        nid, expand = queue.popleft()
        if (nid, expand) in seen:
            continue
        seen.add((nid, expand))
        required.add(nid)
        if not expand:
            continue
        queue.extend((_canonical(conn, x), True) for x in _children(conn, nid))
        for e in outgoing.get(nid, []):
            dep = e['relation'] in ('uses', 'requires')
            queue.append((e['to'], not dep))
            for part in e.get('used_parts', []) if dep else []:
                pid = part.get('node_id') if isinstance(part, dict) else part
                if pid and (_base(conn, pid) or conn.execute(
                        'SELECT 1 FROM review_graph_nodes WHERE id=?', (pid,)).fetchone()):
                    queue.append((_canonical(conn, pid), True))
    return required


def _questions(conn, node_ids, project_id=None):
    from . import question_links
    scope=set()
    for nid in node_ids:scope.update(question_links.scope_nodes(conn,nid))
    return question_links.resolve(conn,scope,project_id)


def get_map(conn, root_id=None, project_id=None, domains=None, learning_status=None,
            mastery=None, include_extensions=False, dependency_expansion='reference',
            node_id=None, cursor=0, limit=20):
    """Bounded graph summary. Dependency visibility does not enlarge required scope."""
    _choice(dependency_expansion, ('reference', 'used_parts', 'full'), 'dependency_expansion')
    if learning_status:
        _choice(learning_status, LEARNING, 'learning_status')
    if mastery:
        _choice(mastery, MASTERY, 'mastery')
    root_id = node_id or root_id or project_id
    project_id = _canonical(conn, project_id) if project_id else None
    edges = _edges(conn, project_id)
    outgoing = {}
    for e in edges:
        outgoing.setdefault(e['from'], []).append(e)
    visible, required, matched = set(), set(), {}
    if root_id:
        root_id = _canonical(conn, root_id)
        _node(conn, root_id)
        required = _required_scope(conn, root_id, edges)
        # Core traversal stops at reused dependency roots; each use selects its parts.
        queue = deque([(root_id, True, True, None)])
        seen = set()
        while queue:
            nid, is_required, expand, via = queue.popleft()
            marker = (nid, is_required, expand)
            if marker in seen:
                continue
            seen.add(marker)
            visible.add(nid)
            if via:
                matched.setdefault(nid, []).append(via)
            if not expand:
                continue
            for child in _children(conn, nid):
                queue.append((_canonical(conn, child), is_required, True, 'legacy:contains:' + nid))
            for e in outgoing.get(nid, []):
                extension = e['inclusion'] == 'extension'
                if extension and not include_extensions:
                    continue
                target_required = is_required and not extension
                dep = e['relation'] in ('uses', 'requires')
                # Explicit parts define required scope regardless of display switch.
                for part in e.get('used_parts', []) if dep and dependency_expansion != 'reference' else []:
                    pid = part.get('node_id') if isinstance(part, dict) else part
                    if pid and (_base(conn, pid) or conn.execute(
                            'SELECT 1 FROM review_graph_nodes WHERE id=?', (pid,)).fetchone()):
                        queue.append((_canonical(conn, pid), target_required, True, e['id']))
                queue.append((e['to'], target_required, not dep, e['id']))
                if dep and dependency_expansion == 'full':
                    queue.append((e['to'], False, True, e['id']))
    else:
        visible = {r[0] for r in conn.execute('SELECT id FROM review_graph_nodes')}
        # Existing heading IDs are immediately queryable without copying/importing them.
        replaced = knowledge.canonical_replacements(conn)
        curated = {json.loads(r[0]).get('content_ref', {}).get('id')
                   for r in conn.execute('SELECT payload FROM review_graph_nodes')
                   if json.loads(r[0]).get('provenance', {}).get('curated_index')}
        visible.update(r[0] for r in conn.execute('SELECT id,block_id FROM knowledge_point_index WHERE active=1')
                       if r[1] not in replaced and r[1] not in curated)
        if include_extensions:
            visible.update(e[k] for e in edges for k in ('from', 'to'))
        aliases = {r[0]: r[1] for r in conn.execute(
            "SELECT ref_id,node_id FROM review_graph_bindings WHERE ref_type='node' AND course_id='' ")}
        visible = {aliases.get(x, x) for x in visible}
    cursor, limit = max(0, int(cursor)), _limit(limit, 300)
    pre_paginated = not (domains or learning_status or mastery)
    selected_ids = sorted(visible)
    total = len(selected_ids)
    if domains:
        point_domains = {r[0]: _domain(r[1]) for r in conn.execute(
            'SELECT p.id,b.area FROM knowledge_point_index p JOIN knowledge_blocks b ON b.id=p.block_id WHERE p.active=1')}
        point_domains.update({r[0]: _domain(r[1]) for r in conn.execute('SELECT id,area FROM knowledge_blocks')})
        for r in conn.execute('SELECT id,payload FROM review_graph_nodes'):
            n = json.loads(r[1])
            if 'domains' in n:
                point_domains[r[0]] = n['domains']
        selected_ids = [nid for nid in selected_ids if set(domains).intersection(point_domains.get(nid, []))]
    if pre_paginated:
        selected_ids = selected_ids[cursor:cursor + limit]
    results = []
    for nid in selected_ids:
        n = _node(conn, nid)
        general = _assessed(conn, nid)
        n.update({k: general[k] for k in ('mastery', 'learning_status') if k in general})
        n['general_mastery'] = n['mastery']
        n['context_mastery'] = None
        n['effective_mastery'] = n['mastery']
        local_edges = [e for e in edges if e['to'] == nid and e['context_project_id'] == project_id]
        local = [dict(edge_id=e['id'], **_assessed(conn, nid, e['id'])) for e in local_edges
                 if _assessed(conn, nid, e['id'])]
        n['context_assessments'] = local
        if len(local) == 1:
            n['context_mastery'] = local[0].get('mastery')
            n['effective_mastery'] = local[0].get('mastery', n['mastery'])
        local_masteries = {a['mastery'] for a in local if a.get('mastery')}
        if domains and not set(domains).intersection(n.get('domains', [])):
            continue
        if learning_status and n['learning_status'] != learning_status:
            continue
        if mastery and (mastery not in local_masteries if local_masteries else n['mastery'] != mastery):
            continue
        n['required'] = nid in required
        n['matched_via'] = sorted(set(matched.get(nid, [])))
        results.append(n)
    if not pre_paginated:
        total = len(results)
        results = results[cursor:cursor + limit]
    # Graph lists carry labels/state and refs; one-node reads carry bodies and
    # backstage metadata. Never send 800 nodes' history before paginating.
    fields = ('id', 'kind', 'title', 'domains', 'summary', 'owner_ref', 'content_ref', 'content_state',
              'learning_status', 'mastery', 'general_mastery', 'context_mastery',
              'effective_mastery', 'required', 'matched_via')
    results = [{k: n[k] for k in fields if k in n} for n in results]
    for n in results:
        if len(n.get('summary', '')) > 280:
            n['summary'] = n['summary'][:280] + '…'
    ids = {n['id'] for n in results}
    display_edges = [e for e in edges if e['from'] in ids and e['to'] in ids and
                     (include_extensions or e['inclusion'] != 'extension')]
    for n in results:
        for child in _children(conn, n['id']):
            child = _canonical(conn, child)
            if child in ids and not any(e['from'] == n['id'] and e['to'] == child and e['relation'] == 'contains'
                                       for e in display_edges):
                display_edges.append({'id': 'legacy:contains:%s:%s' % (n['id'], child),
                                      'from': n['id'], 'to': child, 'relation': 'contains',
                                      'inclusion': 'core', 'origin': 'legacy'})
    findings = [json.loads(r[0]) for r in conn.execute(
        'SELECT payload FROM review_graph_findings WHERE project_id=?', (project_id or '',))]
    findings = [f for f in findings if ids.intersection(f.get('target_node_ids', [])) or
                set(f.get('target_edge_ids', [])).intersection(e['id'] for e in display_edges)]
    roots = dicts(conn.execute("SELECT id,title FROM nodes WHERE type='course' ORDER BY title"))
    known = {r['id'] for r in roots}
    roots.extend({'id': r[0], 'title': json.loads(r[1])['title']} for r in conn.execute(
        'SELECT id,payload FROM review_graph_nodes') if r[0] not in known and
        json.loads(r[1]).get('kind') == 'project')
    return {'nodes': results, 'edges': display_edges, 'findings': findings,
            'question_refs': _questions(conn, ids, project_id), 'roots': roots,
            'pending_links': [dict(json.loads(r['payload']), pending_link_id=r['id']) for r in conn.execute(
                'SELECT id,payload FROM review_graph_pending_links WHERE project_id=? LIMIT 20',
                (project_id or '',))],
            'total': total, 'required_count': len(required),
            'next_cursor': cursor + limit if cursor + limit < total else None,
            'root_id': root_id, 'project_id': project_id}


def resolve(conn, mentions, project_id=None, limit_per_mention=5):
    """Name/alias/body candidates; never infer equality or learning state."""
    cap = _limit(limit_per_mention, 10)
    result = []
    points = dicts(conn.execute('SELECT p.id,p.title,p.block_id,p.start_line,p.end_line,b.area '
                                'FROM knowledge_point_index p JOIN knowledge_blocks b ON b.id=p.block_id WHERE p.active=1'))
    custom = [(r[0], json.loads(r[1])) for r in conn.execute('SELECT id,payload FROM review_graph_nodes')]
    bodies = {}
    for mention in mentions:
        terms = [t.strip().casefold() for t in [mention['title']] + mention.get('aliases', []) if t.strip()]
        hits = {}
        for pid, n in custom:
            names = [n.get('title', '')] + n.get('aliases', [])
            score = 3 if any(t == name.casefold() for t in terms for name in names) else 2 if any(
                t in name.casefold() for t in terms for name in names) else 0
            if score:
                hits[pid] = {'id': pid, 'title': n.get('title', pid), 'matched_on': 'title_or_alias',
                             'content_ref': n.get('content_ref'), 'excerpt': n.get('summary', '')[:240], 'score': score}
        for p in points:
            names = p['title'].casefold()
            score = 3 if names in terms else 2 if any(t in names for t in terms) else 0
            if p['block_id'] not in bodies:
                bodies[p['block_id']] = knowledge_points.body(conn, p['block_id']).splitlines()
            text = '\n'.join(bodies[p['block_id']][p['start_line']:p['end_line']])
            if not score and any(t in text.casefold() for t in terms):
                score = 1
            if score:
                pos = min((text.casefold().find(t) for t in terms if t in text.casefold()), default=0)
                if score >= hits.get(p['id'], {}).get('score', 0):
                    hits[p['id']] = {'id': p['id'], 'title': p['title'],
                                    'content_ref': {'type': 'knowledge_point', 'id': p['id']},
                                    'matched_on': 'title' if score > 1 else 'body',
                                    'excerpt': text[max(0, pos - 40):pos + 200], 'score': score}
        candidates = sorted(hits.values(), key=lambda h: (-h['score'], h['title']))[:cap]
        result.append({'client_key': mention.get('client_key'), 'title': mention['title'],
                       'status': 'not_found' if not candidates else 'candidate' if len(candidates) == 1 else 'ambiguous',
                       'candidates': candidates})
    return {'project_id': project_id, 'mentions': result}


def connections(conn, node_id):
    """Reverse project links, without bodies or teaching history."""
    nid = _canonical(conn, node_id)
    rows = dicts(conn.execute('SELECT id,from_id,to_id,relation,context_project_id,inclusion,payload '
                              'FROM review_graph_edges WHERE from_id=? OR to_id=? LIMIT 50', (nid, nid)))
    for r in rows:
        r['target_id'] = r['to_id'] if r['from_id'] == nid else r['from_id']
        r['target_title'] = _node(conn, r['target_id'])['title']
        r['usage'] = json.loads(r.pop('payload')).get('usage', '')
    return rows


def assess(conn, request_id, assessments=None, recall_results=None, question_id=None):
    payload = dict(assessments=assessments or [], recall_results=recall_results or [], question_id=question_id)
    digest, previous = _request(conn, request_id, 'assessment', payload)
    if previous is not None:
        return previous
    if question_id and not conn.execute('SELECT 1 FROM questions WHERE id=?', (question_id,)).fetchone():
        raise ValidationError('Unknown question: ' + question_id)
    changed, schedules = [], []
    with transaction(conn):
        for data in assessments or []:
            nid = _ensure(conn, data['node_id'])
            edge_id = data.get('context_edge_id')
            if edge_id:
                edge = conn.execute('SELECT to_id FROM review_graph_edges WHERE id=?', (edge_id,)).fetchone()
                if not edge or _canonical(conn, edge[0]) != nid:
                    raise ValidationError('context_edge_id must point to the assessed node')
            if 'mastery' in data:
                _choice(data['mastery'], MASTERY, 'mastery')
            if 'learning_status' in data:
                _choice(data['learning_status'], LEARNING, 'learning_status')
            conn.execute('INSERT INTO review_graph_assessments(node_id,context_edge_id,mastery,learning_status,'
                         'gap_note,basis,question_id,assessed_at) VALUES(?,?,?,?,?,?,?,?)',
                         (nid, edge_id, data.get('mastery'), data.get('learning_status'), data.get('gap_note'),
                          data.get('basis', ''), question_id, now_iso()))
            changed.append({'node_id': nid, 'context_edge_id': edge_id})
        for data in recall_results or []:
            nid = _ensure(conn, data['node_id'])
            context_edge_id = data.get('context_edge_id')
            if context_edge_id:
                edge = conn.execute('SELECT to_id FROM review_graph_edges WHERE id=?', (context_edge_id,)).fetchone()
                if not edge or _canonical(conn, edge[0]) != nid:
                    raise ValidationError('context_edge_id must point to the recalled node')
            n = get_node(conn, nid)
            if n['learning_status'] == 'not_started':
                raise ValidationError('Unlearned nodes are excluded from recall; record learning status first')
            rows = _schedules(conn, nid)
            chosen = data.get('review_item_id')
            if chosen is not None and not any(r['id'] == chosen for r in rows):
                raise ValidationError('review_item_id is not bound to this node')
            if chosen is None and rows:
                chosen = sorted(rows, key=lambda r: (r['next_due'] is None, r['next_due'] or '', r['id']))[0]['id']
            if chosen is None:
                ref = n.get('content_ref') or {}
                source = ref.get('id') if ref.get('type') == 'source_anchor' else None
                cur = conn.execute('INSERT INTO review_items(course_id,point_id,title,source_id,anchor,created_at) '
                    'VALUES(?,?,?,?,?,?)', ('knowledge-review', nid, n['title'], source, ref.get('anchor', ''), now_iso()))
                chosen = cur.lastrowid
            update = review.record(conn, chosen, data['result'], data.get('hint_level', 0), data.get('note', ''))
            update['node_id'] = nid
            update['other_schedules_preserved'] = len(rows) - 1 if rows else 0
            schedules.append(update)
            effective = 'partial' if data['result'] == 'correct' and data.get('hint_level', 0) > 1 else data['result']
            conn.execute('INSERT INTO review_graph_assessments(node_id,context_edge_id,mastery,learning_status,gap_note,basis,assessed_at) '
                         'VALUES(?,?,?,?,?,?,?)', (nid, context_edge_id, 'usable' if effective == 'correct' else 'weak', 'learned',
                                                None if effective == 'correct' else data.get('note') or None,
                                                'recall', now_iso()))
        return _receipt(conn, request_id, 'assessment', digest,
                        {'success': True, 'updated': changed, 'schedules': schedules})


def today(conn, project_id=None, domains=None, limit=15):
    """Canonical cards, reusing old dates and omitting explicitly unlearned nodes."""
    from datetime import date
    scope = None
    if project_id:
        scope = _required_scope(conn, project_id, _edges(conn, project_id))
    grouped = {}
    day = date.today().isoformat()
    for r in conn.execute('SELECT * FROM review_items ORDER BY next_due,id'):
        binding = conn.execute("SELECT node_id FROM review_graph_bindings WHERE ref_type='review_point' "
                               'AND course_id=? AND ref_id=?', (r['course_id'], r['point_id'])).fetchone()
        nid = binding[0] if binding else r['point_id'] if (_base(conn, r['point_id']) or conn.execute(
            'SELECT 1 FROM review_graph_nodes WHERE id=?', (r['point_id'],)).fetchone()) else 'review:%s' % r['id']
        nid = _canonical(conn, nid)
        if scope is not None and nid not in scope:
            continue
        grouped.setdefault(nid, []).append(dict(r))
    cards = []
    for nid, rows in grouped.items():
        n = get_node(conn, nid)
        if n['learning_status'] == 'not_started' or domains and not set(domains).intersection(n.get('domains', [])):
            continue
        active = [r for r in rows if r['status'] == 'active']
        due = [r for r in active if r['next_due'] and r['next_due'] <= day]
        if active and not due:
            continue
        r = sorted(due or rows, key=lambda r: (r['next_due'] is None, r['next_due'] or '', r['id']))[0]
        cards.append({'node_id': nid, 'title': n['title'], 'mastery': n['mastery'],
                      'learning_status': n['learning_status'], 'review_item_id': r['id'],
                      'schedule_ids': [r['id'] for r in rows], 'next_due': r['next_due'],
                      'kind': 'due' if due else 'unknown'})
    ordered = sorted(cards, key=lambda c: (c['kind'] != 'due', c['next_due'] or '', c['title']))
    return {'date': day, 'cap': _limit(limit, 15), 'total': len(ordered), 'items': ordered[:_limit(limit, 15)]}
