"""Typed node/edge graph operations, prerequisite cycle checks, and proposals.

Graph mutations by callers (including the desktop AI) are staged as proposals.
Only `approve_proposal` applies them, transactionally, and bumps the graph
version. `seed` is the one exception: it writes the initial human-authored
graph directly at initialization time.
"""

import json
import uuid
from datetime import datetime, timezone

from .db import EDGE_TYPES, NODE_TYPES, dicts, transaction


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ValidationError(ValueError):
    pass


class CycleError(ValidationError):
    pass


def _require(cond, msg):
    if not cond:
        raise ValidationError(msg)


def node_exists(conn, node_id):
    return conn.execute(
        "SELECT 1 FROM nodes WHERE id = ?", (node_id,)
    ).fetchone() is not None


def get_node(conn, node_id):
    row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
    _require(row is not None, "unknown node id: %r" % node_id)
    return dict(row)


def add_node(conn, node_id, course_id, type, title, summary="", sort_order=0):
    _require(type in NODE_TYPES, "invalid node type: %r" % type)
    _require(title and title.strip(), "node title must not be empty")
    with transaction(conn):
        conn.execute(
            "INSERT INTO nodes (id, course_id, type, title, summary, sort_order)"
            " VALUES (?,?,?,?,?,?)",
            (node_id, course_id, type, title.strip(), summary, sort_order),
        )


def _prereq_path_exists(conn, start, goal):
    """True if a prerequisite path start -> ... -> goal already exists."""
    seen = {start}
    frontier = [start]
    while frontier:
        current = frontier.pop()
        if current == goal:
            return True
        rows = conn.execute(
            "SELECT dst FROM edges WHERE src = ? AND type = 'prerequisite'",
            (current,),
        ).fetchall()
        for r in rows:
            if r["dst"] not in seen:
                seen.add(r["dst"])
                frontier.append(r["dst"])
    return False


def check_prereq_cycle(conn, src, dst):
    """Adding prerequisite src -> dst is a cycle iff dst already reaches src."""
    if src == dst:
        raise CycleError("self prerequisite on %r" % src)
    if _prereq_path_exists(conn, dst, src):
        raise CycleError(
            "prerequisite %s -> %s would create a cycle" % (src, dst)
        )


def add_edge(conn, src, dst, type, note="", check_cycles=True):
    _require(type in EDGE_TYPES, "invalid edge type: %r" % type)
    _require(node_exists(conn, src), "unknown edge src: %r" % src)
    _require(node_exists(conn, dst), "unknown edge dst: %r" % dst)
    if type == "prerequisite" and check_cycles:
        check_prereq_cycle(conn, src, dst)
    with transaction(conn):
        conn.execute(
            "INSERT INTO edges (src, dst, type, note) VALUES (?,?,?,?)",
            (src, dst, type, note),
        )


def remove_edge(conn, src, dst, type):
    _require(type in EDGE_TYPES, "invalid edge type: %r" % type)
    with transaction(conn):
        cur = conn.execute(
            "DELETE FROM edges WHERE src = ? AND dst = ? AND type = ?",
            (src, dst, type),
        )
        _require(cur.rowcount > 0, "no such edge: %s -[%s]-> %s" % (src, type, dst))


def get_graph(conn, course_id, edge_types=None):
    """Return nodes/edges for one course, optionally filtered by edge types."""
    if edge_types:
        bad = [t for t in edge_types if t not in EDGE_TYPES]
        _require(not bad, "invalid edge types: %r" % bad)
    nodes = dicts(
        conn.execute(
            "SELECT * FROM nodes WHERE course_id = ? ORDER BY sort_order, id",
            (course_id,),
        )
    )
    sql = (
        "SELECT e.* FROM edges e JOIN nodes n ON e.src = n.id"
        " WHERE n.course_id = ?"
    )
    params = [course_id]
    if edge_types:
        sql += " AND e.type IN (%s)" % ",".join("?" * len(edge_types))
        params.extend(edge_types)
    edges = dicts(conn.execute(sql, params))
    return {"course_id": course_id, "nodes": nodes, "edges": edges}


