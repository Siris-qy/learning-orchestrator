"""Symbol-aware chunking for C++/Proto source files.

Teaching needs code excerpts that cite file path, line range, and symbol —
not whole files. This module splits .proto/.h/.hpp/.cpp/.cc files by
top-level symbols (message/service/rpc, class/struct, function definitions)
using brace matching, and falls back to fixed-line windows when no symbol
boundaries are found. It is a teaching index, not a parser: heuristics favour
recall over exactness, and every chunk keeps its 1-based line range so a
teacher can always point back at the real file.
"""

import re
from pathlib import Path

CODE_SUFFIXES = {".proto", ".h", ".hpp", ".cpp", ".cc"}
CMAKE_NAME = "CMakeLists.txt"

# Never index build output, VCS data, vendored dependencies, or protobuf
# generated code.
EXCLUDE_DIRS = {
    "build", ".git", ".svn", "third_party", "external", "vendor",
    "node_modules", ".venv", "venv", "libs_tier_01",
}
GENERATED_MARKERS = (".pb.h", ".pb.cc", ".grpc.pb.h", ".grpc.pb.cc")

MAX_CHUNK_CHARS = 2000
FALLBACK_LINES = 60
FALLBACK_OVERLAP = 10

_CONTROL = re.compile(
    r"^\s*(if|for|while|switch|catch|else|do|try|return|namespace|using"
    r"|typedef|#)\b")
_CLASS = re.compile(r"^\s*(?:template\s*<[^;{}]*>\s*)?(class|struct)\s+(\w+)")
_PROTO_BLOCK = re.compile(r"^\s*(message|enum|service)\s+(\w+)")
_PROTO_RPC = re.compile(r"^\s*rpc\s+(\w+)\s*\(")
_FUNC_NAME = re.compile(r"((?:\w+::)*~?\w+)\s*\([^;{}]*$")


def _func_symbol(lines, i):
    """Best-effort qualified name for the function defined at line i."""
    sig = "\n".join(lines[max(0, i - 1):i + 1]).split("{")[0]
    m = _FUNC_NAME.search(sig)
    return m.group(1) if m else "(function)"


def is_code_file(path):
    path = Path(path)
    return path.name == CMAKE_NAME or path.suffix.lower() in CODE_SUFFIXES


def is_excluded(path):
    """True for build dirs, vendored deps, and generated protobuf code."""
    path = Path(path)
    if any(part in EXCLUDE_DIRS for part in path.parts):
        return True
    return path.name.endswith(GENERATED_MARKERS)


def module_of(rel_path):
    """Top-level directory of the project-relative path (the module)."""
    parts = Path(rel_path).parts
    return parts[0] if len(parts) > 1 else "(root)"


def chunk_code_file(path, root):
    """Split one source file into cited chunks.

    Returns a list of dicts: anchor, text, symbol, kind, start, end,
    rel_path, module. Line numbers are 1-based and inclusive.
    """
    path = Path(path)
    root = Path(root)
    rel = str(path.relative_to(root)).replace("\\", "/")
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    module = module_of(rel)
    if path.name == CMAKE_NAME:
        blocks = [("cmake", path.name, 1, len(lines))] if lines else []
    elif path.suffix.lower() == ".proto":
        blocks = _proto_blocks(lines)
    else:
        blocks = _cpp_blocks(lines)
    chunks = []
    for kind, symbol, start, end in blocks:
        chunks.extend(_emit(rel, module, kind, symbol, start, end, lines))
    if not chunks and lines:
        chunks = _fallback(rel, module, lines)
    return chunks


# ---------------------------------------------------------------------------
# Block finders. Each returns (kind, symbol, start_line, end_line), 1-based
# inclusive, in file order.
# ---------------------------------------------------------------------------

def _proto_blocks(lines):
    blocks = []
    i = 0
    while i < len(lines):
        m = _PROTO_BLOCK.match(lines[i])
        if m and "{" in lines[i]:
            end = _match_brace(lines, i)
            blocks.append((m.group(1), m.group(2), i + 1, end + 1))
            i = end + 1
        else:
            rpc = _PROTO_RPC.match(lines[i])
            if rpc:  # rpc outside a service block: cite the single line
                blocks.append(("rpc", rpc.group(1), i + 1, i + 1))
            i += 1
    return blocks


