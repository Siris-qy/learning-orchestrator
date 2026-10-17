"""Local dashboard: stdlib HTTP server, plain HTML/CSS/JS, no build step.

Read-only JSON API + static files. Run:
    python -m learning_orchestrator.dashboard [--port 8745]
"""

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .db import PROJECT_ROOT
from .graph import ValidationError
from .service import Orchestrator

STATIC_DIR = PROJECT_ROOT / "dashboard_static"


class DashboardServer(HTTPServer):
    # On Windows SO_REUSEADDR allows two servers to bind the same port,
    # causing the browser to alternate between old and new API versions.
    allow_reuse_address = os.name != 'nt'
    request_timeout = 2.0

    def get_request(self):
        connection, address = super().get_request()
        # Browsers can pre-open a socket without sending an HTTP request.
        # Bound idle reads so one such socket cannot monopolize this server
        # (and its single-threaded SQLite connection) indefinitely.
        connection.settimeout(self.request_timeout)
        return connection, address

_MIME = {".html": "text/html; charset=utf-8", ".css": "text/css",
         ".js": "text/javascript", ".png":"image/png", ".jpg":"image/jpeg",
         ".jpeg":"image/jpeg", ".webp":"image/webp", ".gif":"image/gif",
         ".woff2":"font/woff2", ".woff":"font/woff", ".ttf":"font/ttf"}


