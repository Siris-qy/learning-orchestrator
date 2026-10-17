"""Authored flow steps reuse graph identities, knowledge and question stores."""
from . import review_graph, question_links
from .graph import ValidationError


def expand(conn, flows, project_id=None, pending_nodes=None):
    nodes, edges = [], []
    pending = {n['id']: n for n in pending_nodes or [] if n.get('id')}
    def node(nid):
        if nid in pending:
            return pending[nid]
        return review_graph._node(conn, nid)
    for flow in flows or []:
        fid = review_graph._canonical(conn, flow['flow_id'])
        if node(fid)['kind'] != 'flow':
            raise ValidationError('Steps must belong to a flow: ' + fid)
        identifiers = [s['id'] for s in flow['steps']]
        if len(identifiers) != len(set(identifiers)):
            raise ValidationError('Step IDs must be distinct within a flow')
        for index, step in enumerate(flow['steps']):
            if not step.get('title') or not step.get('description'):
                raise ValidationError('A step needs title and description')
            existing = conn.execute('SELECT 1 FROM review_graph_nodes WHERE id=?', (step['id'],)).fetchone()
            if existing and review_graph._node(conn, step['id'])['kind'] != 'step':
                raise ValidationError('Step ID already identifies another kind of node')
            old_parent = conn.execute("SELECT from_id FROM review_graph_edges WHERE to_id=? "
                "AND relation='contains' AND from_id!=?", (step['id'], fid)).fetchone()
            if old_parent:
                raise ValidationError('Step already belongs to another flow')
            nodes.append(dict(id=step['id'], kind='step', title=step['title'], summary=step['description'],
                              owner_ref={'type': 'flow', 'id': fid}))
            edges.append(dict(from_id=fid, to=step['id'], relation='contains', seq=index))
            for use in step.get('knowledge', []):
                nid = review_graph._canonical(conn, use['node_id'])
                if node(nid)['kind'] != 'knowledge':
                    raise ValidationError('A step knowledge reference must identify a knowledge node')
                edges.append(dict(from_id=step['id'], to=nid, relation='uses',
                    **{k: use[k] for k in ('usage', 'used_parts', 'required_depth') if k in use}))
        connections = flow.get('connections')
        if connections is None:
            connections = [{'from': a, 'to': b, 'relation': 'next'} for a, b in zip(identifiers, identifiers[1:])]
        for connection in connections:
            if (connection['from'] not in identifiers or connection['to'] not in identifiers
                    or connection.get('relation', 'next') not in ('next', 'fails_to')):
                raise ValidationError('Step connections must link steps in this flow')
            edges.append(dict(from_id=connection['from'], to=connection['to'],
                relation=connection.get('relation', 'next'), conditions=connection.get('conditions', '')))
    return nodes, [dict({'from': e.pop('from_id')}, **e) for e in edges]


def view(conn, flow_id, project_id=None, top_k=5):
    def scope_ok(e):
        return not project_id or e['context_project_id'] in ('', project_id)
    steps = []
    scoped_edges = review_graph._edges(conn, project_id)
    containment = {}
    for edge in scoped_edges:
        if edge['from'] != flow_id or edge['relation'] != 'contains':
            continue
        previous = containment.get(edge['to'])
        if not previous or edge.get('context_project_id') == project_id:
            containment[edge['to']] = edge
    for edge in containment.values():
        n = review_graph._node(conn, edge['to'])
        if n['kind'] != 'step':
            continue
        uses = []
        for row in conn.execute("SELECT * FROM review_graph_edges WHERE from_id=? AND relation='uses'", (n['id'],)):
            if not scope_ok(row):
                continue
            import json
            knowledge = review_graph._node(conn, row['to_id'])
            uses.append(dict(edge_id=row['id'], node_id=knowledge['id'], title=knowledge['title'],
                usage=json.loads(row['payload']).get('usage', ''),
                general_assessment=review_graph._assessed(conn, knowledge['id']),
                assessment=review_graph._assessed(conn, knowledge['id'], row['id'])))
        steps.append(dict(id=n['id'], title=n['title'], description=n['summary'], seq=edge.get('seq', 0), knowledge=uses))
    steps.sort(key=lambda s: (s['seq'], s['id']))
    ids = {s['id'] for s in steps}
    connections = [e for e in scoped_edges
                   if e['from'] in ids and e['to'] in ids and e['relation'] in ('next', 'fails_to')]
    index = question_links.index(conn)
    import json
    project_ids = set()
    for row in conn.execute('SELECT id,payload FROM review_graph_nodes'):
        n = json.loads(row['payload'])
        owner = n.get('owner_ref') or {}
        from . import curricula
        course_is_project = owner.get('type') == 'course' and curricula.kind(conn, owner.get('id', row['id'])) == 'project'
        if n.get('kind') == 'project' and owner.get('type') != 'knowledge_system' and (owner.get('type') != 'course' or course_is_project):
            project_ids.add(row['id'])
            if owner.get('type') == 'project' and owner.get('id'):
                project_ids.add(owner['id'])
    project_questions = {r['id'] for r in conn.execute('SELECT id,course_id FROM questions')
                         if r['course_id'] in project_ids}
    direct = question_links.resolve(conn, [flow_id] + list(ids), project_id, index)
    direct_ids = {q['id'] for q in direct}
    associated = {}
    knowledge_refs = [(u['node_id'], s['id']) for s in steps for u in s['knowledge']]
    # With authored steps, previews follow those exact references. A legacy
    # broad flow-level link (e.g. fd) must not flood the step preview with all
    # unrelated networking questions. Old flows keep their flow-level preview.
    if not steps:
        for e in scoped_edges:
            if e['from'] == flow_id and e['relation'] == 'uses':
                knowledge_refs.append((e['to'], None))
    for nid, sid in knowledge_refs:
        for q in question_links.questions_for_node(conn, nid, links=index):
            # Preview public knowledge questions only, not another project's
            # contextual question simply linked to the same reusable node.
            public = [c for c in q['contexts'] if not c.get('project_id')]
            if q['id'] in direct_ids or q['id'] in project_questions or not public:
                continue
            item = associated.setdefault(q['id'], dict(q, contexts=public, knowledge_refs=[]))
            ref = dict(node_id=nid, title=review_graph._node(conn, nid)['title'], step_id=sid)
            if ref not in item['knowledge_refs']:
                item['knowledge_refs'].append(ref)
    previews = sorted(associated.values(), key=lambda q: (q.get('level') != 'firsthand', q['id']))
    return dict(steps=steps, connections=connections, direct_questions=direct,
                knowledge_question_count=len(previews), knowledge_questions=previews[:max(0, min(20, int(top_k)))])
