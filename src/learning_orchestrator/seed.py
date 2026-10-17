"""Human-authored seed for the first CMU 15-445/645 learning slices.

The summaries are original navigation text, not copied slide prose. Official
URLs identify the source material; local PDF ingestion is handled separately
by ``scripts/prepare_cmu_l01.py``.
"""

from . import graph
from .db import transaction

COURSE_ID = "cmu-15-445-f2025"

BASE = "https://15445.courses.cs.cmu.edu/fall2025"

# (id, type, title, summary, sort_order)
NODES = [
    (COURSE_ID, "course", "CMU 15-445/645 Database Systems (Fall 2025)",
     "Introductory database systems course covering storage, execution, "
     "concurrency, and recovery. The current graph starts with Lecture 01 "
     "and the storage/buffer-pool slice from Lectures 03-05.", 0),

    ("mod:foundations", "module", "Database Foundations",
     "Why database management systems exist, how data models separate logical "
     "structure from physical storage, and how the relational model expresses "
     "data and queries.", 0),

    ("unit:l01", "unit", "Lecture 01: Relational Model & Algebra",
     "Start from the limitations of application-managed flat files, then learn "
     "the relational model, keys and constraints, relational algebra, and the "
     "trade-offs of alternative data models.", 1),
    ("obj:dbms-motivation", "objective",
     "Explain why applications use a DBMS instead of managing flat files",
     "Connect flat-file failure modes to DBMS responsibilities: integrity, "
     "shared access, reusable query/storage logic, concurrency, durability, "
     "and recovery.", 1),
    ("obj:data-model-schema", "objective",
     "Distinguish a data model, a schema, and data independence",
     "A data model defines the concepts available to describe data; a schema "
     "uses those concepts for one database. Data independence keeps application "
     "logic insulated from low-level representation and access changes.", 2),
    ("obj:relational-model", "objective",
     "Explain relations, tuples, attributes, and domains",
     "Describe the logical structure of a relation without confusing it with "
     "a physical file layout: tuples contain attribute values drawn from "
     "domains, while the relation is conceptually unordered.", 3),
    ("obj:keys-constraints", "objective",
     "Explain primary keys, foreign keys, and integrity constraints",
     "Primary keys identify tuples, foreign keys express references between "
     "relations, and constraints reject database states that violate declared "
     "rules.", 4),
    ("obj:relational-algebra", "objective",
     "Use the core relational algebra operators to describe a query",
     "Selection filters tuples, projection chooses attributes, set operators "
     "combine compatible relations, product combines tuple pairs, and joins "
     "combine related tuples. Operator outputs are relations and can be "
     "composed.", 5),
    ("obj:alternative-data-models", "objective",
     "Compare relational, document, key-value, graph, and vector models",
     "Choose a model by its representation and access needs rather than by "
     "fashion; understand what flexibility or specialized access each model "
     "adds and what structure it gives up.", 6),

    ("mod:storage", "module", "Storage and Memory Management",
     "How a disk-oriented DBMS lays out data in files and pages, and how the "
     "buffer pool manages the movement of pages between disk and memory.", 1),

    ("unit:l03", "unit", "Lecture 03: Database Storage I",
     "Why the DBMS manages storage itself, how databases are stored as files "
     "of fixed-size pages, and how heap files organize those pages.", 2),
    ("obj:storage-hierarchy", "objective",
     "Explain the storage hierarchy and why the DBMS is disk-oriented",
     "Distinguish volatile memory from non-volatile storage by speed, cost, "
     "and capacity; explain that the DBMS assumes the database lives on disk "
     "and explicitly stages data into memory, rather than relying on the OS "
     "virtual memory (mmap) which it cannot control for correctness and "
     "performance reasons.", 10),
    ("obj:pages-files", "objective",
     "Describe how a database file is organized into fixed-size pages",
     "A database is stored as one or more files divided into fixed-size "
     "pages, each identified by a page id; the DBMS page size is chosen by "
     "the system and differs from hardware/OS page sizes.", 11),
    ("obj:heap-files", "objective",
     "Describe heap file organization and slotted page layout",
     "A heap file is an unordered collection of pages; it can be tracked as "
     "a linked list of pages or via a page directory that records page "
     "locations and free space. Within a page, the slotted layout uses a "
     "header plus a slot array mapping slots to record offsets, and a "
     "record id is (page id, slot).", 12),

    ("unit:l04", "unit", "Lecture 04: Memory Management / Buffer Pool",
     "How the buffer pool caches pages in memory frames, how the page table, "
     "pin counts, and dirty flags control eviction, and why replacement "
     "policy choice matters.", 3),
    ("obj:buffer-pool-purpose", "objective",
     "Explain the purpose of the buffer pool",
     "The buffer pool is the DBMS-managed region of memory that caches pages "
     "read from disk, giving the DBMS control over spatial and temporal "
     "reuse that it would not get from the OS page cache.", 20),
    ("obj:pages-vs-frames", "objective",
     "Distinguish pages from frames",
     "A page is the unit of storage on disk; a frame is a fixed-size slot in "
     "the buffer pool that can hold a copy of one page. Requests ask for a "
     "page; the buffer pool manager places it in a frame.", 21),
    ("obj:page-table", "objective",
     "Explain the role of the page table",
     "The in-memory page table maps page ids of pages currently in the pool "
     "to the frames holding them. It is distinct from the on-disk page "
     "directory, which maps page ids to file locations.", 22),
    ("obj:pin-dirty", "objective",
     "Explain pin counts and dirty flags",
     "Each frame tracks a pin count (how many threads are using the page; a "
     "pinned frame cannot be evicted) and a dirty flag (whether the page was "
     "modified since being read, meaning it must be written back on "
     "eviction).", 23),
    ("obj:replacement-policy", "objective",
     "Compare page replacement policies (LRU, CLOCK)",
     "When no free frame exists, a replacement policy picks a victim frame "
     "to evict. LRU evicts the least recently used page; CLOCK approximates "
     "LRU with a reference bit and a sweeping hand, avoiding exact "
     "timestamps.", 24),
    ("obj:sequential-flooding", "objective",
     "Explain sequential flooding and its mitigations",
     "A large sequential scan pollutes the pool under LRU because each "
     "freshly read page is used once and never again, evicting useful pages. "
     "Mitigations include LRU-K (tracking the last K references) and "
     "per-query hints such as using a small local pool for the scan.", 25),
    ("obj:project1-bpm", "objective",
     "Connect the buffer pool concepts to Project #1 (Buffer Pool Manager)",
     "Project #1 asks students to implement the buffer pool manager: the "
     "page table, pin/dirty bookkeeping, and an LRU-K replacement policy. "
     "The lecture concepts map directly onto the components to build.", 26),

    ("unit:l05", "unit", "Lecture 05: Database Storage II",
     "How tuples are laid out inside pages, the log-structured alternative "
     "to slotted pages, and how attribute values are represented.", 4),
    ("obj:tuple-storage", "objective",
     "Describe tuple layout within a page",
     "A tuple is a header (visibility/concurrency metadata and a NULL "
     "bitmap) followed by attribute values; the DBMS stores attributes in "
     "the order given by the schema and does not need to interleave "
     "metadata from external catalogs.", 30),
    ("obj:log-structured", "objective",
     "Contrast log-structured storage with slotted pages",
     "Log-structured storage appends changes as log records (put/delete "
     "entries) instead of updating pages in place, accumulating and "
     "compacting them later; it trades read amplification for fast "
     "sequential writes.", 31),
    ("obj:data-representation", "objective",
     "Explain how attribute values are represented",
     "Fixed-width integers/floats are stored directly; variable-length "
     "values carry a length header; values larger than a page must be "
     "handled specially (e.g., overflow storage).", 32),
]

