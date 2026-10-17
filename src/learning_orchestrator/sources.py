"""Local source registration and extraction.

- URLs are registered as references only (never fetched).
- Markdown/TXT files are read from configured source roots and chunked.
- PDF extraction works when PyMuPDF (`fitz`) is installed; otherwise a clear
  error is raised.
- Search uses SQLite FTS5 when available, else a LIKE fallback. No embeddings.

Only files inside configured source roots may be imported; nothing outside
those roots is ever read.
"""

import re
import uuid
from pathlib import Path

from . import code_index
from .db import SOURCE_KINDS, dicts, fts_available, transaction
from .graph import ValidationError, now_iso

_CHUNK_MAX = 1200  # characters per extracted chunk
_ATTACHED_EXCERPT_LIMIT = 8


def _require(cond, msg):
    if not cond:
        raise ValidationError(msg)


def _check_in_roots(path, source_roots):
    path = Path(path).resolve()
    roots = [Path(r).resolve() for r in source_roots]
    _require(roots, "no source roots configured")
    ok = any(path == r or r in path.parents for r in roots)
    _require(ok, "file %s is outside the configured source roots" % path)
    _require(path.is_file(), "not a file: %s" % path)
    return path


def _matching_root(path, source_roots):
    """The configured root that contains path (used for relative anchors)."""
    path = Path(path).resolve()
    for r in source_roots:
        r = Path(r).resolve()
        if path == r or r in path.parents:
            return r
    return path.parent


def register_url(conn, source_id, course_id, url, title, lecture_ref=""):
    """Register a remote source as a reference. Never fetches content."""
    _require(url.startswith("http://") or url.startswith("https://"),
             "url must be http(s): %r" % url)
    with transaction(conn):
        conn.execute(
            "INSERT INTO sources (id, course_id, kind, uri, title, lecture_ref)"
            " VALUES (?,?, 'url', ?,?,?)",
            (source_id, course_id, url, title, lecture_ref),
        )
    return source_id


def register_file(conn, course_id, path, source_roots, title=None,
                  lecture_ref="", source_id=None, page_ranges=None):
    """Import a local Markdown/TXT/PDF/code file: register + extract chunks."""
    path = _check_in_roots(path, source_roots)
    suffix = path.suffix.lower()
    is_code = code_index.is_code_file(path)
    if is_code:
        _require(not code_index.is_excluded(path),
                 "refusing to index build/vendor/generated file: %s" % path)
    # The sources.kind CHECK predates code support; code files are stored as
    # 'text' and marked via note='code' so existing databases keep working.
    kind = {".md": "markdown", ".markdown": "markdown", ".txt": "text",
            ".pdf": "pdf"}.get(suffix, "text" if is_code else None)
    _require(kind is not None, "unsupported file type: %s" % suffix)
    source_id = source_id or ("src-file-" + uuid.uuid4().hex[:10])
    existing = conn.execute(
        "SELECT kind FROM sources WHERE id = ?", (source_id,)
    ).fetchone()
    if existing:
        count = conn.execute(
            "SELECT count(*) FROM chunks WHERE source_id = ?", (source_id,)
        ).fetchone()[0]
        return {"source_id": source_id, "kind": existing["kind"],
                "chunks": count, "reused": True}
    _require(not page_ranges or kind == "pdf",
             "page_ranges is supported only for PDF sources")
    if is_code:
        root = _matching_root(path, source_roots)
        chunks = [(c["anchor"], c["text"])
                  for c in code_index.chunk_code_file(path, root)]
    else:
        chunks = _extract(path, kind, page_ranges=page_ranges)
    _require(chunks, "no text extracted from %s" % path)
    with transaction(conn):
        conn.execute(
            "INSERT INTO sources (id, course_id, kind, uri, title,"
            " lecture_ref, note) VALUES (?,?,?,?,?,?,?)",
            (source_id, course_id, kind, str(path),
             title or path.name, lecture_ref,
             "code" if is_code else ""),
        )
        conn.executemany(
            "INSERT INTO chunks (source_id, anchor, text) VALUES (?,?,?)",
            [(source_id, anchor, text) for anchor, text in chunks],
        )
    return {"source_id": source_id, "kind": kind, "chunks": len(chunks)}


def _extract(path, kind, page_ranges=None):
    if kind == "pdf":
        try:
            try:
                import pymupdf as fitz  # current PyMuPDF name
            except ImportError:
                import fitz  # PyMuPDF <= 1.27 compatibility name
        except ImportError:
            raise ValidationError(
                "PDF extraction requires PyMuPDF; install the 'pdf' extra")
        out = []
        with fitz.open(str(path)) as doc:
            wanted = None
            if page_ranges:
                wanted = set()
                for start, end in page_ranges:
                    _require(1 <= start <= end <= len(doc),
                             "invalid PDF page range: %r" % ((start, end),))
                    wanted.update(range(start, end + 1))
            for i, page in enumerate(doc, start=1):
                if wanted is not None and i not in wanted:
                    continue
                text = page.get_text().strip()
                if text:
                    out.append(("p.%d" % i, text[:_CHUNK_MAX]))
        return out
    text = path.read_text(encoding="utf-8", errors="replace")
    if kind == "markdown":
        return _chunk_markdown(text)
    return _chunk_plain(text)