def _cpp_blocks(lines):
    blocks = []
    misc_start = None
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        cls = _CLASS.match(line)
        if cls and not stripped.endswith(";"):
            end = _match_brace(lines, i)
            blocks.extend(_class_blocks(lines, cls.group(1), cls.group(2), i, end))
            misc_start = None
            i = end + 1
            continue
        if _looks_like_function_def(lines, i):
            end = _match_brace(lines, i)
            blocks.append(("function", _func_symbol(lines, i), i + 1, end + 1))
            misc_start = None
            i = end + 1
            continue
        if stripped and not stripped.startswith("//"):
            if misc_start is None:
                misc_start = i
        elif misc_start is not None:
            blocks.append(("file scope", "(includes/globals)",
                           misc_start + 1, i + 1))
            misc_start = None
        i += 1
    if misc_start is not None:
        blocks.append(("file scope", "(includes/globals)",
                       misc_start + 1, len(lines)))
    return _merge_small_misc(blocks)


def _class_blocks(lines, kind, name, start, end):
    """One chunk for a small class; member-level chunks for a large one."""
    text_len = sum(len(l) + 1 for l in lines[start:end + 1])
    if text_len <= MAX_CHUNK_CHARS:
        return [(kind, name, start + 1, end + 1)]
    # Overview: declaration lines with method bodies elided, so the chunk
    # shows the class interface instead of just the `class X {` line.
    blocks = []
    overview_end = start
    i = start + 1
    while i < end:
        if _looks_like_function_def(lines, i):
            fend = _match_brace(lines, i)
            if fend > i:  # multi-line body: its own chunk
                symbol = "%s::%s" % (name, _func_symbol(lines, i).split("::")[-1])
                blocks.append(("function", symbol, i + 1, fend + 1))
                i = fend + 1
                continue
        overview_end = i  # declarations and one-line inlines stay in overview
        i += 1
    if overview_end > start:
        blocks.insert(0, (kind, name + " (overview)", start + 1,
                          overview_end + 1))
    return blocks


def _looks_like_function_def(lines, i):
    line = lines[i]
    if "(" not in line or _CONTROL.match(line):
        return False
    head = line.split("(")[0]
    if not head.strip() or head.strip().startswith(("*", ".")):
        return False
    if line.rstrip().endswith(";"):
        return False
    # A definition opens its body within the next couple of lines.
    for j in range(i, min(i + 3, len(lines))):
        if "{" in lines[j]:
            return True
        if lines[j].rstrip().endswith(";"):
            return False
    return False


def _match_brace(lines, start):
    """Index of the line where the block opened at `start` closes."""
    depth = 0
    seen_open = False
    for i in range(start, len(lines)):
        # Strip line comments before counting; heuristics only.
        code = lines[i].split("//")[0]
        depth += code.count("{")
        if "{" in code:
            seen_open = True
        depth -= code.count("}")
        if seen_open and depth <= 0:
            return i
    return len(lines) - 1


def _merge_small_misc(blocks):
    """Adjacent file-scope fragments collapse into one chunk."""
    merged = []
    for block in blocks:
        if (merged and block[0] == "file scope" and merged[-1][0] == "file scope"
                and block[2] - merged[-1][3] <= 3):
            prev = merged[-1]
            merged[-1] = (prev[0], prev[1], prev[2], block[3])
        else:
            merged.append(block)
    return merged


# ---------------------------------------------------------------------------
# Chunk emission with size cap and fixed-line fallback.
# ---------------------------------------------------------------------------