# (src, dst, type, note)
EDGES = [
    ("mod:foundations", COURSE_ID, "part_of", ""),
    ("unit:l01", "mod:foundations", "part_of", ""),
    ("mod:storage", COURSE_ID, "part_of", ""),
    ("unit:l03", "mod:storage", "part_of", ""),
    ("unit:l04", "mod:storage", "part_of", ""),
    ("unit:l05", "mod:storage", "part_of", ""),
] + [
    (obj, "unit:l01", "part_of", "")
    for obj in (
        "obj:dbms-motivation", "obj:data-model-schema",
        "obj:relational-model", "obj:keys-constraints",
        "obj:relational-algebra", "obj:alternative-data-models",
    )
] + [
    (obj, unit, "part_of", "")
    for unit, objs in (
        ("unit:l03", ("obj:storage-hierarchy", "obj:pages-files",
                      "obj:heap-files")),
        ("unit:l04", ("obj:buffer-pool-purpose", "obj:pages-vs-frames",
                      "obj:page-table", "obj:pin-dirty",
                      "obj:replacement-policy", "obj:sequential-flooding",
                      "obj:project1-bpm")),
        ("unit:l05", ("obj:tuple-storage", "obj:log-structured",
                      "obj:data-representation")),
    )
    for obj in objs
] + [
    ("obj:dbms-motivation", "obj:data-model-schema", "sequence", ""),
    ("obj:data-model-schema", "obj:relational-model", "sequence", ""),
    ("obj:relational-model", "obj:keys-constraints", "sequence", ""),
    ("obj:keys-constraints", "obj:relational-algebra", "sequence", ""),
    ("obj:relational-algebra", "obj:alternative-data-models", "sequence", ""),
    ("obj:data-model-schema", "obj:relational-model", "prerequisite", ""),
    ("obj:relational-model", "obj:keys-constraints", "prerequisite", ""),
    ("obj:relational-model", "obj:relational-algebra", "prerequisite", ""),
    # lecture order
    ("unit:l03", "unit:l04", "sequence", ""),
    ("unit:l04", "unit:l05", "sequence", ""),
    # within-lecture order
    ("obj:storage-hierarchy", "obj:pages-files", "sequence", ""),
    ("obj:pages-files", "obj:heap-files", "sequence", ""),
    ("obj:buffer-pool-purpose", "obj:pages-vs-frames", "sequence", ""),
    ("obj:pages-vs-frames", "obj:page-table", "sequence", ""),
    ("obj:page-table", "obj:pin-dirty", "sequence", ""),
    ("obj:pin-dirty", "obj:replacement-policy", "sequence", ""),
    ("obj:replacement-policy", "obj:sequential-flooding", "sequence", ""),
    ("obj:sequential-flooding", "obj:project1-bpm", "sequence", ""),
    ("obj:tuple-storage", "obj:log-structured", "sequence", ""),
    ("obj:log-structured", "obj:data-representation", "sequence", ""),
    # prerequisites
    ("obj:pages-files", "obj:heap-files", "prerequisite", ""),
    ("obj:buffer-pool-purpose", "obj:pages-vs-frames", "prerequisite", ""),
    ("obj:pages-vs-frames", "obj:page-table", "prerequisite", ""),
    ("obj:page-table", "obj:pin-dirty", "prerequisite", ""),
    ("obj:pin-dirty", "obj:replacement-policy", "prerequisite", ""),
    ("obj:replacement-policy", "obj:sequential-flooding", "prerequisite", ""),
    ("obj:page-table", "obj:project1-bpm", "prerequisite", ""),
    ("obj:pin-dirty", "obj:project1-bpm", "prerequisite", ""),
    ("obj:replacement-policy", "obj:project1-bpm", "prerequisite", ""),
    ("obj:heap-files", "obj:tuple-storage", "prerequisite", ""),
    ("obj:tuple-storage", "obj:data-representation", "prerequisite", ""),
    # cross-links
    ("obj:log-structured", "obj:heap-files", "contrasts_with",
     "append-only log vs in-place slotted pages"),
    # Project #1 exercises the buffer-pool objectives
    ("obj:page-table", "obj:project1-bpm", "tested_by", ""),
    ("obj:pin-dirty", "obj:project1-bpm", "tested_by", ""),
    ("obj:replacement-policy", "obj:project1-bpm", "tested_by", ""),
]