def make_handler(orch):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the console quiet
            pass

        def _send_json(self, obj, status=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_static(self, path):
            if not path or path.endswith("/"):
                path += "index.html"
            target = (STATIC_DIR / path.lstrip("/")).resolve()
            if not str(target).startswith(str(STATIC_DIR.resolve())) \
                    or not target.is_file():
                self.send_error(404)
                return
            body = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type",
                             _MIME.get(target.suffix, "application/octet-stream"))
            # Local single-user dashboard: always revalidate so edits to
            # app.js/style.css show up on a plain refresh (no build step,
            # no versioned asset names).
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            qs = parse_qs(url.query)
            one = lambda k, d=None: qs.get(k, [d])[0]
            try:
                if url.path == "/api/review_catalog":
                    from . import review_views
                    self._send_json(review_views.catalog(orch.conn,one('project_id')))
                elif url.path == '/api/workflow':
                    self._send_json(orch.get_workflow_contract(one('operation')))
                elif url.path == '/api/workflow_board':
                    self._send_json(orch.get_workflow_board(one('project_id', '')))
                elif url.path == '/api/workflow_task':
                    self._send_json(orch.get_workflow_task(one('document_id', '')))
                elif url.path == '/api/documents':
                    self._send_json(orch.list_documents(project_id=one('project_id'), kind=one('kind'),
                        query=one('query', ''), offset=one('offset', 0), limit=one('limit', 60)))
                elif url.path == '/api/document':
                    self._send_json(orch.read_document(document_id=one('id', ''), version=one('version'),
                        start_line=one('start_line', 1), end_line=one('end_line'),
                        page_start=one('page_start', 1), page_end=one('page_end'),
                        anchor=one('anchor'), max_chars=one('max_chars', 12000)))
                elif url.path == '/api/document/versions':
                    self._send_json(orch.document_versions(one('id', '')))
                elif url.path == '/api/review_batches':
                    self._send_json(orch.list_review_batches(one('project_id')))
                elif url.path == '/api/review_batch':
                    self._send_json(orch.get_review_batch(one('id', '')))
                elif url.path == '/api/review_batch/export':
                    selected = one('node_ids')
                    self._send_json(orch.export_review_batch(one('id', ''),
                        node_ids=selected.split(',') if selected else None,
                        include_answers=one('answers') == '1'))
                elif url.path == "/api/review_detail":
                    self._send_json(orch.get_review_detail(one('id', ''),one('project_id'),one('top_k', 5)))
                elif url.path == "/api/question_inventory":
                    from . import question_links
                    self._send_json(question_links.inventory(orch.conn,one('text',''),one('state',''),one('offset',0),one('limit',80),one('category','')))
                elif url.path == "/api/courses":
                    self._send_json(orch.list_courses())
                elif url.path == "/api/meta":
                    self._send_json(orch.meta())
                elif url.path == "/api/dashboard":
                    self._send_json(orch.get_dashboard(one("course_id")))
                elif url.path == "/api/graph":
                    types = one("edge_types")
                    self._send_json(orch.get_graph(
                        one("course_id"),
                        types.split(",") if types else None))
                elif url.path == "/api/node":
                    self._send_json(orch.get_node_detail(one("id")))
                elif url.path == "/api/sessions":
                    self._send_json(orch.recent_sessions(one("course_id")))
                elif url.path == "/api/next":
                    self._send_json(orch.suggest_next_action(one("course_id")))
                elif url.path == "/api/teaching":
                    self._send_json(orch.get_teaching_state(one("course_id")))
                elif url.path == "/api/teaching_tree":
                    self._send_json(orch.get_teaching_tree(one("course_id")))
                elif url.path == "/api/learning_tree":
                    self._send_json(orch.get_learning_tree(one("course_id")))
                elif url.path == "/api/code_structure":
                    self._send_json(orch.code_structure(
                        one("course_id"), top=one("top")))
                elif url.path == "/api/code_map":
                    self._send_json(orch.get_code_map(one("course_id"))
                                    or {"components": [], "connections": []})
                elif url.path == "/api/knowledge":
                    self._send_json(orch.knowledge_catalog(one("course_id")))
                elif url.path == "/api/library":
                    self._send_json(orch.knowledge_library())
                elif url.path == "/api/knowledge_points":
                    self._send_json(orch.search_knowledge_points(one("q"), limit=100))
                elif url.path == "/api/knowledge_point":
                    self._send_json(orch.get_knowledge_point(one("id")))
                elif url.path == "/api/review_map":
                    self._send_json(orch.get_review_map(
                        root_id=one('root_id'), project_id=one('project_id'),
                        domains=one('domains').split(',') if one('domains') else None,
                        learning_status=one('learning_status'), mastery=one('mastery'),
                        include_extensions=one('include_extensions') == '1',
                        dependency_expansion=one('dependency_expansion', 'reference'),
                        cursor=int(one('cursor', 0)), limit=int(one('limit', 100))))
                elif url.path == "/api/review_node":
                    self._send_json(orch.get_review_node(
                        one('id'), context_edge_id=one('context_edge_id'),
                        include_content=one('content') == '1'))
                elif url.path == "/api/question":
                    self._send_json(orch.get_question_detail(one('id')))
                elif url.path == "/api/review_graph_today":
                    self._send_json(orch.review_graph_today(
                        project_id=one('project_id'),
                        domains=one('domains').split(',') if one('domains') else None))
                elif url.path == "/api/wiki":
                    self._send_json(orch.get_knowledge_block(one("id"), include_history=one("history") == "1"))
                elif url.path == "/api/knowledge_connections":
                    self._send_json(orch.knowledge_connections(one("course_id"), one("point_id")))
                elif url.path == "/api/knowledge_item":
                    self._send_json(orch.knowledge_item(
                        one("course_id"), one("id")))
                elif url.path == "/api/claims":
                    self._send_json(orch.list_claims(
                        course_id=one("course_id"), status=one("status")))
                elif url.path == "/api/sources":
                    rows = orch.list_sources(one("course_id"))
                    counts = {r[0]: r[1] for r in orch.conn.execute(
                        "SELECT source_id, COUNT(*) FROM chunks GROUP BY source_id")}
                    self._send_json([
                        {"id": s["id"], "title": s["title"], "kind": s["kind"],
                         "lecture_ref": s["lecture_ref"], "note": s["note"],
                         "chunks": counts.get(s["id"], 0)} for s in rows])
                elif url.path == "/api/review":
                    course = one("course_id")
                    self._send_json({
                        "overview": orch.review_overview(course),
                        "today": orch.review_today(course)})
                elif url.path == "/api/cockpit":
                    self._send_json(orch.review_cockpit(one("course_id")))
                elif url.path.startswith("/api/"):
                    self._send_json({"error": "unknown endpoint"}, 404)
                else:
                    self._send_static(url.path)
            except (ValidationError, TypeError, ValueError) as exc:
                self._send_json({"error": str(exc)}, 400)
            except Exception as exc:  # noqa: BLE001 - never crash the server
                self._send_json({"error": "internal: %s" % exc}, 500)

        def do_POST(self):
            # Local graph writes use the same facade as teaching AI tools.
            url = urlparse(self.path)
            try:
                content_actions = {'/api/content/prepare': orch.prepare_content_task,
                                   '/api/content/commit': orch.commit_content_task,
                                   '/api/review_batch/save': orch.save_review_batch,
                                   '/api/review_record/prepare': orch.prepare_review_record,
                                   '/api/review_record/commit': orch.commit_review_record,
                                   '/api/questions/commit': orch.commit_question_batch,
                                   '/api/workflow/prepare': orch.prepare_workflow,
                                   '/api/workflow/commit': orch.commit_workflow,
                                   '/api/workflow_controls/save': orch.save_workflow_controls,
                                   '/api/workflow_constraints/save': orch.save_constraint_module,
                                   '/api/workflow_task/save': orch.save_workflow_task,
                                   '/api/document/save': orch.save_document}
                if url.path in content_actions:
                    length = int(self.headers.get('Content-Length') or 0)
                    payload = json.loads(self.rfile.read(length) or b'{}')
                    self._send_json(content_actions[url.path](**payload))
                elif url.path in ('/api/review_map', '/api/review_assessment'):
                    length = int(self.headers.get('Content-Length') or 0)
                    payload = json.loads(self.rfile.read(length) or b'{}')
                    if not isinstance(payload, dict):
                        raise ValidationError('Request body must be an object')
                    fn = orch.commit_review_map if url.path == '/api/review_map' else orch.record_review_assessment
                    self._send_json(fn(**payload))
                elif url.path == "/api/resolve_review_mentions":
                    length = int(self.headers.get('Content-Length') or 0)
                    payload = json.loads(self.rfile.read(length) or b'{}')
                    self._send_json(orch.resolve_review_mentions(**payload))
                elif url.path == "/api/cockpit/judgment":
                    length = int(self.headers.get("Content-Length") or 0)
                    payload = json.loads(self.rfile.read(length) or b"{}")
                    result = payload.get("result")
                    gap = (payload.get("gap_note") or "").strip()
                    if result == "deepen" and not gap:
                        raise ValidationError("需要深入必须记录具体缺口")
                    self._send_json(orch.record_question_judgment(
                        payload.get("question_id", ""), result, gap,
                        origin="cockpit"))
                else:
                    self._send_json({"error": "unknown endpoint"}, 404)
            except (ValidationError, TypeError, ValueError, KeyError,
                    json.JSONDecodeError) as exc:
                self._send_json({"error": str(exc)}, 400)
            except Exception as exc:  # noqa: BLE001 - never crash the server
                self._send_json({"error": "internal: %s" % exc}, 500)

    return Handler


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Learning Orchestrator dashboard")
    parser.add_argument("--port", type=int, default=8745)
    parser.add_argument("--db", default=None)
    parser.add_argument("--workspace", default=None)
    args = parser.parse_args(argv)

    orch = Orchestrator(db=args.db, workspace=args.workspace)
    orch.initialize()
    # One local learner and a read-only dashboard do not need concurrent
    # request threads. Keeping requests on the creator thread also preserves
    # sqlite3's default thread-safety boundary for this shared connection.
    server = DashboardServer(("127.0.0.1", args.port), make_handler(orch))
    print("Dashboard at http://127.0.0.1:%d  (Ctrl+C to stop)" % args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        orch.close()


if __name__ == "__main__":
    main()