def list_courses(conn):
    return dicts(
        conn.execute("SELECT * FROM nodes WHERE type = 'course' ORDER BY id")
    )


def parents_of(conn, node_id):
    return dicts(
        conn.execute(
            "SELECT n.* FROM edges e JOIN nodes n ON n.id = e.dst"
            " WHERE e.src = ? AND e.type = 'part_of'",
            (node_id,),
        )
    )


def prerequisites_of(conn, node_id):
    return dicts(
        conn.execute(
            "SELECT n.*, e.note AS edge_note FROM edges e"
            " JOIN nodes n ON n.id = e.src"
            " WHERE e.dst = ? AND e.type = 'prerequisite'",
            (node_id,),
        )
    )


# ---------------------------------------------------------------------------
# Proposals: staged, validated, approved transactionally with a version bump.
# ---------------------------------------------------------------------------

def _validate_payload(conn, kind, payload):
    _require(kind in ("add_node", "update_node", "add_edge", "remove_edge"),
             "invalid proposal kind: %r" % kind)
    if kind == "add_node":
        for field in ("id", "course_id", "type", "title"):
            _require(payload.get(field), "add_node payload missing %r" % field)
        _require(payload["type"] in NODE_TYPES,
                 "invalid node type: %r" % payload["type"])
    elif kind == "update_node":
        _require(payload.get("id"), "update_node payload missing 'id'")
        _require(node_exists(conn, payload["id"]),
                 "unknown node id: %r" % payload["id"])
        updatable = set(payload) - {"id"} - {"title", "summary", "sort_order"}
        _require(not updatable, "cannot update fields: %r" % sorted(updatable))
    else:  # add_edge / remove_edge
        for field in ("src", "dst", "type"):
            _require(payload.get(field), "edge payload missing %r" % field)
        _require(payload["type"] in EDGE_TYPES,
                 "invalid edge type: %r" % payload["type"])
        if kind == "add_edge":
            _require(node_exists(conn, payload["src"]),
                     "unknown edge src: %r" % payload["src"])
            _require(node_exists(conn, payload["dst"]),
                     "unknown edge dst: %r" % payload["dst"])
            if payload["type"] == "prerequisite":
                check_prereq_cycle(conn, payload["src"], payload["dst"])


def propose_change(conn, kind, payload, rationale=""):
    """Stage a graph change. Validation happens now and again at approval."""
    _validate_payload(conn, kind, payload)
    proposal_id = "prop-" + uuid.uuid4().hex[:12]
    with transaction(conn):
        conn.execute(
            "INSERT INTO proposals (id, created_at, status, kind, payload,"
            " rationale) VALUES (?,?,?,?,?,?)",
            (proposal_id, now_iso(), "pending", kind,
             json.dumps(payload, ensure_ascii=False), rationale),
        )
    return proposal_id


def list_proposals(conn, status=None):
    sql = "SELECT * FROM proposals"
    params = []
    if status:
        _require(status in ("pending", "approved", "rejected"),
                 "invalid proposal status: %r" % status)
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY created_at"
    out = dicts(conn.execute(sql, params))
    for p in out:
        p["payload"] = json.loads(p["payload"])
    return out


