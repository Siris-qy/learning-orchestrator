"""Learning sessions: start/resume/push/pop/finish plus append-only events.

A session has a root goal node and a stack of nodes being studied. Pushing
lets the learner dive into a prerequisite temporarily; popping returns to the
parent. All activity is recorded as append-only events; progress is *derived*
from those events (see progress.py), never written directly.
"""

import json
import uuid

from .db import (
    ATTEMPT_RESULTS, EVENT_TYPES, SESSION_MODES, dicts, transaction,
)
from .graph import ValidationError, get_node, now_iso, node_exists


def _require(cond, msg):
    if not cond:
        raise ValidationError(msg)


def _new_id(prefix):
    return prefix + "-" + uuid.uuid4().hex[:12]


def _active_stack(conn, session_id):
    """Stack entries not yet popped, in push order (bottom first)."""
    return dicts(conn.execute(
        "SELECT * FROM session_stack WHERE session_id = ? AND popped_at IS NULL"
        " ORDER BY id",
        (session_id,),
    ))


def _current_entry(conn, session_id):
    stack = _active_stack(conn, session_id)
    return stack[-1] if stack else None


def _get_session(conn, session_id):
    row = conn.execute(
        "SELECT * FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    _require(row is not None, "unknown session id: %r" % session_id)
    return dict(row)


def _log_event(conn, session_id, node_id, type, payload):
    _require(type in EVENT_TYPES, "invalid event type: %r" % type)
    conn.execute(
        "INSERT INTO events (session_id, node_id, ts, type, payload)"
        " VALUES (?,?,?,?,?)",
        (session_id, node_id, now_iso(), type,
         json.dumps(payload or {}, ensure_ascii=False)),
    )


def start_session(conn, course_id, root_node_id, mode, goal=""):
    _require(mode in SESSION_MODES, "invalid session mode: %r" % mode)
    _require(node_exists(conn, root_node_id),
             "unknown root node: %r" % root_node_id)
    session_id = _new_id("sess")
    ts = now_iso()
    with transaction(conn):
        conn.execute(
            "INSERT INTO sessions (id, course_id, root_node_id, mode, status,"
            " started_at) VALUES (?,?,?,?, 'active', ?)",
            (session_id, course_id, root_node_id, mode, ts),
        )
        conn.execute(
            "INSERT INTO session_stack (session_id, node_id, pushed_at, reason)"
            " VALUES (?,?,?,?)",
            (session_id, root_node_id, ts, goal or "session root"),
        )
        _log_event(conn, session_id, root_node_id, "checkpoint",
                   {"action": "start", "goal": goal})
    return session_id


def _require_active(conn, session_id):
    session = _get_session(conn, session_id)
    _require(session["status"] == "active",
             "session %s is %s" % (session_id, session["status"]))
    return session


def push_node(conn, session_id, node_id, reason=""):
    _require_active(conn, session_id)
    _require(node_exists(conn, node_id), "unknown node: %r" % node_id)
    with transaction(conn):
        conn.execute(
            "INSERT INTO session_stack (session_id, node_id, pushed_at, reason)"
            " VALUES (?,?,?,?)",
            (session_id, node_id, now_iso(), reason),
        )
        _log_event(conn, session_id, node_id, "checkpoint",
                   {"action": "push", "reason": reason})
    return resume_session(conn, session_id)


def pop_node(conn, session_id, reason=""):
    """Pop the current node. The root cannot be popped; finish instead."""
    _require_active(conn, session_id)
    entry = _current_entry(conn, session_id)
    _require(entry is not None, "session stack is empty")
    session = _get_session(conn, session_id)
    _require(entry["node_id"] != session["root_node_id"],
             "cannot pop the session root; finish the session instead")
    with transaction(conn):
        conn.execute(
            "UPDATE session_stack SET popped_at = ? WHERE id = ?",
            (now_iso(), entry["id"]),
        )
        _log_event(conn, session_id, entry["node_id"], "checkpoint",
                   {"action": "pop", "reason": reason})
    return resume_session(conn, session_id)


def finish_session(conn, session_id, summary="", abandon=False):
    session = _require_active(conn, session_id)
    ts = now_iso()
    status = "abandoned" if abandon else "finished"
    with transaction(conn):
        conn.execute(
            "UPDATE session_stack SET popped_at = ?"
            " WHERE session_id = ? AND popped_at IS NULL",
            (ts, session_id),
        )
        conn.execute(
            "UPDATE sessions SET status = ?, ended_at = ?, summary = ?"
            " WHERE id = ?",
            (status, ts, summary, session_id),
        )
        _log_event(conn, session_id, session["root_node_id"], "checkpoint",
                   {"action": status, "summary": summary})
    return {"session_id": session_id, "status": status}


def record_note(conn, session_id, node_id, text, batch_id=None, record_kind=None):
    _require_active(conn, session_id)
    _require(node_exists(conn, node_id), "unknown node: %r" % node_id)
    payload = {"text": text}
    if batch_id is not None:
        payload["batch_id"] = batch_id
    if record_kind:
        payload["record_kind"] = record_kind
    with transaction(conn):
        _log_event(conn, session_id, node_id, "note", payload)


def record_source_coverage(conn, session_id, node_id, source_id, anchor=""):
    """Mark that the learner covered (part of) a source at a node."""
    _require_active(conn, session_id)
    _require(node_exists(conn, node_id), "unknown node: %r" % node_id)
    src = conn.execute(
        "SELECT 1 FROM sources WHERE id = ?", (source_id,)
    ).fetchone()
    _require(src is not None, "unknown source id: %r" % source_id)
    with transaction(conn):
        _log_event(conn, session_id, node_id, "source_coverage",
                   {"source_id": source_id, "anchor": anchor})


def record_attempt(conn, session_id, node_id, result, hint_level=0,
                   response_summary="", mistake_signatures=None,
                   batch_id=None, record_kind=None):
    """Record a recall/exercise attempt. This is evidence, not a verdict."""
    _require_active(conn, session_id)
    _require(node_exists(conn, node_id), "unknown node: %r" % node_id)
    _require(result in ATTEMPT_RESULTS, "invalid attempt result: %r" % result)
    _require(isinstance(hint_level, int) and 0 <= hint_level <= 3,
             "hint_level must be an integer 0..3")
    payload = {
        "result": result,
        "hint_level": hint_level,
        "response_summary": response_summary,
        "mistake_signatures": list(mistake_signatures or []),
    }
    if batch_id is not None:
        payload["batch_id"] = batch_id
    if record_kind:
        payload["record_kind"] = record_kind
    with transaction(conn):
        _log_event(conn, session_id, node_id, "attempt", payload)


def record_misconception(conn, session_id, node_id, text, signature=""):
    _require_active(conn, session_id)
    _require(node_exists(conn, node_id), "unknown node: %r" % node_id)
    _require(text and text.strip(), "misconception text must not be empty")
    with transaction(conn):
        cur = conn.execute(
            "INSERT INTO misconceptions (node_id, session_id, created_at,"
            " text, signature, status) VALUES (?,?,?,?,?, 'open')",
            (node_id, session_id, now_iso(), text.strip(), signature),
        )
        _log_event(conn, session_id, node_id, "note",
                   {"kind": "misconception", "text": text.strip()})
    return cur.lastrowid


def resolve_misconception(conn, misconception_id):
    row = conn.execute(
        "SELECT status FROM misconceptions WHERE id = ?", (misconception_id,)
    ).fetchone()
    _require(row is not None, "unknown misconception id: %r" % misconception_id)
    _require(row["status"] == "open", "misconception already resolved")
    with transaction(conn):
        conn.execute(
            "UPDATE misconceptions SET status = 'resolved', resolved_at = ?"
            " WHERE id = ?",
            (now_iso(), misconception_id),
        )


def find_active_session(conn, course_id=None):
    sql = ("SELECT * FROM sessions WHERE status = 'active'")
    params = []
    if course_id:
        sql += " AND course_id = ?"
        params.append(course_id)
    sql += " ORDER BY started_at DESC LIMIT 1"
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def resume_session(conn, session_id=None, course_id=None):
    """Describe where a session stands and what to do next.

    Returns None if there is no matching active session.
    """
    if session_id:
        session = _get_session(conn, session_id)
        if session["status"] != "active":
            return None
    else:
        session = find_active_session(conn, course_id)
        if session is None:
            return None
    sid = session["id"]
    stack = _active_stack(conn, sid)
    current = stack[-1] if stack else None
    root = get_node(conn, session["root_node_id"])

    last_event = conn.execute(
        "SELECT * FROM events WHERE session_id = ? ORDER BY id DESC LIMIT 1",
        (sid,),
    ).fetchone()

    node_ids = [e["node_id"] for e in stack]
    open_misc = []
    if node_ids:
        q = ",".join("?" * len(node_ids))
        open_misc = dicts(conn.execute(
            "SELECT * FROM misconceptions WHERE status = 'open'"
            " AND node_id IN (%s) ORDER BY id" % q, node_ids))

    return {
        "session_id": sid,
        "mode": session["mode"],
        "status": session["status"],
        "root_goal": {"id": root["id"], "title": root["title"],
                      "summary": root["summary"]},
        "current_node": _node_brief(conn, current["node_id"]) if current else None,
        "stack": [_node_brief(conn, e["node_id"]) for e in stack],
        "open_questions": [
            {"id": m["id"], "node_id": m["node_id"], "text": m["text"]}
            for m in open_misc
        ],
        "last_activity": (
            {"ts": last_event["ts"], "type": last_event["type"],
             "payload": json.loads(last_event["payload"])}
            if last_event else None
        ),
        "suggested_next_action": _suggest_for_session(conn, session, current,
                                                      open_misc),
    }


def _node_brief(conn, node_id):
    n = get_node(conn, node_id)
    return {"id": n["id"], "type": n["type"], "title": n["title"]}


def _suggest_for_session(conn, session, current, open_misc):
    if current is None:
        return "finish the session; the stack is empty"
    if open_misc:
        m = open_misc[0]
        return ("clarify open misconception on %s: %s"
                % (m["node_id"], m["text"][:80]))
    attempted = conn.execute(
        "SELECT 1 FROM events WHERE session_id = ? AND node_id = ?"
        " AND type = 'attempt' LIMIT 1",
        (session["id"], current["node_id"]),
    ).fetchone()
    if attempted is None:
        return ("continue: build a context pack for %s and check understanding"
                % current["node_id"])
    return "continue: move to the next unstudied node or finish the session"


def recent_sessions(conn, course_id=None, limit=10):
    sql = ("SELECT s.*, n.title AS root_title FROM sessions s"
           " JOIN nodes n ON n.id = s.root_node_id")
    params = []
    if course_id:
        sql += " WHERE s.course_id = ?"
        params.append(course_id)
    sql += " ORDER BY s.started_at DESC LIMIT ?"
    params.append(limit)
    out = dicts(conn.execute(sql, params))
    for s in out:
        s["event_count"] = conn.execute(
            "SELECT COUNT(*) AS c FROM events WHERE session_id = ?",
            (s["id"],),
        ).fetchone()["c"]
        activity = dicts(conn.execute(
            "SELECT e.node_id, n.title, COUNT(*) AS count"
            " FROM events e JOIN nodes n ON n.id = e.node_id"
            " WHERE e.session_id = ? GROUP BY e.node_id, n.title"
            " ORDER BY MIN(e.id)",
            (s["id"],),
        ))
        s["activity_nodes"] = activity
        current_id = None
        if s["status"] == "active":
            workspace = conn.execute(
                "SELECT section_id FROM teaching_workspace WHERE course_id=?",
                (s["course_id"],),
            ).fetchone()
            current_id = workspace["section_id"] if workspace else None
        if not current_id and activity:
            current_id = activity[-1]["node_id"]
        if current_id:
            current = conn.execute(
                "SELECT title FROM nodes WHERE id=?", (current_id,)
            ).fetchone()
            s["current_title"] = current["title"] if current else s["root_title"]
        else:
            s["current_title"] = s["root_title"]
    return out


def session_timeline(conn, session_id, limit=50):
    _get_session(conn, session_id)
    rows = dicts(conn.execute(
        "SELECT * FROM events WHERE session_id = ? ORDER BY id DESC LIMIT ?",
        (session_id, limit),
    ))
    for r in rows:
        r["payload"] = json.loads(r["payload"])
    return rows


def last_attempts_by_node(conn, course_id):
    """Latest attempt event per objective node in a course."""
    rows = conn.execute(
        "SELECT e.node_id, e.ts, e.payload FROM events e"
        " JOIN nodes n ON n.id = e.node_id"
        " WHERE e.type = 'attempt' AND n.course_id = ?"
        " ORDER BY e.id",
        (course_id,),
    ).fetchall()
    latest = {}
    for r in rows:
        latest[r["node_id"]] = {"ts": r["ts"], **json.loads(r["payload"])}
    return latest