# (id, kind, uri, title, lecture_ref)
SOURCES = [
    ("src:schedule", "url", BASE + "/schedule.html",
     "15-445 Fall 2025 schedule", ""),
    ("src:l01-slides", "url", BASE + "/slides/01-relationalmodel.pdf",
     "Lecture 01 slides: Relational Model & Algebra", "L01"),
    ("src:l01-notes", "url", BASE + "/notes/01-relationalmodel.pdf",
     "Lecture 01 notes: Relational Model & Algebra", "L01"),
    ("src:l01-video", "url",
     "https://www.youtube.com/watch?v=7NPIENPr-zk",
     "Lecture 01 video: Relational Model & Algebra", "L01"),
    ("src:textbook-7e", "url", "https://www.db-book.com/",
     "Database System Concepts, Seventh Edition (official site)",
     "Chapters 1-2"),
    ("src:l03-slides", "url", BASE + "/slides/03-storage1.pdf",
     "Lecture 03 slides: Database Storage I", "L03"),
    ("src:l03-notes", "url", BASE + "/notes/03-storage1.pdf",
     "Lecture 03 notes: Database Storage I", "L03"),
    ("src:l04-slides", "url", BASE + "/slides/04-bufferpool.pdf",
     "Lecture 04 slides: Memory Management / Buffer Pool", "L04"),
    ("src:l04-notes", "url", BASE + "/notes/04-bufferpool.pdf",
     "Lecture 04 notes: Memory Management / Buffer Pool", "L04"),
    ("src:l05-slides", "url", BASE + "/slides/05-storage2.pdf",
     "Lecture 05 slides: Database Storage II", "L05"),
    ("src:l05-notes", "url", BASE + "/notes/05-storage2.pdf",
     "Lecture 05 notes: Database Storage II", "L05"),
    ("src:project1", "url", BASE + "/project1/",
     "Project #1: Buffer Pool Manager", "Project #1"),
]

