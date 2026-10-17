"""Resolve stored content references for reading, review and export.

This module never manufactures a body from a node summary and never writes
learning state. References remain owned by the existing knowledge/graph stores.
"""
import json
from . import review_graph
from .db import transaction
from .graph import ValidationError


def resolve(conn, ref, _seen=None):
    ref = ref or {}
    result = {'body': '', 'block_id': None, 'point': None,
              'synthesis_id': None, 'content_ref': ref}
    typ, rid = ref.get('type'), ref.get('id')
    if typ == 'knowledge_point':
        # Explicit legacy bindings let a point move to a different block without
        # rewriting every old source/question link. Only follow registered graph
        # identities, never title similarity.
        canonical = review_graph._canonical(conn, rid)
        registered = conn.execute('SELECT payload FROM review_graph_nodes WHERE id=?', (canonical,)).fetchone()
        redirect = json.loads(registered[0]).get('content_ref') if registered else None
        key = review_graph._json(ref)
        seen = set(_seen or ())
        if redirect and redirect != ref and key not in seen:
            return resolve(conn, redirect, seen | {key})
        row = conn.execute('SELECT * FROM knowledge_point_index WHERE id=?', (rid,)).fetchone()
        if row is None or not row['active']:
            return result
        result['point'] = dict(row)
        result['block_id'] = row['block_id']
    elif typ == 'knowledge_block':
        result['block_id'] = rid
    if result['block_id']:
        row = conn.execute('SELECT id,content FROM knowledge_syntheses WHERE block_id=? '
                           'ORDER BY id DESC LIMIT 1', (result['block_id'],)).fetchone()
        if row:
            result['synthesis_id'], result['body'] = row['id'], row['content']
            point = result['point']
            if point:
                result['body'] = '\n'.join(result['body'].splitlines()[point['start_line']:point['end_line']])
    elif typ == 'source_anchor':
        row = conn.execute('SELECT text FROM chunks WHERE source_id=? AND anchor=? ORDER BY id LIMIT 1',
                           (rid, ref.get('anchor', ''))).fetchone()
        if row:
            result['body'] = row['text']
    elif typ == 'lesson':
        # A lesson is read only when explicitly referenced; never substitute a
        # historical lesson merely because the formal project body is absent.
        row = conn.execute('SELECT content FROM lesson_artifacts WHERE node_id=? AND mode=?',
                           (rid, ref.get('mode', 'intro'))).fetchone()
        if row:
            result['body'] = row['content']
        elif ref.get('mode', 'intro') == 'intro' and conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='generated_lessons'").fetchone():
            row = conn.execute('SELECT content FROM generated_lessons WHERE node_id=? ORDER BY id DESC LIMIT 1',
                               (rid,)).fetchone()
            if row:
                result['body'] = row['content']
    return result


def for_node(conn, node_id):
    node = review_graph._node(conn, node_id)
    return dict(resolve(conn, node.get('content_ref')), node_id=node['id'])


def relocate(conn, request_id, node_id, target_ref, owner_ref=None):
    """Switch the formal location/maintenance owner, keeping graph and schedule IDs.

    Target content is prepared separately. Old bodies/history are retained.
    """
    payload = dict(node_id=node_id, target_ref=target_ref, owner_ref=owner_ref)
    digest, previous = review_graph._request(conn, request_id, 'content.relocate', payload)
    if previous is not None:
        return previous
    node = review_graph._node(conn, node_id)
    if target_ref.get('type') not in ('knowledge_block', 'knowledge_point', 'source_anchor', 'lesson'):
        raise ValidationError('Unsupported formal content reference')
    if not resolve(conn, target_ref)['body']:
        raise ValidationError('The new formal content must be readable before relocating')
    old_ref = node.get('content_ref')
    with transaction(conn):
        update = {'id': node['id'], 'content_ref': target_ref, 'content_state': 'linked'}
        if owner_ref is not None:
            update['owner_ref'] = owner_ref
        review_graph.commit(conn, request_id + ':node', nodes=[update])
        if old_ref and old_ref.get('type') == 'knowledge_point' and old_ref['id'] != node['id']:
            review_graph._bind(conn, 'node', '', old_ref['id'], node['id'])
        if not for_node(conn, node['id'])['body']:
            raise ValidationError('Relocated content cannot be read')
        return review_graph._receipt(conn, request_id, 'content.relocate', digest,
            {'success': True, 'node_id': node['id'], 'previous_ref': old_ref, 'content_ref': target_ref})
