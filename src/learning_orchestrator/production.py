"""Prepare bounded AI jobs and publish their artifacts through the existing stores.

Strategies choose a method and material; the host AI produces the prose. Custom
Python strategies can be registered without changing storage or page readers.
"""
import hashlib
import json

from . import content, knowledge, review_graph
from .db import transaction
from .graph import ValidationError

CONTRACT = 'lo.content.v1'
STRATEGIES = {}


def setup(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS generated_lessons(
      id INTEGER PRIMARY KEY, node_id TEXT NOT NULL REFERENCES review_graph_nodes(id),
      content TEXT NOT NULL, request_id TEXT NOT NULL, created_at TEXT NOT NULL)''')


def lesson(conn, node_id):
    row = conn.execute('SELECT content,created_at FROM generated_lessons WHERE node_id=? '
                       'ORDER BY id DESC LIMIT 1', (node_id,)).fetchone()
    return dict(row) if row else None


def register_strategy(strategy_id, operation, profile, instructions, prepare=None):
    """A prepare hook receives a JSON context and returns a JSON material bundle.

    It runs only for the selected strategy. It cannot replace publication rules.
    Hosts may register their own strategies during application startup.
    """
    if operation not in ('note', 'lesson') or not strategy_id or not instructions:
        raise ValidationError('A strategy needs id, note/lesson operation and instructions')
    STRATEGIES[strategy_id] = dict(id=strategy_id, operation=operation,
        profile=profile, instructions=instructions, prepare=prepare)


register_strategy('project.note', 'note', 'project',
    '写给复盘项目的人：先交代模块的位置、目的和输入输出，再沿正常通路解释各步怎样衔接、'
    '为何需要关键机制，并在对应步骤解释主要失败分支。用一个具体输入贯穿，按需配短代码。'
    '正文要能独立读懂；公共知识引用已有节点，项目用法写在本模块。标题随内容安排。')
register_strategy('course.note', 'note', 'course',
    '根据选定教材/slide及实际学习记录整理本小节。解释概念、因果和一个有帮助的例子，'
    '保留课程边界、必要公式或代码。知识正文与学习过程分开；引用已有公共知识身份。')
register_strategy('project.lesson', 'lesson', 'project',
    '为看不到仓库的网页AI准备自包含教案：项目目标、当前模块位置、输入输出、最小核心实现、'
    '分段讲解提纲和回到实际实现的对应。嵌入必需代码及背景，链接只作来源，不依赖本地路径。'
    '按内容量分批，教案小节数由材料决定。')
register_strategy('course.lesson', 'lesson', 'course',
    '按本次教材/slide范围准备自包含教案：本节目标、必要前置、自然分段的完整解释、'
    '例子及已提供的教材练习索引。网页AI不应需要打开本地教材。不要把生成教案当成已学习。')


def strategies():
    return [{k: s[k] for k in ('id', 'operation', 'profile', 'instructions')}
            for s in STRATEGIES.values()]


def _hash(value):
    return hashlib.sha256(review_graph._json(value).encode('utf-8')).hexdigest()


def _snapshot(conn, node_id, operation, teaching_item_id=None):
    node = review_graph._node(conn, node_id)
    if operation == 'lesson':
        if teaching_item_id is not None:
            row = conn.execute("SELECT json_extract(payload,'$.lesson_artifact.content') FROM teaching_updates "
                "WHERE section_id=? AND json_extract(payload,'$.lesson_artifact.item_id')=? "
                "AND json_extract(payload,'$.lesson_artifact.mode')='intro' ORDER BY id DESC LIMIT 1",
                (node_id, teaching_item_id)).fetchone()
        elif conn.execute('SELECT 1 FROM nodes WHERE id=?', (node_id,)).fetchone():
            row = conn.execute("SELECT content FROM lesson_artifacts WHERE node_id=? AND mode='intro'",
                               (node_id,)).fetchone()
        else:
            row = conn.execute('SELECT content FROM generated_lessons WHERE node_id=? ORDER BY id DESC LIMIT 1',
                               (node_id,)).fetchone()
        body = row[0] if row else ''
        return node, body, _hash([node.get('title'), body])
    resolved = content.for_node(conn, node_id)
    additions = []
    if resolved['block_id']:
        additions = [tuple(r) for r in conn.execute(
            'SELECT id,content FROM knowledge_entries WHERE block_id=? ORDER BY rowid',
            (resolved['block_id'],))]
    return node, resolved['body'], _hash([node.get('content_ref'), resolved['body'], additions])


def prepare(orch, operation, node_ids, profile=None, strategy_id=None,
            goal='', materials=None, project_id=None, teaching_item_id=None):
    if profile is None:
        node = review_graph._node(orch.conn, node_ids[0]) if node_ids else {}
        owner = node.get('owner_ref') or {}
        root = orch.conn.execute('SELECT payload FROM review_graph_nodes WHERE id=?',
                                (owner.get('id') or project_id,)).fetchone()
        project_owner = root and json.loads(root[0]).get('kind') == 'project'
        if owner.get('type') == 'knowledge_system':
            profile = 'course'
        elif owner.get('type') == 'course':
            from . import curricula
            profile = curricula.kind(orch.conn, owner['id'])
        else:
            profile = 'project' if project_id or project_owner or node.get('kind') in ('flow', 'module', 'project') else 'course'
    strategy_id = strategy_id or profile + '.' + operation
    strategy = orch._strategies.select(strategy_id, operation + '.publish', profile)
    if not node_ids or len(set(node_ids)) != len(node_ids):
        raise ValidationError('Provide distinct target node_ids')
    targets, versions = [], {}
    for node_id in node_ids:
        node, body, version = _snapshot(orch.conn, node_id, operation, teaching_item_id)
        if operation == 'lesson' and (teaching_item_id is not None or orch.conn.execute(
                'SELECT 1 FROM nodes WHERE id=?', (node_id,)).fetchone()):
            orch._lesson_key(node_id, 'intro', teaching_item_id)
        versions[node['id']] = version
        targets.append({'node_id': node['id'], 'title': node['title'],
                        'kind': node['kind'], 'body': body,
                        'content_ref': node.get('content_ref')})
        if operation == 'lesson':
            formal = content.for_node(orch.conn, node['id'])
            if formal['body'] and formal['body'] != body:
                targets[-1]['formal_material'] = dict(body=formal['body'],
                    content_ref=formal['content_ref'], synthesis_id=formal['synthesis_id'])
        if node['kind'] == 'flow':
            from .flow_steps import view
            structure = view(orch.conn, node['id'], project_id, top_k=0)
            targets[-1]['flow_structure'] = {k: structure[k] for k in ('steps', 'connections')}
    if project_id:
        review_graph._node(orch.conn, project_id)
    context = dict(goal=goal, targets=targets, materials=materials or [], project_id=project_id,
                   scope=dict(node_ids=node_ids, project_id=project_id, profile=profile),
                   state={}, missing=[])
    if strategy['prepare']:
        context = strategy['prepare'](context)
        json.dumps(context)  # Extensions keep the same transport contract.
    return {'contract': CONTRACT, 'ticket': {
        'contract': CONTRACT, 'operation': operation, 'strategy_id': strategy_id,
        'project_id': project_id, 'versions': versions, 'teaching_item_id': teaching_item_id},
        'instructions': strategy['instructions'], 'context': context,
        'output': {'documents': [{'node_id': 'existing target ID', 'body': 'complete Markdown',
                                  'source_refs': [], 'area': 'other'}],
                   'edges': 'optional existing graph edges',
                   'question_links': 'optional existing question IDs and scope'}}


def commit(orch, request_id, ticket, documents, edges=None, question_links=None, flow_steps=None):
    """Publish bodies + graph references atomically; never assess or move cursors."""
    conn = orch.conn
    payload = dict(ticket=ticket, documents=documents, edges=edges or [],
                   question_links=question_links or [])
    if flow_steps:
        payload['flow_steps'] = flow_steps
    digest, previous = review_graph._request(conn, request_id, 'content.publish', payload)
    if previous is not None:
        return previous
    if ticket.get('contract') != CONTRACT or ticket.get('operation') not in ('note', 'lesson'):
        raise ValidationError('Unsupported content contract')
    operation = ticket['operation']
    if operation == 'lesson' and (edges or question_links or flow_steps):
        raise ValidationError('Lesson publication does not modify formal graph links')
    strategy = orch._strategies.select(ticket['strategy_id'], operation + '.publish')
    if strategy.get('transform'):
        from .operation_contracts import get, validate
        source = dict(documents=documents, edges=edges or [], question_links=question_links or [])
        if flow_steps:
            source['flow_steps'] = flow_steps
        transformed = strategy['transform'](source)
        if operation == 'lesson':
            transformed = {k: v for k, v in transformed.items() if k == 'documents' or v}
        validate(transformed, get(operation + '.publish')['artifact_schema'], 'artifact')
        documents = transformed['documents']
        edges, question_links = transformed.get('edges'), transformed.get('question_links')
        flow_steps = transformed.get('flow_steps')
    versions = ticket.get('versions', {})
    ids = [d['node_id'] for d in documents]
    if not ids or len(set(ids)) != len(ids) or any(i not in versions for i in ids):
        raise ValidationError('Documents must identify distinct prepared targets')
    published = []
    with transaction(conn):
        for d in documents:
            node, old_body, version = _snapshot(conn, d['node_id'], operation, ticket.get('teaching_item_id'))
            if version != versions[d['node_id']]:
                raise ValidationError('Content changed since preparation: ' + d['node_id'])
            body = d.get('body', '')
            if not isinstance(body, str) or not body.strip():
                raise ValidationError('A published document needs a nonempty body')
            if operation == 'lesson':
                if conn.execute('SELECT 1 FROM nodes WHERE id=?', (node['id'],)).fetchone():
                    receipt = orch.save_lesson_artifact(node['id'], 'intro', body,
                                                       teaching_item_id=ticket.get('teaching_item_id'))
                else:
                    from .graph import now_iso
                    review_graph._ensure(conn, node['id'])
                    row = conn.execute('INSERT INTO generated_lessons(node_id,content,request_id,created_at) '
                                       'VALUES(?,?,?,?)', (node['id'], body, request_id, now_iso()))
                    receipt = {'saved': True, 'lesson_id': row.lastrowid}
                published.append({'node_id': node['id'], 'lesson': receipt})
                continue
            ref = node.get('content_ref') or {}
            if ref.get('type') == 'knowledge_point':
                raise ValidationError('Edit the containing knowledge block, not a partial point as a whole body')
            block_id = ref['id'] if ref.get('type') == 'knowledge_block' else 'review-body:' + node['id']
            entry_id = 'publish-' + _hash([request_id, node['id']])
            knowledge.append(conn, block_id, node['title'], node['title'], body,
                area=d.get('area', 'other'), source_refs=d.get('source_refs', []), entry_id=entry_id)
            last = conn.execute('SELECT covered_entries FROM knowledge_syntheses '
                                'WHERE block_id=? ORDER BY id DESC LIMIT 1', (block_id,)).fetchone()
            # Unmerged contributions remain additions unless the producer
            # explicitly included them; publishing is not an implicit cleanup.
            covered = list(set((json.loads(last[0]) if last else []) +
                               d.get('covered_entry_ids', []) + [entry_id]))
            synthesis = knowledge.consolidate(conn, block_id, body, covered)
            update = {'id': node['id'], 'content_ref': {'type': 'knowledge_block', 'id': block_id},
                      'content_state': 'linked'}
            if node['kind'] == 'knowledge' and not node.get('domains') and d.get('area'):
                update['domains'] = review_graph._domain(d['area'])
            review_graph.commit(conn, request_id + ':node:' + node['id'], nodes=[update])
            if content.for_node(conn, node['id'])['body'] != body:
                raise ValidationError('Published body could not be read back')
            published.append({'node_id': node['id'], 'block_id': block_id,
                              'synthesis_id': synthesis['synthesis_id']})
        if edges or question_links or flow_steps:
            review_graph.commit(conn, request_id + ':links', project_id=ticket.get('project_id'),
                                edges=edges, question_links=question_links, flow_steps=flow_steps)
        return review_graph._receipt(conn, request_id, 'content.publish', digest,
            {'success': True, 'request_id': request_id, 'published': published})