# (node_id, source_id) - attachments; anchors left empty (not verified)
NODE_SOURCES = [
    (COURSE_ID, "src:schedule"),
    ("unit:l01", "src:l01-slides"), ("unit:l01", "src:l01-notes"),
    ("unit:l01", "src:l01-video"), ("unit:l01", "src:textbook-7e"),
    ("obj:dbms-motivation", "src:l01-notes"),
    ("obj:data-model-schema", "src:l01-notes"),
    ("obj:relational-model", "src:l01-notes"),
    ("obj:keys-constraints", "src:l01-notes"),
    ("obj:relational-algebra", "src:l01-notes"),
    ("obj:alternative-data-models", "src:l01-notes"),
    ("unit:l03", "src:l03-slides"), ("unit:l03", "src:l03-notes"),
    ("obj:storage-hierarchy", "src:l03-notes"),
    ("obj:pages-files", "src:l03-notes"),
    ("obj:heap-files", "src:l03-notes"),
    ("unit:l04", "src:l04-slides"), ("unit:l04", "src:l04-notes"),
    ("obj:buffer-pool-purpose", "src:l04-notes"),
    ("obj:pages-vs-frames", "src:l04-notes"),
    ("obj:page-table", "src:l04-notes"),
    ("obj:pin-dirty", "src:l04-notes"),
    ("obj:replacement-policy", "src:l04-notes"),
    ("obj:sequential-flooding", "src:l04-notes"),
    ("obj:project1-bpm", "src:project1"),
    ("obj:project1-bpm", "src:l04-notes"),
    ("unit:l05", "src:l05-slides"), ("unit:l05", "src:l05-notes"),
    ("obj:tuple-storage", "src:l05-notes"),
    ("obj:log-structured", "src:l05-notes"),
    ("obj:data-representation", "src:l05-notes"),
]


def seed(conn):
    """Insert the seed graph and source registry. Idempotent."""
    existed = conn.execute(
        "SELECT 1 FROM nodes WHERE id = ?", (COURSE_ID,)
    ).fetchone() is not None
    before = conn.total_changes
    with transaction(conn):
        conn.executemany(
            "INSERT OR IGNORE INTO nodes (id, course_id, type, title, summary,"
            " sort_order) VALUES (?,?,?,?,?,?)",
            [(nid, COURSE_ID, ntype, title, summary, order)
             for (nid, ntype, title, summary, order) in NODES],
        )
        conn.executemany(
            "INSERT OR IGNORE INTO edges (src, dst, type, note) VALUES (?,?,?,?)",
            EDGES,
        )
        conn.executemany(
            "INSERT OR IGNORE INTO sources (id, course_id, kind, uri, title,"
            " lecture_ref, anchor) VALUES (?,?,?,?,?,?,NULL)",
            [(sid, COURSE_ID, kind, uri, title, lec)
             for (sid, kind, uri, title, lec) in SOURCES],
        )
        conn.executemany(
            "INSERT OR IGNORE INTO node_sources (node_id, source_id, anchor)"
            " VALUES (?,?,'')",
            NODE_SOURCES,
        )
        changed = conn.total_changes > before
        if changed:
            note = "seed content expansion" if existed else "initial seed"
            conn.execute(
                "INSERT INTO graph_versions (applied_at, proposal_id, note)"
                " VALUES (?,NULL,?)",
                (graph.now_iso(), note),
            )
    return changed