def _chunk_markdown(text):
    """Chunk by ATX headings; anchor each chunk with its heading path."""
    chunks, anchor, buf = [], "", []

    def flush():
        body = "\n".join(buf).strip()
        if body:
            chunks.append((anchor, body[:_CHUNK_MAX]))

    for line in text.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            flush()
            buf = []
            anchor = m.group(2).strip()
        else:
            buf.append(line)
    flush()
    return chunks


def _chunk_plain(text):
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, buf = [], ""
    for p in paras:
        if len(buf) + len(p) > _CHUNK_MAX and buf:
            chunks.append(("", buf))
            buf = ""
        buf = (buf + "\n\n" + p) if buf else p
    if buf:
        chunks.append(("", buf))
    return chunks


def attach_source(conn, node_id, source_id, anchor=""):
    """Attach a source to a node (an explains-style link with an anchor)."""
    _require(conn.execute(
        "SELECT 1 FROM nodes WHERE id = ?", (node_id,)).fetchone(),
        "unknown node id: %r" % node_id)
    _require(conn.execute(
        "SELECT 1 FROM sources WHERE id = ?", (source_id,)).fetchone(),
        "unknown source id: %r" % source_id)
    with transaction(conn):
        conn.execute(
            "INSERT OR IGNORE INTO node_sources (node_id, source_id, anchor)"
            " VALUES (?,?,?)",
            (node_id, source_id, anchor),
        )


def sources_for_node(conn, node_id, max_excerpt=500):
    """Attached sources with optional local excerpt from extracted chunks."""
    rows = dicts(conn.execute(
        "SELECT s.*, ns.anchor AS node_anchor FROM node_sources ns"
        " JOIN sources s ON s.id = ns.source_id WHERE ns.node_id = ?",
        (node_id,)))
    for r in rows:
        r["excerpts"] = []
        if r["kind"] != "url":
            page_range = _page_range(r["node_anchor"])
            if page_range:
                anchors = _sample_page_anchors(
                    page_range[0], page_range[1], _ATTACHED_EXCERPT_LIMIT)
                marks = ",".join("?" for _ in anchors)
                chunks = dicts(conn.execute(
                    "SELECT anchor, text FROM chunks WHERE source_id = ?"
                    " AND anchor IN (" + marks + ") ORDER BY id",
                    [r["id"]] + anchors))
            else:
                chunks = dicts(conn.execute(
                    "SELECT anchor, text FROM chunks WHERE source_id = ?"
                    " ORDER BY id LIMIT ?",
                    (r["id"], _ATTACHED_EXCERPT_LIMIT)))
            r["excerpts"] = [
                {"anchor": c["anchor"], "text": c["text"][:max_excerpt]}
                for c in chunks
            ]
    return rows


def _page_range(anchor):
    """Parse the attachment convention ``p.N`` or ``p.N-p.M``."""
    match = re.fullmatch(r"p\.(\d+)(?:-p\.(\d+))?", anchor or "")
    if not match:
        return None
    start = int(match.group(1))
    end = int(match.group(2) or start)
    return (start, end) if start <= end else None


def _sample_page_anchors(start, end, limit):
    """Cover the whole range without flooding the teaching context."""
    count = end - start + 1
    if count <= limit:
        pages = range(start, end + 1)
    elif limit == 1:
        pages = [start]
    else:
        pages = [round(start + i * (end - start) / (limit - 1))
                 for i in range(limit)]
    return ["p.%d" % page for page in dict.fromkeys(pages)]


def search_chunks(conn, course_id, query, limit=5, max_excerpt=400):
    """Full-text search over extracted chunks (FTS5, or LIKE fallback)."""
    query = (query or "").strip()
    if not query:
        return []
    # SQLite's default unicode61 tokenizer does not segment CJK text. LIKE is
    # slower but reliable for the small, page-scoped Chinese textbook index.
    if fts_available(conn) and not re.search(r"[\u3400-\u9fff]", query):
        sql = (
            "SELECT c.source_id, c.anchor,"
            " snippet(chunks_fts, 0, '[', ']', '...', 12) AS snip"
            " FROM chunks_fts f JOIN chunks c ON c.id = f.rowid"
            " JOIN sources s ON s.id = c.source_id"
            " WHERE chunks_fts MATCH ? AND s.course_id = ? LIMIT ?")
        try:
            rows = dicts(conn.execute(sql, (query, course_id, limit)))
        except Exception:
            rows = _like_search(conn, course_id, query, limit, max_excerpt)
    else:
        rows = _like_search(conn, course_id, query, limit, max_excerpt)
    for r in rows:
        r["text"] = r.pop("snip", r.get("text", ""))[:max_excerpt]
    return rows


def _like_search(conn, course_id, query, limit, max_excerpt):
    terms = [t for t in re.split(r"\s+", query) if len(t) >= 3]
    if not terms:
        return []
    params = ["%" + t + "%" for t in terms]
    where = " AND ".join("c.text LIKE ?" for _ in terms)
    sql = (
        "SELECT c.source_id, c.anchor, substr(c.text, 1, ?) AS text"
        " FROM chunks c JOIN sources s ON s.id = c.source_id"
        " WHERE s.course_id = ? AND " + where + " LIMIT ?")
    return dicts(conn.execute(
        sql, [max_excerpt, course_id] + params + [limit]))


def list_sources(conn, course_id):
    return dicts(conn.execute(
        "SELECT * FROM sources WHERE course_id = ? ORDER BY id", (course_id,)))