def _emit(rel, module, kind, symbol, start, end, lines):
    body = lines[start - 1:end]
    text = "\n".join(body)
    if len(text) <= MAX_CHUNK_CHARS:
        return [_chunk(rel, module, kind, symbol, start, end, text)]
    # Oversized symbol: split at blank lines into numbered parts.
    parts, buf, buf_start = [], [], start
    chunks = []
    for offset, line in enumerate(body):
        if (not line.strip() and buf
                and sum(len(l) + 1 for l in buf) > MAX_CHUNK_CHARS // 2):
            parts.append((buf_start, start + offset, buf))
            buf, buf_start = [], start + offset + 1
        buf.append(line)
    if buf:
        parts.append((buf_start, end, buf))
    if len(parts) <= 1:
        # No usable blank lines: hard-wrap by line count.
        step = FALLBACK_LINES
        parts = [(start + k, min(start + k + step - 1, end),
                  body[k:k + step]) for k in range(0, len(body), step)]
    total = len(parts)
    for n, (ps, pe, plines) in enumerate(parts, 1):
        chunks.append(_chunk(rel, module, kind,
                             "%s (%d/%d)" % (symbol, n, total),
                             ps, pe, "\n".join(plines)))
    return chunks


def _fallback(rel, module, lines):
    chunks = []
    step = FALLBACK_LINES - FALLBACK_OVERLAP
    for start in range(0, len(lines), step):
        end = min(start + FALLBACK_LINES, len(lines))
        text = "\n".join(lines[start:end])
        chunks.append(_chunk(rel, module, "window", "(fixed lines)",
                             start + 1, end, text))
        if end == len(lines):
            break
    return chunks


def _chunk(rel, module, kind, symbol, start, end, text):
    anchor = "%s:L%d-L%d" % (rel, start, end)
    if symbol:
        anchor += " · %s" % symbol
    return {
        "anchor": anchor,
        "text": text[:MAX_CHUNK_CHARS],
        "symbol": symbol,
        "kind": kind,
        "start": start,
        "end": end,
        "rel_path": rel,
        "module": module,
    }


# ---------------------------------------------------------------------------
# Code structure view (页面代码结构视图): directory-containment only, built
# from the course's registered code sources (note='code') and their chunk
# anchors (rel:Lx-Ly · symbol). Skeleton files form a separate group from the
# skeletons table. No call/inference edges are derived here — containment is
# the only relation shown, and it comes from real paths.
def structure(conn, course_id, top=None):
    """Directory tree of indexed code. top=None → top-level summary with
    per-directory counts; top=<dir> → the files in that directory with their
    parsed symbols. Relations are directory containment only (实)."""
    from .db import dicts
    from . import skeletons
    skel_rows = skeletons.list_skeletons(conn, course_id=course_id)
    skel_src = {r['source_id'] for r in skel_rows}
    srcs = {r['id']: r for r in dicts(conn.execute(
        "SELECT id, title FROM sources WHERE course_id=? AND note='code'"
        " ORDER BY id", (course_id,))) if r['id'] not in skel_src}
    chunk_rows = dicts(conn.execute(
        "SELECT source_id, anchor FROM chunks WHERE source_id IN"
        " (SELECT id FROM sources WHERE course_id=? AND note='code')"
        " ORDER BY id", (course_id,)))

    def parse(anchor):
        rel, _, rest = (anchor or '').partition(':L')
        lines, _, symbol = rest.partition(' · ')
        return rel, ('L' + lines) if lines else '', symbol

    files = {}
    for c in chunk_rows:
        sid = c['source_id']
        if sid not in srcs:
            continue
        rel, lines, symbol = parse(c['anchor'])
        f = files.setdefault(sid, {'rel': rel or sid, 'chunks': 0,
                                   'symbols': []})
        f['chunks'] += 1
        if symbol:
            f['symbols'].append({'lines': lines, 'symbol': symbol})

    skel_symbols = {}
    for c in chunk_rows:
        sid = c['source_id']
        if sid not in skel_src:
            continue
        _, lines, symbol = parse(c['anchor'])
        if symbol:
            skel_symbols.setdefault(sid, []).append(
                {'lines': lines, 'symbol': symbol})

    result = {'course_id': course_id,
              'relation': '目录包含（实）',
              'skeletons': [{'id': s['id'], 'title': s['title'],
                             'state': s['state'],
                             'state_label': s['state_label'],
                             'node_id': s['node_id'],
                             'source_id': s['source_id'],
                             'symbols': skel_symbols.get(s['source_id'], [])}
                            for s in skel_rows]}
    if top is None:
        tops = {}
        for sid, f in files.items():
            name = module_of(f['rel'])
            t = tops.setdefault(name, {'name': name, 'files': 0, 'chunks': 0})
            t['files'] += 1
            t['chunks'] += f['chunks']
        result['tops'] = [tops[k] for k in sorted(tops)]
        result['has_code'] = bool(tops)
        return result
    result['top'] = top
    result['files'] = [
        {'source_id': sid, 'title': srcs[sid]['title'], 'rel': f['rel'],
         'chunks': f['chunks'], 'symbols': f['symbols']}
        for sid, f in sorted(files.items(), key=lambda kv: kv[1]['rel'])
        if module_of(f['rel']) == top]
    return result
