"""Progress derived from append-only events. No stored mastery percentages.

Transparent rules (also documented in README.md):

- source_coverage: fraction of attached (node, source) pairs that have at
  least one source_coverage event. An attachment counts once no matter how
  many times it was revisited.
- demonstrated progress: an objective is "demonstrated" iff its most recent
  attempt has result 'correct' with hint_level <= 1 (no hint or a small
  nudge). Latest attempt 'partial' => "in_progress"; 'incorrect' (or an open
  misconception) => "struggling"; no attempts => "untouched".
- review_due: objectives that are demonstrated but whose latest attempt is
  older than REVIEW_INTERVAL_DAYS, or whose latest attempt was not clean.
"""

from datetime import datetime, timedelta, timezone

from .db import dicts

REVIEW_INTERVAL_DAYS = 7


def objective_statuses(conn, course_id):
    """Per-objective derived status from latest attempt + open misconceptions."""
    objectives = dicts(conn.execute(
        "SELECT id, title FROM nodes WHERE course_id = ? AND type = 'objective'"
        " ORDER BY sort_order, id", (course_id,)))
    latest = {}
    rows = conn.execute(
        "SELECT e.node_id, e.ts, e.payload FROM events e"
        " JOIN nodes n ON n.id = e.node_id"
        " WHERE e.type = 'attempt' AND n.course_id = ? ORDER BY e.id",
        (course_id,)).fetchall()
    import json
    for r in rows:
        latest[r["node_id"]] = (r["ts"], json.loads(r["payload"]))
    open_misc = {
        r["node_id"] for r in conn.execute(
            "SELECT DISTINCT m.node_id FROM misconceptions m"
            " JOIN nodes n ON n.id = m.node_id"
            " WHERE m.status = 'open' AND n.course_id = ?", (course_id,))
    }
    out = {}
    for obj in objectives:
        nid = obj["id"]
        ts_payload = latest.get(nid)
        if ts_payload is None:
            status = "untouched"
            last_ts, hint, result = None, None, None
        else:
            last_ts, p = ts_payload
            result, hint = p.get("result"), p.get("hint_level", 0)
            if result == "correct" and hint <= 1:
                status = "demonstrated"
            elif result == "partial":
                status = "in_progress"
            else:
                status = "struggling"
        if nid in open_misc and status == "demonstrated":
            status = "struggling"
        out[nid] = {
            "node_id": nid, "title": obj["title"], "status": status,
            "last_attempt_ts": last_ts, "last_result": result,
            "last_hint_level": hint,
        }
    return out


def source_coverage(conn, course_id):
    """Coverage of attached sources, derived from source_coverage events."""
    total = conn.execute(
        "SELECT COUNT(*) AS c FROM node_sources ns JOIN nodes n"
        " ON n.id = ns.node_id WHERE n.course_id = ?", (course_id,)
    ).fetchone()["c"]
    covered = conn.execute(
        "SELECT COUNT(*) AS c FROM ("
        "  SELECT DISTINCT ns.node_id, ns.source_id FROM node_sources ns"
        "  JOIN nodes n ON n.id = ns.node_id"
        "  JOIN events e ON e.node_id = ns.node_id AND e.type = 'source_coverage'"
        "    AND json_extract(e.payload, '$.source_id') = ns.source_id"
        "  WHERE n.course_id = ?)", (course_id,),
    ).fetchone()["c"]
    return {
        "attached": total,
        "covered": covered,
        "ratio": (covered / total) if total else 0.0,
    }


def chapter_progress(conn, course_id):
    """Section-level (unit) pass count, shown alongside the strict objective
    stats (TODO §8.5 dual-track display). Unit-level attempts never feed the
    objective counts; this is a separate, honest column."""
    import json
    units = dicts(conn.execute(
        "SELECT id, title FROM nodes WHERE course_id = ? AND type = 'unit'"
        " ORDER BY sort_order, id", (course_id,)))
    latest = {}
    rows = conn.execute(
        "SELECT e.node_id, e.payload FROM events e"
        " JOIN nodes n ON n.id = e.node_id"
        " WHERE e.type = 'attempt' AND n.course_id = ?"
        "   AND n.type = 'unit' ORDER BY e.id", (course_id,)).fetchall()
    for r in rows:
        latest[r["node_id"]] = json.loads(r["payload"])
    chapters = []
    passed = 0
    for u in units:
        p = latest.get(u["id"])
        ok = bool(p and p.get("result") == "correct"
                  and p.get("hint_level", 0) <= 1)
        passed += ok
        chapters.append({"node_id": u["id"], "title": u["title"],
                         "status": "passed" if ok else "not_passed"})
    return {"total": len(units), "passed": passed, "chapters": chapters}


def review_due_count(conn, course_id, now=None):
    due = review_due_list(conn, course_id, now=now)
    return len(due)


