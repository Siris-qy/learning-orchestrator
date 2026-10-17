"""Read bounded transcript slices; semantic analysis belongs to the calling AI.

No transcript indexing, model calls, automatic progress changes or new tables.
Reports are stored by teaching.commit in the existing teaching_updates log.
"""
import hashlib
import json

from . import teaching
from .graph import ValidationError, get_node
from .sources import _check_in_roots


def _read_file(path, source_roots):
    file = _check_in_roots(path, source_roots)
    if file.suffix.lower() not in ('.txt', '.md', '.markdown'):
        raise ValidationError('Learning records must be TXT or Markdown')
    raw = file.read_bytes()
    encodings = ['utf-16'] if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else ['utf-8-sig', 'gb18030']
    for encoding in encodings:
        try:
            return file, raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValidationError('Cannot decode learning record; use UTF-8')


def _digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _binding(conn, course_id, section_id):
    # Reuse report metadata as a source binding/checkpoint, not another table.
    row = conn.execute(
        "SELECT id,json_extract(payload,'$.record_analysis.source_ref') AS source_ref,"
        " json_extract(payload,'$.record_analysis.fingerprint') AS fingerprint,"
        " json_extract(payload,'$.record_analysis.processed_chars') AS processed_chars,"
        " json_extract(payload,'$.record_analysis.prefix_fingerprint') AS prefix_fingerprint,"
        " json_extract(payload,'$.record_analysis.covered_ranges') AS covered_ranges"
        " FROM teaching_updates WHERE course_id=? AND section_id=?"
        " AND (lower(json_extract(payload,'$.record_analysis.source_ref')) LIKE '%.txt'"
        " OR lower(json_extract(payload,'$.record_analysis.source_ref')) LIKE '%.md'"
        " OR lower(json_extract(payload,'$.record_analysis.source_ref')) LIKE '%.markdown')"
        " ORDER BY id DESC LIMIT 1", (course_id, section_id)).fetchone()
    return dict(row) if row else None


def check_bound_record(conn, source_roots, course_id, section_id):
    """Automatic resume-time detection. AI handles pending analysis in that turn.

    Unchanged records return metadata only. No model, polling worker or write.
    Append-only updates get a bounded tail + small overlap; edited prefixes
    trigger a fresh bounded scan. Reading a fragment never marks it processed.
    """
    bound = _binding(conn, course_id, section_id) if section_id else None
    if not bound:
        return {'status': 'unbound'}
    info = dict(source_ref=bound['source_ref'], analysis_id=bound['id'])
    try:
        _, text, _ = _read_file(bound['source_ref'], source_roots)
    except (ValidationError, OSError) as exc:
        return dict(info, status='unavailable', reason=str(exc))
    processed = bound['processed_chars']
    if processed is None:
        processed = 0
        for part in sorted(json.loads(bound['covered_ranges'] or '[]'),
                           key=lambda r: r.get('offset', 0)):
            if part.get('offset', 0) > processed:
                break
            processed = max(processed, part.get('end_offset', 0))
    processed = max(0, int(processed))
    fingerprint = _digest(text)
    if fingerprint == bound['fingerprint'] and processed >= len(text):
        return dict(info, status='unchanged', processed_chars=processed)
    prior_prefix = bound['prefix_fingerprint'] or bound['fingerprint']
    appended = (0 < processed <= len(text) and prior_prefix
                and _digest(text[:processed]) == prior_prefix)
    offset = max(0, processed - 1200) if appended else 0
    pack = prepare(conn, source_roots, course_id, section_id,
                   path=bound['source_ref'], offset=offset)
    return dict(info, status='pending_analysis',
                change='append' if appended else 'rescan',
                previously_processed_chars=processed,
                source=pack['source'], fragment=pack['fragment'], outline=pack['outline'])


def prepare(conn, source_roots, course_id, section_id=None, path=None,
            transcript=None, source_ref=None, offset=0, max_chars=10000):
    position = teaching.local_state(conn, course_id)
    sid = section_id or position.get('section_id')
    if not sid or get_node(conn, sid)['course_id'] != course_id:
        raise ValidationError('Specify a section belonging to this course')
    if path is None and transcript is None:
        bound = _binding(conn, course_id, sid)
        if not bound:
            raise ValidationError('No learning record is bound; provide path once')
        path = bound['source_ref']
    if path is not None and transcript is not None:
        raise ValidationError('Provide either path or transcript, not both')
    encoding = 'supplied-text'
    if path is not None:
        file, text, encoding = _read_file(path, source_roots)
        source_ref = str(file)
    else:
        if not isinstance(transcript, str):
            raise ValidationError('transcript must be text')
        text = transcript
        source_ref = source_ref or 'pasted-transcript'
    if offset < 0 or offset > len(text) or max_chars < 1:
        raise ValidationError('Invalid transcript offset or size')
    end = min(len(text), offset + min(max_chars, 24000))
    plan = teaching._active_plan(conn, course_id, sid)
    # Titles/IDs for alignment only, not the global graph, lessons or history.
    outline = [{k: item[k] for k in ('id', 'parent_id', 'kind', 'title', 'status', 'material_ref')}
               for item in teaching._items(conn, plan['id'])
               if item['status'] != 'retracted'] if plan else []
    return dict(course_id=course_id, section_id=sid,
                source=dict(ref=source_ref,
                            fingerprint=_digest(text),
                            encoding=encoding, total_chars=len(text)),
                fragment=dict(text=text[offset:end], offset=offset, end_offset=end,
                              prefix_fingerprint=_digest(text[:end]),
                              start_line=text.count('\n', 0, offset) + 1,
                              end_line=text.count('\n', 0, end) + 1,
                              next_offset=end if end < len(text) else None,
                              has_more=end < len(text)),
                position=position, outline=outline)


def read_analysis(conn, course_id, analysis_id):
    row = conn.execute(
        "SELECT id,section_id,role,ts,json_extract(payload,'$.record_analysis') AS analysis"
        ' FROM teaching_updates WHERE course_id=? AND id=?',
        (course_id, analysis_id)).fetchone()
    if not row or not row['analysis']:
        raise ValidationError('No learning-record analysis in this course at that ID')
    result = dict(row)
    result['analysis'] = json.loads(result['analysis'])
    return result
