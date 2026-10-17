"""Incremental question ingestion: append sources and links, preserve old fields."""
import hashlib
from . import questions, question_categories, review_graph
from .db import transaction
from .graph import ValidationError, now_iso


def setup(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS question_link_pending(
      question_id TEXT PRIMARY KEY REFERENCES questions(id), reason TEXT NOT NULL,
      candidate_node_ids TEXT NOT NULL DEFAULT '[]', origin TEXT NOT NULL, updated_at TEXT NOT NULL)''')


def commit(conn, request_id, entries, source_ref=None):
    payload = dict(entries=entries, source_ref=source_ref)
    digest, previous = review_graph._request(conn, request_id, 'questions.batch', payload)
    if previous is not None:
        return previous
    results = []
    with transaction(conn):
        for index, item in enumerate(entries):
            qid = item.get('question_id')
            old = conn.execute('SELECT * FROM questions WHERE id=?', (qid,)).fetchone() if qid else None
            if not old and item.get('action') == 'reuse':
                raise ValidationError('Cannot reuse missing question: ' + str(qid))
            if not old:
                # No automatic semantic merge. A stable client key/request yields
                # the same new ID; the caller identifies equivalence before commit.
                qid = qid or 'q-' + hashlib.sha256(
                    (request_id + ':' + str(item.get('client_key', index))).encode()).hexdigest()[:24]
                questions.add_question(conn, course_id=item.get('course_id', 'public-questions'),
                    question_id=qid, stem=item['stem'], group_key=item.get('group_key', ''),
                    variants=item.get('variants'), context=item.get('context', ''),
                    answer_basis=item.get('answer_basis', ''), source_ref=item.get('source_ref', source_ref or {}),
                    origin=item.get('origin', 'manual'))
            else:
                variants = list(item.get('variants', []))
                if item.get('stem') and item['stem'] != old['stem']:
                    variants.append(item['stem'])
                questions.merge_variants(conn, qid, variants=variants,
                    source_ref=item.get('source_ref', source_ref))
                # Explicit correction is distinct from adding another source.
                corrections = item.get('corrections', {})
                for key in corrections:
                    if key not in ('stem', 'context', 'answer_basis', 'group_key'):
                        raise ValidationError('Unsupported question correction: ' + key)
                if corrections:
                    conn.execute('UPDATE questions SET ' + ','.join(k + '=?' for k in corrections) +
                                 ',updated_at=? WHERE id=?', list(corrections.values()) + [now_iso(), qid])
            for tag in item.get('categories', []):
                if tag not in question_categories.LABELS:
                    raise ValidationError('Unknown question category: ' + tag)
                conn.execute('INSERT OR IGNORE INTO question_categories VALUES(?,?,?)',
                             (qid, tag, 'explicit'))
            links = [dict(x, question_id=qid) for x in item.get('links', [])]
            if links:
                review_graph.commit(conn, request_id + ':links:' + str(index), question_links=links)
            if item.get('firsthand'):
                questions.upgrade_firsthand(conn, qid, **item['firsthand'])
            if 'pending_reason' in item:
                if item['pending_reason']:
                    conn.execute('INSERT INTO question_link_pending VALUES(?,?,?,?,?) ON CONFLICT(question_id) '
                                 'DO UPDATE SET reason=excluded.reason,updated_at=excluded.updated_at',
                                 (qid, item['pending_reason'], '[]', 'question-batch', now_iso()))
                else:
                    conn.execute('DELETE FROM question_link_pending WHERE question_id=?', (qid,))
            results.append({'client_key': item.get('client_key'), 'question_id': qid,
                            'status': 'reused' if old else 'created', 'linked': len(links)})
        return review_graph._receipt(conn, request_id, 'questions.batch', digest,
                                    {'success': True, 'items': results})
