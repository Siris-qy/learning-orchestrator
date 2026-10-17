"""Seed for the 八股 notes corpus (M2.5, TODO milestones).

Registers the formal notes of 「Agent1 后端部分 · 阶段1」 as course sources
so M3's review flow works against real material and daily review can start.
Deliberately minimal per the milestone: build sources + search index ONLY —
no graph units, no edges, no parsing of the review sheet, no wholesale
attachment into teaching context packs (retrieval stays per-knowledge-point
via search_sources; the 主链/异常树 multi-view becomes graph edges in M3/M4).

The notes' own organization is preserved as metadata: each source's
lecture_ref carries its role (主链索引 / 异常树索引 / 知识块正文 / 复习总表 …),
mirroring the README's "views, not six textbooks" rule.

Idempotent: the course node is inserted once; file registration reuses the
stable source ids. If the notes directory is missing, the course node is
still seeded and registration is skipped with a warning list.
"""

import os
from pathlib import Path

from . import graph, sources
from .db import PROJECT_ROOT, transaction

COURSE_ID = "bagu-agent1-backend"

_ENV_ROOT = "LEARNING_ORCHESTRATOR_BAGU_ROOT"

# (source_id, path relative to the 正式笔记 dir, title, lecture_ref role)
_FILES = [
    ("bagu-s1-readme", "README.md", "笔记体系说明", "笔记说明"),
    ("bagu-s1-normal-chain", "01-normal-chain.md", "正常主链", "主链索引"),
    ("bagu-s1-fault-index", "02-fault-index.md", "异常排查索引", "异常树索引"),
    ("bagu-s1-full-index", "03-full-index.md", "完整链路索引", "完整索引"),
    ("bagu-s1-review", "04-review.md", "知识总表与复习记录", "复习总表"),
    ("bagu-s1-weak-points", "05-weak-points.md", "薄弱点入口", "薄弱点"),
    ("bagu-s1-editorial", "06-editorial-notes.md", "整理说明与纠错", "整理说明"),
    ("bagu-s1-project-entry", "07-project-entry.md",
     "HttpServer 项目复习入口", "项目链路索引"),
    ("bagu-s1-interview-index", "08-interview-question-index.md",
     "网络与 C++ 面经题目索引", "面试题索引"),
    ("bagu-s1-kb-network", "知识块/01-network.md",
     "网络分层、IP、端口与路由（专题1 知识块）", "知识块正文"),
    ("bagu-s1-kb-dns", "知识块/02-dns.md",
     "DNS 域名解析：角色、缓存、记录与失败区分（专题2 知识块）", "知识块正文"),
    ("bagu-s1-kb-tcp", "知识块/03-tcp.md",
     "TCP 传输控制协议：建连、可靠传输与关闭（专题3 知识块）", "知识块正文"),
    ("bagu-s1-kb-tls", "知识块/04-tls.md",
     "TLS/HTTPS：加密通道、证书信任与故障定位（专题4 知识块）", "知识块正文"),
    ("bagu-s1-kb-http", "知识块/05-http.md",
     "HTTP/1.1：报文边界、增量解析、路由与状态码、持久连接（专题5 知识块）",
     "知识块正文"),
    ("bagu-s1-kb-reactor", "知识块/06-reactor.md",
     "socket、非阻塞 IO、epoll、Reactor 与 Buffer（专题6 知识块）", "知识块正文"),
    ("bagu-s1-kb-upstream", "知识块/07-upstream.md",
     "服务间调用：HTTP、异步回包、超时与任务受理", "知识块正文"),
    ("bagu-s1-kb-project", "知识块/08-muduo-httpserver.md",
     "muduo 与 HttpServer 项目实现（M01–M08）", "项目知识块正文"),
]

_NOTES_SUBDIR = Path("Agent1后端部分") / "阶段1" / "正式笔记"


def default_corpus_root():
    env = os.environ.get(_ENV_ROOT)
    if env:
        return Path(env)
    return PROJECT_ROOT.parent / "八股学习"


def seed(conn, corpus_root=None):
    """Insert the course node, register the notes, and parse the review
    sheet into knowledge-point review items (M3). Idempotent.

    corpus_root=None seeds the course node only (no file registration, no
    review items) — used by tests and by installs where the notes are
    unavailable. Returns {seeded, course_id, registered, missing, review}.
    """
    existed = conn.execute(
        "SELECT 1 FROM nodes WHERE id = ?", (COURSE_ID,)).fetchone() is not None
    with transaction(conn):
        conn.execute(
            "INSERT OR IGNORE INTO nodes (id, course_id, type, title, summary,"
            " sort_order) VALUES (?,?,?,?,?,?)",
            (COURSE_ID, COURSE_ID, "course", "八股 · Agent1 后端基础",
             "阶段1 后端基础正式笔记：知识块正文一份，主链/异常树/完整索引为"
             "观察角度；复习状态以 04-review 复习总表为事实基准。", 0))
    result = {"seeded": not existed, "course_id": COURSE_ID,
              "registered": [], "missing": [], "review": None}
    if not corpus_root:
        return result
    notes_dir = Path(corpus_root) / _NOTES_SUBDIR
    roots = [corpus_root]
    source_by_file = {}
    for source_id, rel, title, role in _FILES:
        path = notes_dir / rel
        if not path.is_file():
            result["missing"].append(rel)
            continue
        res = sources.register_file(conn, COURSE_ID, path, roots,
                                    title=title, lecture_ref=role,
                                    source_id=source_id)
        source_by_file[rel] = source_id
        result["registered"].append(
            {"source_id": source_id, "chunks": res["chunks"],
             "reused": res.get("reused", False)})
    sheet = notes_dir / "04-review.md"
    if sheet.is_file():
        from . import review
        result["review"] = review.seed_from_sheet(conn, COURSE_ID, sheet,
                                                  source_by_file)
    return result
