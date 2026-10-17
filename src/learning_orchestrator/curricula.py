"""Explicit course/project registration for empty and portable workspaces."""
from . import graph, review_graph
from .db import transaction
from .graph import ValidationError


def setup(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS curriculum_profiles(
      course_id TEXT PRIMARY KEY REFERENCES nodes(id), kind TEXT NOT NULL)''')


def kind(conn, course_id):
    row = conn.execute('SELECT kind FROM curriculum_profiles WHERE course_id=?', (course_id,)).fetchone()
    if row:
        return row[0]
    # Old workspaces did not register this metadata. Keep their display names.
    from .presentation import PROJECTS
    return 'project' if course_id in PROJECTS else 'course'


def register(conn, request_id, course_id, title, kind='course', sections=None):
    payload = dict(course_id=course_id, title=title, kind=kind, sections=sections or [])
    digest, previous = review_graph._request(conn, request_id, 'curriculum.register', payload)
    if previous is not None:
        return previous
    if kind not in ('course', 'project') or not course_id or not title.strip():
        raise ValidationError('Register a named course or project with a stable id')
    with transaction(conn):
        root = conn.execute('SELECT * FROM nodes WHERE id=?', (course_id,)).fetchone()
        if root and (root['type'] != 'course' or root['course_id'] != course_id):
            raise ValidationError('This id already identifies another object')
        if not root:
            graph.add_node(conn, course_id, course_id, 'course', title)
        else:
            conn.execute('UPDATE nodes SET title=? WHERE id=?', (title, course_id))
        conn.execute('INSERT INTO curriculum_profiles VALUES(?,?) ON CONFLICT(course_id) '
                     'DO UPDATE SET kind=excluded.kind', (course_id, kind))
        registered = []
        for index, item in enumerate(sections or []):
            nid, typ = item['id'], item.get('type', 'unit')
            if typ not in ('module', 'unit', 'objective'):
                raise ValidationError('Sections use module/unit/objective types')
            old = conn.execute('SELECT * FROM nodes WHERE id=?', (nid,)).fetchone()
            if old and (old['course_id'] != course_id or old['type'] != typ):
                raise ValidationError('Section belongs to another course or type')
            if not old:
                graph.add_node(conn, nid, course_id, typ, item['title'],
                               item.get('summary', ''), item.get('seq', index))
            else:
                conn.execute('UPDATE nodes SET title=? WHERE id=?', (item['title'], nid))
            registered.append(nid)
        for item in sections or []:
            parent = item.get('parent_id', course_id)
            if graph.get_node(conn, parent)['course_id'] != course_id:
                raise ValidationError('Parent belongs to another course')
            if not conn.execute("SELECT 1 FROM edges WHERE src=? AND dst=? AND type='part_of'",
                                (item['id'], parent)).fetchone():
                graph.add_edge(conn, item['id'], parent, 'part_of')
        if kind == 'project':
            review_graph.commit(conn, request_id + ':root', nodes=[{
                'id': course_id, 'kind': 'project', 'title': title,
                'owner_ref': {'type': 'course', 'id': course_id}}])
        return review_graph._receipt(conn, request_id, 'curriculum.register', digest,
                                    {'success': True, 'course_id': course_id, 'sections': registered})
