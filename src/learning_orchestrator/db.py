"""SQLite persistence layer: schema, connection helpers, transaction wrapper."""

import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

# Project root = <root>/src/learning_orchestrator/db.py -> parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "learning_orchestrator.db"
DEFAULT_SOURCE_ROOT = PROJECT_ROOT / "sources"

NODE_TYPES = ("course", "module", "unit", "objective", "source", "diagnostic")
EDGE_TYPES = (
    "part_of",
    "sequence",
    "prerequisite",
    "explains",
    "contrasts_with",
    "tested_by",
    "fails_as",
)
SESSION_MODES = ("intro", "clarify", "review")
SESSION_STATUSES = ("active", "finished", "abandoned")
EVENT_TYPES = ("source_coverage", "attempt", "note", "checkpoint")
ATTEMPT_RESULTS = ("correct", "partial", "incorrect")
SOURCE_KINDS = ("url", "markdown", "text", "pdf")
PROPOSAL_KINDS = ("add_node", "update_node", "add_edge", "remove_edge")
# Implementation status of a resume claim or project feature. The point is to
# never present a plan or a demo as wired into the live request path.
CLAIM_STATUSES = (
    "implemented_and_wired",    # implemented and on the live request path
    "implemented_not_wired",    # implemented, but not on the live path
    "interface_or_example",     # only an interface, demo, or partial code
    "planned_upgrade",          # candidate upgrade, not built
    "needs_verification",       # claimed, not yet checked against the code
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id          TEXT PRIMARY KEY,
    course_id   TEXT NOT NULL,
    type        TEXT NOT NULL CHECK (type IN
        ('course','module','unit','objective','source','diagnostic')),
    title       TEXT NOT NULL,
    summary     TEXT NOT NULL DEFAULT '',
    sort_order  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS edges (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    src   TEXT NOT NULL REFERENCES nodes(id),
    dst   TEXT NOT NULL REFERENCES nodes(id),
    type  TEXT NOT NULL CHECK (type IN
        ('part_of','sequence','prerequisite','explains','contrasts_with',
         'tested_by','fails_as')),
    note  TEXT NOT NULL DEFAULT '',
    UNIQUE (src, dst, type)
);

CREATE TABLE IF NOT EXISTS sources (
    id          TEXT PRIMARY KEY,
    course_id   TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('url','markdown','text','pdf')),
    uri         TEXT NOT NULL,
    title       TEXT NOT NULL,
    lecture_ref TEXT NOT NULL DEFAULT '',
    anchor      TEXT,
    note        TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS node_sources (
    node_id   TEXT NOT NULL REFERENCES nodes(id),
    source_id TEXT NOT NULL REFERENCES sources(id),
    anchor    TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (node_id, source_id, anchor)
);

CREATE TABLE IF NOT EXISTS chunks (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL REFERENCES sources(id),
    anchor    TEXT NOT NULL DEFAULT '',
    text      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);

CREATE TABLE IF NOT EXISTS proposals (
    id         TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('pending','approved','rejected')),
    kind       TEXT NOT NULL CHECK (kind IN
        ('add_node','update_node','add_edge','remove_edge')),
    payload    TEXT NOT NULL,  -- JSON
    rationale  TEXT NOT NULL DEFAULT '',
    decided_at TEXT
);

CREATE TABLE IF NOT EXISTS graph_versions (
    version     INTEGER PRIMARY KEY AUTOINCREMENT,
    applied_at  TEXT NOT NULL,
    proposal_id TEXT REFERENCES proposals(id),
    note        TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS sessions (
    id           TEXT PRIMARY KEY,
    course_id    TEXT NOT NULL,
    root_node_id TEXT NOT NULL REFERENCES nodes(id),
    mode         TEXT NOT NULL CHECK (mode IN ('intro','clarify','review')),
    status       TEXT NOT NULL CHECK (status IN ('active','finished','abandoned')),
    started_at   TEXT NOT NULL,
    ended_at     TEXT,
    summary      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);

CREATE TABLE IF NOT EXISTS session_stack (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    node_id    TEXT NOT NULL REFERENCES nodes(id),
    pushed_at  TEXT NOT NULL,
    popped_at  TEXT,
    reason     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_stack_session ON session_stack(session_id);

CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT REFERENCES sessions(id),
    node_id    TEXT REFERENCES nodes(id),
    ts         TEXT NOT NULL,
    type       TEXT NOT NULL CHECK (type IN
        ('source_coverage','attempt','note','checkpoint')),
    payload    TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_node ON events(node_id, type);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);

CREATE TABLE IF NOT EXISTS misconceptions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id     TEXT NOT NULL REFERENCES nodes(id),
    session_id  TEXT REFERENCES sessions(id),
    created_at  TEXT NOT NULL,
    text        TEXT NOT NULL,
    signature   TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL CHECK (status IN ('open','resolved')),
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_misc_node ON misconceptions(node_id, status);

CREATE TABLE IF NOT EXISTS lesson_artifacts (
    node_id    TEXT NOT NULL REFERENCES nodes(id),
    mode       TEXT NOT NULL CHECK (mode IN ('intro','clarify','review')),
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (node_id, mode)
);

CREATE TABLE IF NOT EXISTS claims (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id  TEXT NOT NULL,
    node_id    TEXT REFERENCES nodes(id),
    text       TEXT NOT NULL,
    status     TEXT NOT NULL CHECK (status IN
        ('implemented_and_wired','implemented_not_wired',
         'interface_or_example','planned_upgrade','needs_verification')),
    evidence   TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claims_course ON claims(course_id);
CREATE INDEX IF NOT EXISTS idx_claims_node ON claims(node_id);
"""

FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, content='chunks', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;
"""


def db_path():
    """Resolve the database path: env override, else <project>/data/."""
    env = os.environ.get("LEARNING_ORCHESTRATOR_DB")
    if env:
        return Path(env)
    return DEFAULT_DB_PATH


def connect(path=None):
    """Open (creating if needed) a database with the full schema applied."""
    path = Path(path) if path else db_path()
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _init_fts(conn)
    return conn


def _init_fts(conn):
    """Create the FTS5 index if this SQLite build supports it."""
    try:
        conn.executescript(FTS_SCHEMA)
    except sqlite3.OperationalError:
        pass  # sources.py falls back to LIKE search


def fts_available(conn):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunks_fts'"
    ).fetchone()
    return row is not None


@contextmanager
def transaction(conn):
    """Commit on success, roll back on any exception."""
    if conn.in_transaction:
        # A facade can combine existing knowledge/review writes atomically.
        savepoint = 'nested_' + uuid.uuid4().hex
        conn.execute('SAVEPOINT ' + savepoint)
        try:
            yield conn
            conn.execute('RELEASE SAVEPOINT ' + savepoint)
        except Exception:
            conn.execute('ROLLBACK TO SAVEPOINT ' + savepoint)
            conn.execute('RELEASE SAVEPOINT ' + savepoint)
            raise
        return
    try:
        conn.execute("BEGIN")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def dicts(rows):
    return [dict(r) for r in rows]
