"""build_context_pack: assemble what the desktop AI needs to tutor one node.

Modes:
- intro:   full first-contact material (node, parents/position, prereqs,
           sources, exercises) - enough to build one complete lesson.
- clarify: focused on one confusing point; only node + relevant excerpts +
           open misconceptions; do not re-teach the whole unit.
- review:  prior mistakes and fresh checks; stored response summaries are
           withheld so the learner answers before seeing old answers.
"""

import json

from .db import SESSION_MODES, dicts
from .graph import (
    ValidationError, get_node, node_exists, parents_of, prerequisites_of,
)
from .sources import search_chunks, sources_for_node

_MODE_INSTRUCTIONS = {
    "intro": (
        "Prepare ONE self-contained lesson for handoff to a chat that cannot "
        "access the repository or textbook. Include an ordered subsection "
        "outline (reuse teaching item IDs when supplied), suggested batches "
        "without a fixed count, and (1) a short "
        "overview placing it in its parent unit, (2) the core mechanism "
        "explained from the supplied source excerpts and node summaries, "
        "(3) a concrete example or code sketch where relevant, (4) "
        "boundaries: what this node does NOT cover, (5) a source index "
        "listing the anchors used, (6) suitable recall checks. Source excerpts "
        "are previews: read missing essential material before preparing the "
        "lesson. Clearly label additions beyond the sources. Saving or "
        "displaying this lesson is preparation, not learning evidence."
    ),
    "clarify": (
        "Address ONLY the focused confusion stated in 'focused_question'. "
        "Use the matched excerpts and the node's open misconceptions. Do "
        "not re-teach the whole unit; one tight explanation plus one check "
        "question is enough."
    ),
    "review": (
        "Run a review: pose fresh recall questions based on the node "
        "summary and the listed prior mistake signatures, BEFORE revealing "
        "any stored material. Stored response summaries are intentionally "
        "withheld; do not ask the tool for them. After the learner answers, "
        "record the attempt and compare against the prior mistakes."
    ),
}


def build_context_pack(conn, node_id, mode, focused_question=None):
    if mode not in SESSION_MODES:
        raise ValidationError("invalid mode: %r" % mode)
    if not node_exists(conn, node_id):
        raise ValidationError("unknown node id: %r" % node_id)

    node = get_node(conn, node_id)
    course_id = node["course_id"]
    parents = parents_of(conn, node_id)
    prereqs = prerequisites_of(conn, node_id)
    sources = sources_for_node(conn, node_id)
    open_misc = dicts(conn.execute(
        "SELECT id, text, signature, created_at FROM misconceptions"
        " WHERE node_id = ? AND status = 'open' ORDER BY id", (node_id,)))

    exercises = dicts(conn.execute(
        "SELECT n.id, n.title, n.summary FROM edges e"
        " JOIN nodes n ON n.id = e.dst"
        " WHERE e.src = ? AND e.type = 'tested_by'", (node_id,)))

    recent = dicts(conn.execute(
        "SELECT ts, payload FROM events WHERE node_id = ? AND type = 'attempt'"
        " ORDER BY id DESC LIMIT 5", (node_id,)))
    attempts = []
    for r in recent:
        p = json.loads(r["payload"])
        entry = {
            "ts": r["ts"],
            "result": p.get("result"),
            "hint_level": p.get("hint_level"),
            "mistake_signatures": p.get("mistake_signatures", []),
        }
        if mode != "review":
            # In review mode the learner must answer before seeing old answers.
            entry["response_summary"] = p.get("response_summary", "")
        attempts.append(entry)

    pack = {
        "mode": mode,
        "node": {"id": node["id"], "type": node["type"],
                 "title": node["title"], "summary": node["summary"]},
        "claims": dicts(conn.execute(
            "SELECT id, text, status, evidence FROM claims"
            " WHERE node_id = ? OR node_id = ? ORDER BY id",
            (node_id, course_id))),
        "position": {
            "parents": [{"id": p["id"], "type": p["type"],
                         "title": p["title"]} for p in parents],
        },
        "prerequisites": [
            {"id": p["id"], "title": p["title"], "summary": p["summary"]}
            for p in prereqs
        ],
        "sources": sources,
        "exercise_references": exercises,
        "open_misconceptions": open_misc,
        "recent_attempts": attempts,
        "focused_question": focused_question,
        "mode_instructions": _MODE_INSTRUCTIONS[mode],
    }

    if mode == "clarify" and focused_question:
        pack["matched_excerpts"] = search_chunks(
            conn, course_id, focused_question)
    if mode == "intro":
        pack["prerequisite_status"] = _prereq_status(conn, prereqs)
    return pack


def _prereq_status(conn, prereqs):
    """Whether each direct prerequisite has a clean latest attempt."""
    from .progress import objective_statuses
    if not prereqs:
        return []
    statuses = objective_statuses(conn, prereqs[0]["course_id"])
    return [
        {"id": p["id"], "title": p["title"],
         "status": statuses.get(p["id"], {}).get("status", "untouched")}
        for p in prereqs
    ]
