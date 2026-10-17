"""Read-only review projections. Never derive proficiency from teaching activity."""
import json
from . import review_graph, question_links, content


def catalog(conn,project_id=None):
    nodes = []
    open_counts, scoped_counts = {}, {}
    if question_links.exists(conn, 'review_batch_gaps'):
        for row in conn.execute("SELECT g.node_id,b.project_id,COUNT(*) AS n FROM review_batch_gaps g "
                                "JOIN review_batches b ON b.id=g.batch_id WHERE g.state!='resolved' "
                                "AND g.node_id IS NOT NULL GROUP BY g.node_id,b.project_id"):
            scoped_counts[(row['node_id'], row['project_id'])] = row['n']
            open_counts[row['node_id']] = open_counts.get(row['node_id'], 0) + row['n']
    links=question_links.index(conn)
    counts=question_links.counts(conn,links,project_id)
    for row in conn.execute('SELECT id,payload FROM review_graph_nodes'):
        n = json.loads(row['payload'])
        if not n.get('kind'):
            continue
        n['id'] = row['id']
        # Metadata only: bodies, history and teaching state do not enter this response.
        n = {k: n[k] for k in ('id','kind','title','summary','owner_ref','domains','content_ref','provenance') if k in n}
        n.update(review_graph._assessed(conn, row['id']))
        n['question_count'] = counts.get(row['id'],0)
        n['direct_question_count'] = len(links.get(row['id'],{}))
        n['open_gap_count'] = open_counts.get(row['id'], 0)
        nodes.append(n)
    edges = []
    for row in conn.execute('SELECT * FROM review_graph_edges'):
        e = dict(row)
        e['payload'] = json.loads(e['payload'])
        e['assessment'] = review_graph._assessed(conn, e['to_id'], e['id']) if e['relation']=='uses' else {}
        e['open_gap_count'] = scoped_counts.get((e['to_id'], e['context_project_id']), 0)
        edges.append(e)
    by_id = {n['id']: n for n in nodes}
    parents, children = {}, {}
    for edge in edges:
        if edge['relation'] == 'contains':
            parents.setdefault(edge['to_id'], []).append(edge['from_id'])
            children.setdefault(edge['from_id'], []).append(edge['to_id'])
    for n in nodes:
        if n['kind'] != 'flow':
            continue
        scope, todo, seen = project_id, [n['id']], set()
        while not scope and todo:
            current = todo.pop()
            if current in seen:
                continue
            seen.add(current)
            if by_id.get(current, {}).get('kind') == 'project':
                scope = current
                break
            todo.extend(parents.get(current, []))
        steps = [nid for nid in children.get(n['id'], []) if by_id.get(nid, {}).get('kind') == 'step']
        n['question_count'] = len(question_links.resolve(conn, [n['id']] + steps, scope, links))
    return {'nodes': nodes, 'edges': edges}


def detail(conn, node_id,project_id=None,top_k=5):
    node_id = review_graph._canonical(conn, node_id)
    n = review_graph._node(conn, node_id)
    resolved = content.resolve(conn, n.get('content_ref'))
    relations = {'uses': [], 'requires': [], 'next': [], 'fails_to': [], 'previous': [],
                 'supports': [], 'supported_by': []}
    sql = 'SELECT * FROM review_graph_edges WHERE (from_id=? OR to_id=?)'
    args = [node_id, node_id]
    if project_id:
        project_id = review_graph._canonical(conn, project_id)
        sql += " AND context_project_id IN ('',?)"
        args.append(project_id)
    for row in conn.execute(sql + ' ORDER BY id', args):
        e = dict(row)
        outgoing = e['from_id'] == node_id
        key = e['relation'] if outgoing else {'next': 'previous', 'supports': 'supported_by'}.get(e['relation'])
        if key not in relations:
            continue
        target_id = e['to_id'] if outgoing else e['from_id']
        target = review_graph._node(conn, target_id)
        e['payload'] = json.loads(e['payload'])
        e['target'] = {k: target.get(k) for k in ('id', 'kind', 'title', 'domains', 'content_ref')}
        e['general_assessment'] = review_graph._assessed(conn, target_id)
        e['assessment'] = review_graph._assessed(conn, target_id, e['id']) if key == 'uses' else {}
        relations[key].append(e)
    structure = None
    if n['kind'] == 'flow':
        from .flow_steps import view
        structure = view(conn, node_id, project_id, top_k)
    questions = structure['direct_questions'] if structure else question_links.questions_for_node(conn,node_id,project_id)
    for q in questions:
        row = None
        if question_links.exists(conn, 'review_question_attempts'):
            row = conn.execute("SELECT result,gap_note,created_at AS judged_at FROM review_question_attempts "
                "WHERE question_id=? AND project_id=? AND kind='answer' AND result IS NOT NULL ORDER BY rowid DESC LIMIT 1",
                (q['id'], project_id or '')).fetchone()
        if row is None:
            legacy = conn.execute('SELECT result,gap_note,judged_at FROM question_judgments WHERE question_id=? ORDER BY judged_at DESC,id DESC LIMIT 1', (q['id'],)).fetchone()
            if project_id:
                q['historical_judgment'] = dict(legacy) if legacy else None
            else:
                row = legacy
        q['judgment'] = dict(row) if row else None
    pending={r['question_id']:r['reason'] for r in conn.execute('SELECT question_id,reason FROM question_link_pending')} if question_links.exists(conn,'question_link_pending') else {}
    for q in questions:q['pending_reason']=pending.get(q['id'],'')
    gaps = []
    if question_links.exists(conn, 'review_batch_gaps'):
        gap_sql = ("SELECT g.*,b.title AS batch_title FROM review_batch_gaps g JOIN review_batches b "
                   "ON b.id=g.batch_id WHERE g.node_id=? AND g.state!='resolved'")
        gap_args = [node_id]
        if project_id:
            gap_sql += ' AND b.project_id=?'
            gap_args.append(project_id)
        gaps = [dict(r) for r in conn.execute(gap_sql, gap_args)]
    return {**resolved, 'id': node_id, 'project_id': project_id,
            'relations': relations, 'questions': questions, 'gaps': gaps,
            'question_scope':'direct_and_contained' if len(question_links.scope_nodes(conn,node_id))>1 else 'direct',
            'direct_question_count':sum(node_id in q['node_ids'] for q in questions),
            'pending_inventory_count':len(pending), 'flow_structure':structure}