def approve_proposal(conn, proposal_id):
    """Apply a pending proposal transactionally and bump the graph version."""
    row = conn.execute(
        "SELECT * FROM proposals WHERE id = ?", (proposal_id,)
    ).fetchone()
    _require(row is not None, "unknown proposal id: %r" % proposal_id)
    _require(row["status"] == "pending",
             "proposal %s is already %s" % (proposal_id, row["status"]))
    kind, payload = row["kind"], json.loads(row["payload"])
    _validate_payload(conn, kind, payload)  # re-validate against current graph

    with transaction(conn):
        if kind == "add_node":
            conn.execute(
                "INSERT INTO nodes (id, course_id, type, title, summary,"
                " sort_order) VALUES (?,?,?,?,?,?)",
                (payload["id"], payload["course_id"], payload["type"],
                 payload["title"], payload.get("summary", ""),
                 payload.get("sort_order", 0)),
            )
        elif kind == "update_node":
            sets, params = [], []
            for field in ("title", "summary", "sort_order"):
                if field in payload:
                    sets.append("%s = ?" % field)
                    params.append(payload[field])
            _require(sets, "update_node payload has nothing to update")
            params.append(payload["id"])
            conn.execute(
                "UPDATE nodes SET %s WHERE id = ?" % ", ".join(sets), params)
        elif kind == "add_edge":
            conn.execute(
                "INSERT INTO edges (src, dst, type, note) VALUES (?,?,?,?)",
                (payload["src"], payload["dst"], payload["type"],
                 payload.get("note", "")),
            )
        elif kind == "remove_edge":
            cur = conn.execute(
                "DELETE FROM edges WHERE src = ? AND dst = ? AND type = ?",
                (payload["src"], payload["dst"], payload["type"]),
            )
            _require(cur.rowcount > 0, "edge no longer exists")
        conn.execute(
            "UPDATE proposals SET status = 'approved', decided_at = ?"
            " WHERE id = ?",
            (now_iso(), proposal_id),
        )
        conn.execute(
            "INSERT INTO graph_versions (applied_at, proposal_id, note)"
            " VALUES (?,?,?)",
            (now_iso(), proposal_id, "%s %s" % (kind, proposal_id)),
        )
    return proposal_id


def reject_proposal(conn, proposal_id, reason=""):
    row = conn.execute(
        "SELECT status FROM proposals WHERE id = ?", (proposal_id,)
    ).fetchone()
    _require(row is not None, "unknown proposal id: %r" % proposal_id)
    _require(row["status"] == "pending",
             "proposal %s is already %s" % (proposal_id, row["status"]))
    with transaction(conn):
        conn.execute(
            "UPDATE proposals SET status = 'rejected', decided_at = ?,"
            " rationale = rationale || ? WHERE id = ?",
            (now_iso(), (" [rejected: %s]" % reason) if reason else "",
             proposal_id),
        )
    return proposal_id


def graph_version(conn):
    row = conn.execute("SELECT MAX(version) AS v FROM graph_versions").fetchone()
    return row["v"] or 0


# ---------------------------------------------------------------------------
# Claims: resume/project statements with a verified implementation status.
# ---------------------------------------------------------------------------

def add_claim(conn, course_id, text, status, node_id=None, evidence=""):
    from .db import CLAIM_STATUSES
    _require(status in CLAIM_STATUSES, "invalid claim status: %r" % status)
    _require(text and text.strip(), "claim text must not be empty")
    if node_id is not None:
        _require(node_exists(conn, node_id), "unknown node id: %r" % node_id)
    with transaction(conn):
        cur = conn.execute(
            "INSERT INTO claims (course_id, node_id, text, status, evidence,"
            " updated_at) VALUES (?,?,?,?,?,?)",
            (course_id, node_id, text.strip(), status, evidence, now_iso()),
        )
    return cur.lastrowid


def list_claims(conn, course_id=None, node_id=None, status=None):
    from .db import CLAIM_STATUSES
    sql, params = "SELECT * FROM claims", []
    where = []
    if course_id:
        where.append("course_id = ?")
        params.append(course_id)
    if node_id:
        where.append("node_id = ?")
        params.append(node_id)
    if status:
        _require(status in CLAIM_STATUSES, "invalid claim status: %r" % status)
        where.append("status = ?")
        params.append(status)
    if where:
        sql += " WHERE " + " AND ".join(where)
    return dicts(conn.execute(sql + " ORDER BY id", params))


def set_claim_status(conn, claim_id, status, evidence=None):
    from .db import CLAIM_STATUSES
    _require(status in CLAIM_STATUSES, "invalid claim status: %r" % status)
    with transaction(conn):
        if evidence is None:
            cur = conn.execute(
                "UPDATE claims SET status = ?, updated_at = ? WHERE id = ?",
                (status, now_iso(), claim_id),
            )
        else:
            cur = conn.execute(
                "UPDATE claims SET status = ?, evidence = ?, updated_at = ?"
                " WHERE id = ?",
                (status, evidence, now_iso(), claim_id),
            )
        _require(cur.rowcount > 0, "unknown claim id: %r" % claim_id)
    return claim_id
