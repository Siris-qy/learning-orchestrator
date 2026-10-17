"""Ordered original-question batches, external records and explicit local gaps.

Questions retain their identity; knowledge retains its existing review schedule.
The host AI matches unlabelled transcripts and judges actual answers. This store
does not infer confirmation from an explanation or completion from a good answer.
"""
import hashlib
import json

from . import content, review_graph
from .db import transaction
from .graph import ValidationError, now_iso


def setup(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS review_batches(
      id TEXT PRIMARY KEY, project_id TEXT NOT NULL DEFAULT '', title TEXT NOT NULL,
      source_ref TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS review_batch_items(
      batch_id TEXT NOT NULL REFERENCES review_batches(id),
      question_id TEXT NOT NULL REFERENCES questions(id), seq INTEGER NOT NULL,
      label TEXT NOT NULL, node_ids TEXT NOT NULL DEFAULT '[]',
      PRIMARY KEY(batch_id,question_id));
    CREATE TABLE IF NOT EXISTS review_question_attempts(
      id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES review_batches(id),
      question_id TEXT NOT NULL REFERENCES questions(id), project_id TEXT NOT NULL,
      kind TEXT NOT NULL, answer TEXT NOT NULL, result TEXT,
      gap_note TEXT NOT NULL DEFAULT '', coverage TEXT NOT NULL DEFAULT '[]',
      source_ref TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS review_batch_gaps(
      id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES review_batches(id),
      question_id TEXT REFERENCES questions(id), node_id TEXT, parent_id TEXT,
      title TEXT NOT NULL, state TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
      updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS review_record_offsets(
      batch_id TEXT NOT NULL REFERENCES review_batches(id), source_key TEXT NOT NULL,
      offset INTEGER NOT NULL, prefix_hash TEXT NOT NULL,
      PRIMARY KEY(batch_id,source_key));
    CREATE TABLE IF NOT EXISTS review_record_unmatched(
      id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES review_batches(id),
      payload TEXT NOT NULL);
    ''')


def _batch(conn, batch_id):
    row = conn.execute('SELECT * FROM review_batches WHERE id=?', (batch_id,)).fetchone()
    if row is None:
        raise ValidationError('Unknown review batch: ' + batch_id)
    return dict(row)


def save(conn, request_id, batch_id, title, items, project_id=None, source_ref=''):
    payload = dict(batch_id=batch_id, title=title, items=items,
                   project_id=project_id, source_ref=source_ref)
    digest, previous = review_graph._request(conn, request_id, 'review.batch', payload)
    if previous is not None:
        return previous
    if not batch_id or not title.strip() or not items:
        raise ValidationError('Batch id, title and original questions are required')
    with transaction(conn):
        if project_id:
            review_graph._node(conn, project_id)
        existing = conn.execute('SELECT project_id FROM review_batches WHERE id=?', (batch_id,)).fetchone()
        if existing and existing[0] != (project_id or ''):
            raise ValidationError('Batch project cannot change silently')
        conn.execute('INSERT INTO review_batches VALUES(?,?,?,?,?,?) ON CONFLICT(id) '
                     'DO UPDATE SET title=excluded.title,updated_at=excluded.updated_at',
                     (batch_id, project_id or '', title, source_ref, now_iso(), now_iso()))
        next_seq = conn.execute('SELECT COALESCE(MAX(seq),0) FROM review_batch_items '
                                'WHERE batch_id=?', (batch_id,)).fetchone()[0]
        for item in items:
            qid = item['question_id']
            if not conn.execute('SELECT 1 FROM questions WHERE id=?', (qid,)).fetchone():
                raise ValidationError('Unknown original question: ' + qid)
            node_ids = [review_graph._node(conn, n)['id'] for n in item.get('node_ids', [])]
            old = conn.execute('SELECT seq FROM review_batch_items WHERE batch_id=? AND question_id=?',
                               (batch_id, qid)).fetchone()
            next_seq += 1
            seq = item.get('seq', old[0] if old else next_seq)
            conn.execute('INSERT INTO review_batch_items VALUES(?,?,?,?,?) '
                         'ON CONFLICT(batch_id,question_id) DO UPDATE SET '
                         'label=excluded.label,node_ids=excluded.node_ids',
                         (batch_id, qid, seq, str(item.get('label', seq)), json.dumps(node_ids)))
        return review_graph._receipt(conn, request_id, 'review.batch', digest,
            {'success': True, 'batch_id': batch_id, 'question_count': conn.execute(
                'SELECT COUNT(*) FROM review_batch_items WHERE batch_id=?', (batch_id,)).fetchone()[0]})


def listing(conn, project_id=None):
    sql = ('SELECT b.*,COUNT(i.question_id) AS question_count FROM review_batches b '
           'LEFT JOIN review_batch_items i ON i.batch_id=b.id')
    args = []
    if project_id:
        sql += ' WHERE b.project_id=?'
        args.append(project_id)
    return [dict(r) for r in conn.execute(sql + ' GROUP BY b.id ORDER BY b.updated_at DESC,b.id', args)]


def read(conn, batch_id):
    batch = _batch(conn, batch_id)
    items = []
    for row in conn.execute('SELECT i.*,q.stem FROM review_batch_items i JOIN questions q '
                            'ON q.id=i.question_id WHERE i.batch_id=? ORDER BY i.seq,i.question_id', (batch_id,)):
        item = dict(row)
        item['node_ids'] = json.loads(item['node_ids'])
        item['nodes'] = []
        for nid in item['node_ids']:
            node = review_graph._node(conn, nid)
            item['nodes'].append({k: node.get(k) for k in ('id', 'kind', 'title')})
        item['attempts'] = []
        for attempt in conn.execute('SELECT * FROM review_question_attempts WHERE batch_id=? '
                                    'AND question_id=? ORDER BY rowid', (batch_id, item['question_id'])):
            a = dict(attempt)
            a['coverage'] = json.loads(a['coverage'])
            a['source_ref'] = json.loads(a['source_ref'])
            item['attempts'].append(a)
        items.append(item)
    batch['items'] = items
    batch['gaps'] = [dict(r) for r in conn.execute(
        'SELECT * FROM review_batch_gaps WHERE batch_id=? ORDER BY rowid', (batch_id,))]
    batch['unmatched'] = [dict(json.loads(r['payload']), id=r['id']) for r in conn.execute(
        "SELECT id,payload FROM review_record_unmatched WHERE batch_id=? "
        "AND COALESCE(json_extract(payload,'$.state'),'pending')!='resolved'", (batch_id,))]
    return batch


def export(conn, batch_id, node_ids=None, include_answers=False):
    batch = read(conn, batch_id)
    selected = node_ids if node_ids is not None else list(dict.fromkeys(
        nid for item in batch['items'] for nid in item['node_ids']))
    if batch['project_id'] and batch['project_id'] not in selected:
        selected = [batch['project_id']] + list(selected)
    sections = ['# ' + batch['title'],
        '本批为已有题目的复盘。先让学习者回答，再围绕具体缺口讨论；解释过与学习者确认分别记录。']
    missing, versions, structures = [], [], []
    for nid in selected:
        node = review_graph._node(conn, nid)
        resolved = content.for_node(conn, nid)
        body = resolved['body']
        if body:
            sections.extend(['## 背景：' + node['title'], body])
            versions.append({'node_id': nid, 'content_ref': resolved['content_ref'],
                             'synthesis_id': resolved['synthesis_id']})
        else:
            missing.append({'node_id': nid, 'title': node['title']})
        if node['kind'] == 'flow':
            from .flow_steps import view
            structure = view(conn, nid, batch['project_id'], top_k=0)
            if structure['steps']:
                structures.append(dict(flow_id=nid, steps=structure['steps'], connections=structure['connections']))
                sections.append('### 步骤与所用知识：' + node['title'])
                for step in structure['steps']:
                    sections.append('**' + step['title'] + '**\n\n' + step['description'])
                    for use in step['knowledge']:
                        sections.append('- 使用 ' + use['title'] + '：' + use['usage'])
                by_id = {s['id']: s['title'] for s in structure['steps']}
                for edge in structure['connections']:
                    sections.append('- ' + by_id[edge['from']] + ' → ' + by_id[edge['to']] +
                        ('（异常）' if edge['relation'] == 'fails_to' else '') +
                        ('：' + edge['conditions'] if edge.get('conditions') else ''))
    sections.append('## 本批原题')
    for item in batch['items']:
        sections.append('### %s · %s\n\n%s' % (item['label'], item['question_id'], item['stem']))
        if include_answers:
            answer = conn.execute('SELECT answer_basis FROM questions WHERE id=?',
                                  (item['question_id'],)).fetchone()[0]
            if answer:
                sections.append(answer)
    open_gaps = [g for g in batch['gaps'] if g['state'] != 'resolved']
    if open_gaps:
        sections.append('## 遗留问题\n' + '\n'.join('- ' + g['title'] for g in open_gaps))
    manifest = {'batch_id': batch_id, 'project_id': batch['project_id'],
                'questions': [{'label': i['label'], 'question_id': i['question_id']} for i in batch['items']],
                'node_ids': selected, 'documents': versions, 'flow_structures': structures}
    markdown = '\n\n'.join(sections)
    manifest['revision'] = hashlib.sha256(markdown.encode('utf-8')).hexdigest()
    return {'manifest': manifest, 'markdown': markdown, 'missing_content': missing}


def _hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def prepare_record(conn, batch_id, transcript, source_key='pasted-chat', max_chars=10000):
    transcript = transcript.replace('\r\n', '\n').replace('\r', '\n')
    batch = read(conn, batch_id)
    old = conn.execute('SELECT offset,prefix_hash FROM review_record_offsets '
                       'WHERE batch_id=? AND source_key=?', (batch_id, source_key)).fetchone()
    start = old['offset'] if old and _hash(transcript[:old['offset']]) == old['prefix_hash'] else 0
    end = min(len(transcript), start + max(1, min(24000, int(max_chars))))
    return {'batch_id': batch_id, 'delta': transcript[start:end], 'has_more': end < len(transcript),
        'source_ticket': {'source_key': source_key, 'base_offset': old['offset'] if old else 0,
                          'base_hash': old['prefix_hash'] if old else '', 'end_offset': end,
                          'prefix_hash': _hash(transcript[:end]), 'delta_offset': start},
        'questions': [{'question_id': i['question_id'], 'label': i['label'], 'stem': i['stem']}
                      for i in batch['items']],
        'open_gaps': [g for g in batch['gaps'] if g['state'] != 'resolved'],
        'instructions': '将增量中的实际回答匹配到本批原题；没有编号也按题意匹配。'
            '不能确定的留在unmatched。区分用户回答、AI解释、用户确认；并列问题与递归追问用parent_id。'
            '只有用户明确确认才关闭对应问题；单题回答通过不自动关闭其他缺口或标记整个主题掌握。'}


def commit_record(conn, request_id, batch_id, attempts=None, gaps=None, unmatched=None, source_ticket=None,
                  recall_results=None, source_updates=None):
    payload = dict(batch_id=batch_id, attempts=attempts or [], gaps=gaps or [],
                   unmatched=unmatched or [], source_ticket=source_ticket, recall_results=recall_results or [],
                   source_updates=source_updates or [])
    digest, previous = review_graph._request(conn, request_id, 'review.record', payload)
    if previous is not None:
        return previous
    batch = _batch(conn, batch_id)
    allowed = {r[0] for r in conn.execute('SELECT question_id FROM review_batch_items WHERE batch_id=?', (batch_id,))}
    saved = []
    with transaction(conn):
        if source_ticket:
            old = conn.execute('SELECT offset,prefix_hash FROM review_record_offsets WHERE batch_id=? '
                               'AND source_key=?', (batch_id, source_ticket['source_key'])).fetchone()
            if ((old['offset'], old['prefix_hash']) if old else (0, '')) != (
                    source_ticket['base_offset'], source_ticket['base_hash']):
                raise ValidationError('Transcript advanced in another window; prepare again')
        for index, item in enumerate(attempts or []):
            qid = item['question_id']
            if qid not in allowed:
                raise ValidationError('Question is not in this batch: ' + qid)
            kind = item.get('kind', 'answer')
            if kind not in ('answer', 'explanation', 'confirmation'):
                raise ValidationError('Unknown record kind')
            result = item.get('result')
            if result not in (None, 'pass', 'deepen') or result and kind != 'answer':
                raise ValidationError('Only actual answers can receive pass/deepen')
            coverage = item.get('coverage', [])
            for covered in coverage:
                review_graph._node(conn, covered['node_id'])
            aid = item.get('attempt_id') or 'attempt-' + _hash(request_id + ':' + str(index))
            values = (aid, batch_id, qid, batch['project_id'], kind, item.get('text', ''), result,
                      item.get('gap_note', ''), review_graph._json(coverage),
                      review_graph._json(item.get('source_ref', source_ticket or {})))
            old = conn.execute('SELECT * FROM review_question_attempts WHERE id=?', (aid,)).fetchone()
            if old:
                if tuple(old)[:-1] != values:
                    raise ValidationError('attempt_id already identifies another answer')
            else:
                conn.execute('INSERT INTO review_question_attempts VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                             values + (now_iso(),))
            saved.append(aid)
        for item in gaps or []:
            gid = item['id']
            old = conn.execute('SELECT * FROM review_batch_gaps WHERE id=?', (gid,)).fetchone()
            if old and old['batch_id'] != batch_id:
                raise ValidationError('Gap belongs to another batch')
            value = dict(old) if old else {'id': gid, 'batch_id': batch_id, 'question_id': None,
                'node_id': None, 'parent_id': None, 'title': '', 'state': 'open', 'note': ''}
            value.update(item)
            if not value['title'] or value['state'] not in ('open', 'explained', 'resolved', 'deferred'):
                raise ValidationError('Gap needs title and open/explained/resolved/deferred state')
            if value['question_id'] and value['question_id'] not in allowed:
                raise ValidationError('Gap question is outside the batch')
            if value['node_id']:
                review_graph._node(conn, value['node_id'])
            if value['parent_id']:
                parent = conn.execute('SELECT batch_id FROM review_batch_gaps WHERE id=?', (value['parent_id'],)).fetchone()
                if not parent or parent[0] != batch_id or value['parent_id'] == gid:
                    raise ValidationError('Parent gap must be in the same batch')
                seen, parent_id = {gid}, value['parent_id']
                while parent_id:
                    if parent_id in seen:
                        raise ValidationError('Recursive gap cycle')
                    seen.add(parent_id)
                    parent_id = conn.execute('SELECT parent_id FROM review_batch_gaps WHERE id=?', (parent_id,)).fetchone()[0]
            conn.execute('INSERT INTO review_batch_gaps VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) '
                         'DO UPDATE SET title=excluded.title,state=excluded.state,note=excluded.note,'
                         'parent_id=excluded.parent_id,question_id=excluded.question_id,node_id=excluded.node_id,'
                         'updated_at=excluded.updated_at', tuple(value[k] for k in
                         ('id', 'batch_id', 'question_id', 'node_id', 'parent_id', 'title', 'state', 'note')) + (now_iso(),))
        for item in source_updates or []:
            old = conn.execute('SELECT * FROM review_question_attempts WHERE id=?', (item['attempt_id'],)).fetchone()
            if not old or old['batch_id'] != batch_id:
                raise ValidationError('Source update must identify an existing attempt in this batch')
            ref = json.loads(old['source_ref'])
            previous_sources = ref.get('prior_representations', [])
            previous_sources.append({'text': old['answer'], 'representation': ref.get('representation'),
                                     'reason': item.get('reason', 'source text refinement')})
            ref.update(item.get('source_ref', {}))
            ref['prior_representations'] = previous_sources
            conn.execute('UPDATE review_question_attempts SET answer=?,source_ref=? WHERE id=?',
                         (item['text'], review_graph._json(ref), item['attempt_id']))
        for index, item in enumerate(unmatched or []):
            uid = item.get('id') or 'unmatched-' + _hash(request_id + ':' + str(index))
            old = conn.execute('SELECT batch_id,payload FROM review_record_unmatched WHERE id=?', (uid,)).fetchone()
            if old and old['batch_id'] != batch_id:
                raise ValidationError('Unmatched fragment belongs to another batch')
            data = dict(json.loads(old['payload']) if old else {}, **item)
            conn.execute('INSERT INTO review_record_unmatched VALUES(?,?,?) ON CONFLICT(id) '
                         'DO UPDATE SET payload=excluded.payload', (uid, batch_id, review_graph._json(data)))
        if recall_results:
            covered = {c['node_id'] for a in attempts or [] if a.get('kind', 'answer') == 'answer'
                       for c in a.get('coverage', [])}
            if any(r['node_id'] not in covered for r in recall_results):
                raise ValidationError('Recall must identify knowledge covered by an actual answer in this record')
            review_graph.assess(conn, request_id + ':recall', recall_results=recall_results)
        if source_ticket:
            conn.execute('INSERT INTO review_record_offsets VALUES(?,?,?,?) ON CONFLICT(batch_id,source_key) '
                         'DO UPDATE SET offset=excluded.offset,prefix_hash=excluded.prefix_hash',
                         (batch_id, source_ticket['source_key'], source_ticket['end_offset'], source_ticket['prefix_hash']))
        conn.execute('UPDATE review_batches SET updated_at=? WHERE id=?', (now_iso(), batch_id))
        return review_graph._receipt(conn, request_id, 'review.record', digest,
            {'success': True, 'batch_id': batch_id, 'attempt_ids': saved,
             'open_gaps': conn.execute("SELECT COUNT(*) FROM review_batch_gaps WHERE batch_id=? AND state!='resolved'", (batch_id,)).fetchone()[0],
             'unmatched_count': conn.execute("SELECT COUNT(*) FROM review_record_unmatched WHERE batch_id=? "
                                            "AND COALESCE(json_extract(payload,'$.state'),'pending')!='resolved'", (batch_id,)).fetchone()[0]})
