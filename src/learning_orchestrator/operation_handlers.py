"""Operation adapters call domain code, never public compatibility wrappers."""
from . import context, curricula, learning_records, production, question_batch
from . import review_batches, review_graph, review_views, teaching
from .graph import ValidationError


def _plain_prepare(orch, scope, inputs):
    return {}, {}


def _content_prepare(orch, scope, inputs, operation, strategy_id=None):
    task = production.prepare(orch, operation, scope['node_ids'], profile=scope.get('profile'),
        strategy_id=strategy_id, goal=inputs.get('goal', ''), materials=inputs.get('materials'),
        project_id=scope.get('project_id'), teaching_item_id=scope.get('teaching_item_id'))
    return task['context'], {'content_ticket': task['ticket'], 'content_instructions': task['instructions']}


def _context_prepare(orch, scope, inputs):
    targets = []
    for nid in scope.get('node_ids', []):
        if orch.conn.execute('SELECT 1 FROM nodes WHERE id=?', (nid,)).fetchone():
            targets.append(context.build_context_pack(orch.conn, nid, 'intro'))
        else:
            targets.append(review_views.detail(orch.conn, nid, scope.get('project_id')))
    return {'selected_material': targets}, {}


def _plan_prepare(orch, scope, inputs):
    return {'current': teaching.get_state(orch.conn, scope['course_id'])}, {}


def _graph_prepare(orch, scope, inputs):
    targets = [dict(node=review_graph._node(orch.conn, nid),
                    body=review_views.detail(orch.conn, nid, scope.get('project_id'))['body'])
               for nid in scope.get('node_ids', [])]
    mentions = [n['node']['title'] for n in targets]
    from .flow_steps import view
    for target in targets:
        if target['node']['kind'] == 'flow':
            structure = view(orch.conn, target['node']['id'], scope.get('project_id'), 0)
            target['flow_structure'] = {k: structure[k] for k in ('steps', 'connections')}
    return dict(targets=targets, existing_candidates=review_graph.resolve(
        orch.conn, mentions, scope.get('project_id'), 5) if mentions else [],
        method='Read selected prose; resolve candidate identities before judging semantic relations. '
               'Use resolve_review_mentions for newly found concepts. Candidates are not automatic matches.'), {}


def _learning_prepare(orch, scope, inputs):
    offset = inputs.get('offset', 0)
    sid = scope.get('section_id')
    if inputs.get('source_ref', '').startswith('doc-') and 'offset' not in inputs and sid:
        import json
        from .learning_records import _digest
        row = orch.conn.execute("SELECT json_extract(payload,'$.record_analysis') FROM teaching_updates "
            "WHERE course_id=? AND section_id=? AND json_extract(payload,'$.record_analysis.source_ref')=? "
            "ORDER BY id DESC LIMIT 1", (scope['course_id'], sid, inputs['source_ref'])).fetchone()
        if row:
            previous, text = json.loads(row[0]), inputs.get('transcript', '')
            end = int(previous.get('processed_chars') or 0)
            prefix = previous.get('prefix_fingerprint') or previous.get('fingerprint')
            if end <= len(text) and prefix == _digest(text[:end]):
                offset = end
    record = learning_records.prepare(orch.conn, orch.source_roots, scope['course_id'],
        scope.get('section_id'), inputs.get('path'), inputs.get('transcript'),
        inputs.get('source_ref'), offset, inputs.get('max_chars', 10000))
    scope['section_id'] = record['section_id']
    return {'record': record}, {}


def _review_record_prepare(orch, scope, inputs):
    _batch_scope(orch, scope)
    record = review_batches.prepare_record(orch.conn, scope['batch_id'], inputs.get('transcript', ''),
                                           inputs.get('source_key', 'pasted-chat'), inputs.get('max_chars', 10000))
    return {'record': record}, {}


def _curriculum_commit(orch, request_id, scope, artifact, ticket):
    return curricula.register(orch.conn, request_id, course_id=scope['course_id'], **artifact)


def _plan_commit(orch, request_id, scope, artifact, ticket):
    return teaching.save_plan(orch.conn, scope['course_id'], scope['section_id'],
        artifact['milestones'], artifact.get('created_by', 'main'), artifact.get('stage_key'))


def _context_commit(orch, request_id, scope, artifact, ticket):
    return {'material_bundle': artifact}


def _content_commit(orch, request_id, scope, artifact, ticket):
    return production.commit(orch, request_id=request_id, ticket=ticket['content_ticket'], **artifact)


def _learning_commit(orch, request_id, scope, artifact, ticket):
    return learning_turn(orch, course_id=scope['course_id'], section_id=scope['section_id'],
        role=artifact.get('role', 'detail'), record_analysis=artifact['analysis'],
        items_add=artifact.get('items_add'), items_update=artifact.get('items_update'),
        turn_record=artifact.get('turn_record'), **artifact.get('position', {}))


def learning_turn(orch, **data):
    """Shared write for historical direct tutoring and imported record analysis."""
    return teaching.commit(orch.conn, **data)


def _review_record_commit(orch, request_id, scope, artifact, ticket):
    _batch_scope(orch, scope)
    return review_batches.commit_record(orch.conn, request_id, scope['batch_id'], **artifact)


def _assessment_commit(orch, request_id, scope, artifact, ticket):
    if scope.get('project_id'):
        for item in artifact.get('assessments', []) + artifact.get('recall_results', []):
            eid = item.get('context_edge_id')
            row = orch.conn.execute('SELECT context_project_id FROM review_graph_edges WHERE id=?',
                                    (eid,)).fetchone() if eid else None
            if not row or row['context_project_id'] != scope['project_id']:
                raise ValidationError('Project assessment needs a context_edge_id in this project')
    return review_graph.assess(orch.conn, request_id, **artifact)


def _graph_commit(orch, request_id, scope, artifact, ticket):
    return review_graph.commit(orch.conn, request_id, project_id=scope.get('project_id'), **artifact)


def _questions_commit(orch, request_id, scope, artifact, ticket):
    return question_batch.commit(orch.conn, request_id, **artifact)


def _review_commit(orch, request_id, scope, artifact, ticket):
    return review_batches.save(orch.conn, request_id, batch_id=scope['batch_id'],
                               project_id=scope.get('project_id'), **artifact)


def _batch_scope(orch, scope):
    if scope.get('project_id'):
        row = orch.conn.execute('SELECT project_id FROM review_batches WHERE id=?',
                                (scope['batch_id'],)).fetchone()
        if not row or row['project_id'] != scope['project_id']:
            raise ValidationError('Review batch does not belong to this project')


PREPARERS = {'curriculum': _plain_prepare, 'plan': _plan_prepare, 'context': _context_prepare,
    'content': _content_prepare, 'learning': _learning_prepare, 'review_record': _review_record_prepare,
    'assessment': _plain_prepare, 'graph': _graph_prepare, 'questions': _plain_prepare,
    'review': _plain_prepare}
COMMITTERS = {'curriculum': _curriculum_commit, 'plan': _plan_commit, 'context': _context_commit,
    'content': _content_commit, 'learning': _learning_commit, 'review_record': _review_record_commit,
    'assessment': _assessment_commit, 'graph': _graph_commit, 'questions': _questions_commit,
    'review': _review_commit}
