"""Workspace documents and references to existing content; never a second wiki."""
import base64
import hashlib
import json
import uuid
from pathlib import Path

from . import content, sources
from .db import transaction
from .graph import ValidationError, now_iso

KINDS = ('material', 'lesson', 'record', 'note', 'review_pack')


def _pdf_text(path, page_start, page_end):
    try:
        import pymupdf as fitz
    except ImportError:
        try:
            import fitz
        except ImportError as exc:
            raise ValidationError('PDF reading requires the pdf extra (PyMuPDF)') from exc
    with fitz.open(str(path)) as pdf:
        first = max(1, int(page_start))
        last = min(len(pdf), first + 19, int(page_end or first + 2))
        if first > last:
            raise ValidationError('Invalid PDF page range')
        return '\n\n'.join('[p.%d]\n%s' % (i, pdf[i-1].get_text()) for i in range(first, last+1))


def setup(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS workspace_documents(
      id TEXT PRIMARY KEY, title TEXT NOT NULL, kind TEXT NOT NULL,
      project_id TEXT NOT NULL DEFAULT '', locator TEXT NOT NULL,
      version INTEGER NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS workspace_document_versions(
      document_id TEXT NOT NULL, version INTEGER NOT NULL, metadata TEXT NOT NULL,
      created_at TEXT NOT NULL, PRIMARY KEY(document_id,version));
    ''')


def root(orch):
    if orch.workspace:
        return Path(orch.workspace['root']) / 'documents'
    from .db import PROJECT_ROOT
    return PROJECT_ROOT / 'documents'


def _row(row):
    d = dict(row)
    d['locator'] = json.loads(d['locator'])
    return d


def listing(orch, project_id=None, kind=None, query='', offset=0, limit=60):
    """Existing sources/bodies are projected by identity, without copying prose."""
    conn = orch.conn
    entries = [_row(r) for r in conn.execute('SELECT * FROM workspace_documents')]
    for r in conn.execute('SELECT id,title,course_id,kind FROM sources'):
        entries.append(dict(id='source:' + r['id'], title=r['title'], kind='material',
            project_id=r['course_id'], version=None, locator={'type': 'source', 'id': r['id']},
            format=r['kind'], existing=True))
    for r in conn.execute('SELECT b.id,b.title,b.area,MAX(s.id) AS version FROM knowledge_blocks b '
                          'LEFT JOIN knowledge_syntheses s ON s.block_id=b.id GROUP BY b.id'):
        owners = [x[0] for x in conn.execute("SELECT json_extract(payload,'$.owner_ref.id') "
            "FROM review_graph_nodes WHERE json_extract(payload,'$.content_ref.type')='knowledge_block' "
            "AND json_extract(payload,'$.owner_ref.type') IN ('project','course') "
            "AND json_extract(payload,'$.content_ref.id')=?", (r['id'],)) if x[0]]
        entries.append(dict(id='knowledge:' + r['id'], title=r['title'], kind='note',
            project_id=owners[0] if owners else '', project_ids=owners, area=r['area'],
            version=r['version'], locator={'type': 'knowledge_block', 'id': r['id']}, existing=True))
    lesson_ids = set()
    for table in ('generated_lessons', 'lesson_artifacts'):
        for r in conn.execute('SELECT DISTINCT node_id FROM ' + table):
            if r[0] in lesson_ids:
                continue
            lesson_ids.add(r[0])
            title = conn.execute('SELECT title,course_id FROM nodes WHERE id=?', (r[0],)).fetchone()
            graph = conn.execute('SELECT payload FROM review_graph_nodes WHERE id=?', (r[0],)).fetchone()
            n = json.loads(graph[0]) if graph else {}
            entries.append(dict(id='lesson:' + r[0], title=(title['title'] if title else n.get('title', r[0])),
                kind='lesson', project_id=(title['course_id'] if title else (n.get('owner_ref') or {}).get('id', '')),
                locator={'type': 'lesson', 'id': r[0]}, version=None, existing=True))
    for r in conn.execute('SELECT id,title,project_id,updated_at FROM review_batches'):
        entries.append(dict(id='review-pack:' + r['id'], title=r['title'], kind='review_pack',
            project_id=r['project_id'], version=None, updated_at=r['updated_at'],
            locator={'type': 'review_pack', 'id': r['id']}, existing=True))
    if project_id:
        entries = [d for d in entries if not d.get('project_id') or d['project_id'] == project_id
                   or project_id in d.get('project_ids', [])]
    if kind:
        entries = [d for d in entries if d['kind'] == kind]
    if query:
        entries = [d for d in entries if query.casefold() in (d['title'] + ' ' + d['id']).casefold()]
    entries.sort(key=lambda d: (d.get('updated_at', ''), d['title']), reverse=True)
    offset, limit = max(0, int(offset)), max(1, min(200, int(limit)))
    return dict(items=entries[offset:offset+limit], total=len(entries), offset=offset,
                next_offset=offset+limit if offset+limit < len(entries) else None)


def metadata(orch, document_id):
    r = orch.conn.execute('SELECT * FROM workspace_documents WHERE id=?', (document_id,)).fetchone()
    if r:
        data = _row(r)
        task = orch.conn.execute('SELECT id FROM workflow_prepared_tasks WHERE document_id=?', (document_id,)).fetchone()
        if task:
            data['task_id'] = task[0]
        return data
    # IDs of projected old sources remain usable without a migration write.
    prefix, _, rid = document_id.partition(':')
    table = {'source': 'sources', 'knowledge': 'knowledge_blocks'}.get(prefix)
    if table:
        r = orch.conn.execute('SELECT * FROM ' + table + ' WHERE id=?', (rid,)).fetchone()
        if r:
            return dict(id=document_id, title=r['title'], kind='material' if prefix == 'source' else 'note',
                locator={'type': 'source' if prefix == 'source' else 'knowledge_block', 'id': rid}, version=None)
    if prefix == 'lesson':
        resolved = content.resolve(orch.conn, {'type': 'lesson', 'id': rid})
        if resolved['body']:
            return dict(id=document_id, title=rid, kind='lesson', locator={'type': 'lesson', 'id': rid}, version=None)
    if prefix == 'review-pack':
        row = orch.conn.execute('SELECT title FROM review_batches WHERE id=?', (rid,)).fetchone()
        if row:
            return dict(id=document_id, title=row[0], kind='review_pack',
                        locator={'type': 'review_pack', 'id': rid}, version=None)
    raise ValidationError('Unknown document: ' + document_id)


def save(orch, title, kind='material', project_id='', document_id=None, text=None,
         path=None, filename=None, data_base64=None, base_version=None, source_refs=None):
    if kind not in KINDS or not isinstance(title, str) or not title.strip():
        raise ValidationError('Provide a document title and a supported kind')
    document_id = document_id or 'doc-' + uuid.uuid4().hex
    old = orch.conn.execute('SELECT * FROM workspace_documents WHERE id=?', (document_id,)).fetchone()
    if old and orch.conn.execute('SELECT 1 FROM workflow_prepared_tasks WHERE document_id=?', (document_id,)).fetchone():
        raise ValidationError('This is a saved task snapshot; prepare a new task to change it')
    if not old and document_id.startswith(('source:', 'knowledge:', 'lesson:', 'review-pack:')):
        raise ValidationError('This document ID belongs to an existing formal entry')
    if old and (base_version is None or int(base_version) != old['version']):
        raise ValidationError('Document changed; read its current version before updating')
    if not old and base_version not in (None, 0):
        raise ValidationError('Unknown document version')
    version = old['version'] + 1 if old else 1
    if sum(x is not None for x in (text, path, data_base64)) != 1:
        raise ValidationError('Provide exactly one of text, path or data_base64')
    if path is not None:
        checked = sources._check_in_roots(path, orch.source_roots + [str(root(orch))])
        # Keep an immutable workspace copy so updates or moving external files
        # do not silently change the input of an already prepared task.
        raw, suffix = checked.read_bytes(), checked.suffix.lower()
        original = str(checked)
    elif data_base64 is not None:
        try:
            raw = base64.b64decode(data_base64, validate=True)
        except (ValueError, TypeError) as exc:
            raise ValidationError('Invalid uploaded file') from exc
        suffix, original = Path(filename or 'material.txt').suffix.lower(), filename
    else:
        if not isinstance(text, str):
            raise ValidationError('Document text must be a string')
        raw, suffix, original = text.encode('utf-8'), '.md' if kind != 'record' else '.txt', None
        if old:
            old_suffix = Path(json.loads(old['locator'])['path']).suffix
            if old_suffix != '.pdf':
                suffix = old_suffix
    if suffix not in ('.md', '.markdown', '.txt', '.pdf', '.cpp', '.h', '.hpp', '.py', '.java', '.json'):
        raise ValidationError('Use Markdown, TXT, PDF or a supported code file')
    if len(raw) > 25 * 1024 * 1024:
        raise ValidationError('Document exceeds 25 MB; register a selected part instead')
    digest = hashlib.sha256(raw).hexdigest()
    relative = Path(kind) / (hashlib.sha256(document_id.encode()).hexdigest()[:24] + '-' + str(version) + suffix)
    target = root(orch) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    locator = dict(type='managed_file', path=relative.as_posix(), sha256=digest,
                   original=original, source_refs=source_refs or [])
    data = dict(id=document_id, title=title.strip(), kind=kind, project_id=project_id or '',
                locator=locator, version=version, updated_at=now_iso())
    # A unique version file is never overwritten; old versions stay recoverable.
    try:
        with target.open('xb') as stream:
            stream.write(raw)
    except FileExistsError as exc:
        raise ValidationError('Document version is being saved elsewhere; reload before updating') from exc
    try:
        with transaction(orch.conn):
            orch.conn.execute('INSERT INTO workspace_documents VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) '
                'DO UPDATE SET title=excluded.title,kind=excluded.kind,project_id=excluded.project_id,'
                'locator=excluded.locator,version=excluded.version,updated_at=excluded.updated_at',
                (document_id, data['title'], kind, data['project_id'], json.dumps(locator), version, data['updated_at']))
            orch.conn.execute('INSERT INTO workspace_document_versions VALUES(?,?,?,?)',
                (document_id, version, json.dumps(data, ensure_ascii=False), data['updated_at']))
    except Exception:
        target.unlink()  # only the just-created, exact version file
        raise
    return dict(success=True, document=data)


def read(orch, document_id, version=None, start_line=1, end_line=None,
         page_start=1, page_end=None, max_chars=12000, anchor=None):
    d = metadata(orch, document_id)
    if version is not None and d['locator']['type'] == 'managed_file':
        r = orch.conn.execute('SELECT metadata FROM workspace_document_versions '
                             'WHERE document_id=? AND version=?', (document_id, int(version))).fetchone()
        if not r:
            raise ValidationError('Unknown document version')
        d = json.loads(r[0])
    loc = d['locator']
    max_chars = max(1, min(50000, int(max_chars)))
    if loc['type'] == 'managed_file':
        target = (root(orch) / loc['path']).resolve()
        if root(orch).resolve() not in target.parents:
            raise ValidationError('Invalid managed document path')
        raw = target.read_bytes()
        if hashlib.sha256(raw).hexdigest() != loc['sha256']:
            raise ValidationError('Managed file changed outside LO; register a new version')
        if target.suffix == '.pdf':
            body = _pdf_text(target, page_start, page_end)
        else:
            try:
                body = raw.decode('utf-8-sig')
            except UnicodeDecodeError:
                body = raw.decode('gb18030')
    elif loc['type'] == 'source':
        source = orch.conn.execute('SELECT * FROM sources WHERE id=?', (loc['id'],)).fetchone()
        original = Path(source['uri'])
        original_allowed = original.is_file() and any(Path(r).resolve() in original.resolve().parents
            for r in orch.source_roots + [str(root(orch))])
        if original_allowed and not anchor:
            if source['kind'] == 'pdf':
                body = _pdf_text(original, page_start, page_end)
            else:
                body = original.read_text(encoding='utf-8-sig', errors='replace')
            d['content_mode'] = 'original_file'
            lines = body.splitlines()
            first, last = max(1, int(start_line)), int(end_line) if end_line is not None else len(lines)
            body = '\n'.join(lines[first-1:last])
            return dict(document=d, text=body[:max_chars], truncated=len(body)>max_chars,
                selection=dict(start_line=first, end_line=last, page_start=page_start, page_end=page_end, anchor=anchor),
                fingerprint=hashlib.sha256(body[:max_chars].encode()).hexdigest())
        d['content_mode'] = 'indexed_excerpt' if source['kind'] != 'url' else 'url_reference'
        sql, args = 'SELECT anchor,text FROM chunks WHERE source_id=?', [loc['id']]
        if anchor:
            sql += ' AND anchor=?'
            args.append(anchor)
        elif source['kind'] == 'pdf':
            # Source extraction has one or more page-anchored chunks; explicitly
            # select pages instead of accidentally taking the first book excerpt.
            first, last = max(1, int(page_start)), int(page_end or int(page_start) + 2)
            sql += " AND CAST(REPLACE(anchor,'p.','') AS INTEGER) BETWEEN ? AND ?"
            args.extend([first, min(first + 19, last)])
        rows = orch.conn.execute(sql + ' ORDER BY id', args)
        pieces, size = [], 0
        for r in rows:
            piece = '[' + r['anchor'] + ']\n' + r['text']
            pieces.append(piece)
            size += len(piece)
            if size > max_chars + 2000:
                break
        body = '\n\n'.join(pieces)
        if not body and source['kind'] == 'url':
            body = source['uri']
    elif loc['type'] == 'review_pack':
        from .review_batches import export
        package = export(orch.conn, loc['id'])
        body = package['markdown']
        d['version'] = package['manifest']['revision']
    else:
        resolved = content.resolve(orch.conn, loc)
        body = resolved['body']
        d['version'] = resolved.get('synthesis_id') or d.get('version')
    start = max(1, int(start_line))
    lines = body.splitlines()
    end = min(len(lines), int(end_line)) if end_line is not None else len(lines)
    body = '\n'.join(lines[start-1:end])
    return dict(document=d, text=body[:max_chars], truncated=len(body) > max_chars,
        selection=dict(start_line=start, end_line=end, page_start=page_start, page_end=page_end, anchor=anchor),
        fingerprint=hashlib.sha256(body[:max_chars].encode()).hexdigest())


def versions(orch, document_id):
    metadata(orch, document_id)
    return [json.loads(r[0]) for r in orch.conn.execute('SELECT metadata FROM workspace_document_versions '
                                                      'WHERE document_id=? ORDER BY version DESC', (document_id,))]
