"""Publish reviewed Markdown through the same public facade as MCP.

Example: python scripts/publish_content_pack.py docs/content-packs/a2a-mcp.json
Use --apply to publish. A SQLite backup is made before opening the write facade.
"""
import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
import sqlite3

from learning_orchestrator.service import Orchestrator
from learning_orchestrator.db import db_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--workspace', type=Path, default=Path.cwd())
    parser.add_argument('--db', type=Path, default=None)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    root = args.workspace.resolve()
    pack = json.loads(args.manifest.read_text(encoding='utf-8'))
    docs = []
    for d in pack['documents']:
        file = (root / d['path']).resolve()
        file.relative_to(root)
        body = file.read_text(encoding='utf-8')
        docs.append({'node_id': d['node_id'], 'body': body, 'area': d.get('area', 'other'),
                     'source_refs': [{'path': d['path'], 'revision': hashlib.sha256(body.encode()).hexdigest()}]})
    if not args.apply:
        print(json.dumps({'documents': [{'node_id': d['node_id'], 'chars': len(d['body'])}
                                       for d in docs], 'apply': False}, ensure_ascii=False))
        return
    database = (args.db or db_path()).resolve()
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup = root / 'data' / 'backups' / ('before-content-' + stamp + '.db')
    backup.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as original:
        with sqlite3.connect(str(backup)) as destination:
            original.backup(destination)
    orch = Orchestrator(db=database, source_roots=[root], a2a_root=None, bagu_root=None)
    try:
        # Retry reuses the original ticket, including its pre-publication versions.
        stored = orch.conn.execute('SELECT receipt FROM review_graph_requests WHERE id=?',
                                   (pack['request_id'],)).fetchone()
        if stored:
            from learning_orchestrator import content
            if any(content.for_node(orch.conn, d['node_id'])['body'] != d['body'] for d in docs):
                raise ValueError('This request was published with different content; use a new revision request_id')
            print(json.dumps({'already_published': True, 'receipt': json.loads(stored[0]),
                              'backup': str(backup)}, ensure_ascii=False))
            return
        task = orch.prepare_content_task(operation='note', profile=pack.get('profile', 'project'),
            node_ids=[d['node_id'] for d in docs], project_id=pack.get('project_id'))
        receipt = orch.commit_content_task(request_id=pack['request_id'], ticket=task['ticket'],
            documents=docs, edges=pack.get('edges'), question_links=pack.get('question_links'))
        print(json.dumps({'receipt': receipt, 'backup': str(backup)}, ensure_ascii=False))
    finally:
        orch.close()


if __name__ == '__main__':
    main()