def review_due_list(conn, course_id, now=None):
    statuses = objective_statuses(conn, course_id)
    now = now or datetime.now(timezone.utc)
    due = []
    for nid, st in statuses.items():
        if st["status"] == "untouched":
            continue
        ts = datetime.fromisoformat(st["last_attempt_ts"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        stale = (now - ts) > timedelta(days=REVIEW_INTERVAL_DAYS)
        if st["status"] != "demonstrated" or stale:
            due.append(st)
    return due


def dashboard(conn, course_id):
    """Aggregate view for the dashboard cards and the MCP tool."""
    from .sessions import find_active_session, resume_session

    cov = source_coverage(conn, course_id)
    statuses = objective_statuses(conn, course_id)
    counts = {"untouched": 0, "in_progress": 0, "struggling": 0,
              "demonstrated": 0}
    for st in statuses.values():
        counts[st["status"]] += 1
    total_obj = len(statuses)
    active = find_active_session(conn, course_id)
    # Events and teaching updates are different records, not interchangeable
    # measures of mastery. Count by course, including events outside sessions.
    event_counts = {r['type']: r['count'] for r in conn.execute(
        'SELECT e.type, COUNT(*) AS count FROM events e'
        ' JOIN nodes n ON n.id=e.node_id WHERE n.course_id=? GROUP BY e.type',
        (course_id,))}
    teaching_count = conn.execute(
        'SELECT COUNT(*) FROM teaching_updates WHERE course_id=?',
        (course_id,)).fetchone()[0]
    return {
        "course_id": course_id,
        "record_counts": {"events": sum(event_counts.values()),
                          "event_types": event_counts,
                          "teaching_updates": teaching_count},
        "source_coverage": cov,
        "objective_progress": {
            "total": total_obj,
            "counts": counts,
            "demonstrated_ratio": (
                counts["demonstrated"] / total_obj if total_obj else 0.0),
        },
        "chapter_progress": chapter_progress(conn, course_id),
        "review": {
            "due_count": review_due_count(conn, course_id),
            "interval_days": REVIEW_INTERVAL_DAYS,
        },
        "active_session": resume_session(conn, course_id=course_id) if active else None,
        "node_statuses": statuses,
    }


def suggest_next_action(conn, course_id):
    """One plain-language suggestion, derived from events only."""
    from .sessions import find_active_session, resume_session

    if find_active_session(conn, course_id):
        res = resume_session(conn, course_id=course_id)
        return {
            "kind": "resume_session",
            "session_id": res["session_id"],
            "message": res["suggested_next_action"],
        }
    due = review_due_list(conn, course_id)
    if due:
        return {
            "kind": "review",
            "node_id": due[0]["node_id"],
            "message": "start a review session at %s (%s)"
                       % (due[0]["node_id"], due[0]["title"]),
        }
    statuses = objective_statuses(conn, course_id)
    if not statuses:
        # A materials-only course (e.g. registered notes) must not be
        # reported as "all objectives demonstrated".
        return {"kind": "no_objectives",
                "message": "no learning objectives registered for this course"}
    for nid, st in statuses.items():
        if st["status"] == "untouched":
            return {
                "kind": "intro",
                "node_id": nid,
                "message": "start an intro session at %s (%s)"
                           % (nid, st["title"]),
            }
    return {"kind": "done",
            "message": "all objectives demonstrated; keep reviewing to stay fresh"}


# ---------------------------------------------------------------------------
# Global learning tree (page-side composed view; the teaching AI keeps using
# the compact scenario profiles — a page needing global info does not mean the
# AI re-reads the whole tree every turn).
def learning_tree(conn, course_id):
    """Course → modules → units → objectives (+ per-unit teaching branches and
    topic records) for the global learning tree view. Structure only with
    counts; per-unit records load lazily via get_node_detail. Topics/plans are
    attributed by their recorded section_id — never by title guessing; records
    whose section no longer resolves go to 'unassigned' (待归位记录), kept
    visible, never deleted or re-labelled."""
    from . import teaching
    nodes = dicts(conn.execute(
        "SELECT id, type, title, summary, sort_order FROM nodes"
        " WHERE course_id=? ORDER BY sort_order, id", (course_id,)))
    by_id = {n['id']: n for n in nodes}
    children = {}
    for e in dicts(conn.execute(
            "SELECT src, dst FROM edges WHERE type='part_of'"
            " AND src IN (SELECT id FROM nodes WHERE course_id=?)",
            (course_id,))):
        children.setdefault(e['dst'], []).append(e['src'])
    for kids in children.values():
        kids.sort(key=lambda nid: (by_id[nid]['sort_order'], nid))

    statuses = objective_statuses(conn, course_id)
    record_counts = {r[0]: r[1] for r in conn.execute(
        'SELECT node_id, COUNT(*) FROM events WHERE node_id IS NOT NULL'
        ' GROUP BY node_id')}

    # Teaching plans and item counts per section (facts from the plan tables)
    plans = dicts(conn.execute(
        "SELECT id, section_id, version, status FROM teaching_plans"
        " WHERE course_id=? ORDER BY version DESC", (course_id,)))
    plan_items = {}
    for r in dicts(conn.execute(
            'SELECT plan_id, kind, status, COUNT(*) n FROM teaching_items'
            " WHERE status != 'retracted'"
            ' GROUP BY plan_id, kind, status')):
        plan_items.setdefault(r['plan_id'], []).append(r)
    active_plan = teaching.current_plan(conn, course_id)
    cursor = teaching._cursor(conn, course_id)
    workspace = conn.execute(
        'SELECT section_id, status FROM teaching_workspace WHERE course_id=?',
        (course_id,)).fetchone()

    # Topics per section from the update stream (merged, latest wins).
    # Attribution is by recorded section_id only: a section that resolves to a
    # UNIT of this course is attributed to that unit; anything else (removed
    # section, non-unit id, legacy import) goes to 'unassigned' (待归位记录).
    unit_ids = {n['id'] for n in nodes if n['type'] == 'unit'}
    parent_of = {src: dst for dst, srcs in children.items() for src in srcs}

    def unit_of(sid):
        """Resolve a recorded section_id to its unit via recorded part_of
        containment (facts, not title guessing). None when no unit contains
        it — such records stay unassigned, never re-labelled."""
        cur, seen = sid, set()
        while cur is not None and cur not in seen:
            seen.add(cur)
            if cur in unit_ids:
                return cur
            cur = parent_of.get(cur)
        return None

    topic_rows = dicts(conn.execute(
        'SELECT section_id, payload FROM teaching_updates WHERE course_id=?'
        ' ORDER BY id', (course_id,)))
    topics_by_section, unassigned_topics = {}, {}
    import json as _json
    for row in topic_rows:
        sid = row['section_id']
        uid = unit_of(sid)
        bucket = topics_by_section if uid else unassigned_topics
        merged = bucket.setdefault(uid or sid, {})
        for t in _json.loads(row['payload']).get('topics', []):
            merged[t['title']] = t['status']

    def unit_entry(nid):
        n = by_id[nid]
        objs = [{'id': o, 'title': by_id[o]['title'],
                 'status': statuses.get(o, {}).get('status', 'untouched')}
                for o in children.get(nid, []) if by_id[o]['type'] == 'objective']
        teach = []
        for p in plans:
            if unit_of(p['section_id']) != nid:
                continue
            counts = {'milestone': {}, 'section': {}, 'sub': {}, 'question': {}}
            for r in plan_items.get(p['id'], []):
                counts[r['kind']][r['status']] = r['n']
            teach.append({'version': p['version'], 'status': p['status'],
                          'counts': counts,
                          'active': active_plan is not None
                          and p['id'] == active_plan['id']})
        # 小点记录：与本次树同一份整理结果（主题分组 + 归档；未整理的诚实待归位）
        from . import organize
        org = organize.organized_topics(conn, course_id, nid)
        current_unit = unit_of(active_plan['section_id'] if active_plan
                               else workspace['section_id'] if workspace else None)
        return {'id': nid, 'title': n['title'], 'summary': n['summary'],
                'objectives': objs, 'teaching': teach,
                'topic_groups': org['groups'],
                'topics_unassigned': org['unassigned'],
                'records': record_counts.get(nid, 0),
                'is_current': current_unit == nid}

    modules = []
    course_node = next((n for n in nodes if n['type'] == 'course'), None)
    for mid in children.get(course_id, []):
        if by_id[mid]['type'] != 'module':
            continue
        units = [unit_entry(u) for u in children.get(mid, [])
                 if by_id[u]['type'] == 'unit']
        modules.append({'id': mid, 'title': by_id[mid]['title'],
                        'summary': by_id[mid]['summary'], 'units': units})
    top_units = [unit_entry(u) for u in children.get(course_id, [])
                 if by_id[u]['type'] == 'unit']
    # 课程级讲解规划简纲（2026-09-24）：阶段目标+待展开占位，组织层，
    # 不含未展开阶段的小项/教案，也不携带掌握推断。
    from . import organize as _org
    outline = _org.get_outline(conn, course_id)
    return {
        'course_id': course_id,
        'title': course_node['title'] if course_node else course_id,
        'outline': outline,
        'modules': modules, 'units': top_units,
        'current_section': active_plan['section_id'] if active_plan
                           else workspace['section_id'] if workspace else None,
        'cursor_item_id': cursor['item_id'] if cursor else None,
        'active_plan_id': active_plan['id'] if active_plan else None,
        'unassigned': {
            'topics': [{'section_id': sid,
                        'topics': [{'title': t, 'status': s}
                                   for t, s in sorted(items.items())]}
                       for sid, items in unassigned_topics.items()],
        },
    }
