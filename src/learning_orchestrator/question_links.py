"""Shared question/knowledge projection, including reviewed legacy identities.

All readers use this adapter. Direct associations stay in review_graph_questions;
legacy_question_link_reviews marks questions whose old broad associations were
semantically replaced, so an old alias cannot silently reintroduce a wrong link.
"""
import json
import re
from collections import defaultdict


def setup(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS legacy_question_link_reviews(
      question_id TEXT PRIMARY KEY REFERENCES questions(id),
      reviewed_at TEXT NOT NULL, note TEXT NOT NULL)''')


def exists(conn, table):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone() is not None


def sources(ref):
    """Keep an old primary source, but avoid repeating a synthesized batch header."""
    records=list(ref.get('sources') or [])
    identity=lambda r:(r.get('resolved_url') or r.get('url') or re.split(r'[\\/]+',r.get('file') or r.get('path') or r.get('original_path') or '')[-1] or r.get('block_id') or '')
    primary=identity(ref)
    if primary and not any(identity(r)==primary for r in records):
        records.insert(0,{k:v for k,v in ref.items() if k!='sources'})
    return records or ([ref] if ref else [])


def index(conn):
    result=defaultdict(dict)
    nodes={r['id']:json.loads(r['payload']) for r in conn.execute('SELECT id,payload FROM review_graph_nodes')}
    valid_questions={r['id']:r['course_id'] for r in conn.execute('SELECT id,course_id FROM questions')}
    reviewed={r[0] for r in conn.execute('SELECT question_id FROM legacy_question_link_reviews')} if exists(conn,'legacy_question_link_reviews') else set()

    def add(node,qid,scope):
        if node not in nodes or qid not in valid_questions:return
        target=result[node].setdefault(qid,[])
        if scope not in target:target.append(scope)

    for r in conn.execute('SELECT * FROM review_graph_questions'):
        add(r['node_id'],r['question_id'],{'node_id':r['node_id'],'project_id':r['context_project_id'],
             'link_source':'canonical',**json.loads(r['payload'])})
    aliases=defaultdict(list)
    for r in conn.execute("SELECT * FROM review_graph_bindings WHERE ref_type IN ('node','review_point')"):
        aliases[r['ref_id']].append((r['ref_type'],r['course_id'],r['node_id']))
    for r in conn.execute('SELECT * FROM question_knowledge'):
        qid,point=r['question_id'],r['point_id']
        if qid in reviewed:continue
        targets=[point] if point in nodes else []
        targets.extend(node for typ,course,node in aliases.get(point,[]) if typ=='node' or course==valid_questions.get(qid))
        for nid in set(targets):
            add(nid,qid,{'node_id':nid,'project_id':'','link_source':'legacy','focus':'旧题库知识关联',
                         'coverage':'仅表示已有映射，不自动代表整块覆盖；尚未校正的关联保留待核对。'})
    return dict(result)


def scope_nodes(conn,node_id,descendants=True):
    scope=[node_id]
    row=conn.execute('SELECT payload FROM review_graph_nodes WHERE id=?',(node_id,)).fetchone()
    if not descendants or not row or json.loads(row[0]).get('kind')!='knowledge':return scope
    # Only contains is containment; neither uses nor requires inherits questions.
    pairs=list(conn.execute("SELECT from_id,to_id FROM review_graph_edges WHERE relation='contains'"))
    children=defaultdict(list)
    for a,b in pairs:children[a].append(b)
    seen={node_id};todo=[node_id]
    while todo:
        for child in children[todo.pop()]:
            if child not in seen:seen.add(child);scope.append(child);todo.append(child)
    return scope


def resolve(conn,node_ids,project_id=None,links=None):
    links=index(conn) if links is None else links
    hits={}
    for nid in node_ids:
        for qid,scopes in links.get(nid,{}).items():
            scopes=[s for s in scopes if not project_id or s.get('project_id','') in ('',project_id)]
            if not scopes:continue
            if qid not in hits:
                row=conn.execute('SELECT id,stem,level,origin,source_ref FROM questions WHERE id=?',(qid,)).fetchone()
                if not row:continue
                hits[qid]=dict(row,node_ids=[],scopes=[],contexts=[])
            h=hits[qid]
            if nid not in h['node_ids']:h['node_ids'].append(nid)
            for s in scopes:
                if s not in h['contexts']:h['contexts'].append(s)
                display={'node_id':nid,'focus':s.get('focus',''),'coverage':s.get('coverage','')}
                if display not in h['scopes']:h['scopes'].append(display)
    return sorted(hits.values(),key=lambda q:q['id'])


def questions_for_node(conn,node_id,project_id=None,links=None):
    return resolve(conn,scope_nodes(conn,node_id),project_id,links)


def counts(conn,links=None,project_id=None):
    """Counts use the same scope semantics without loading every question body."""
    links=index(conn) if links is None else links
    kinds={r['id']:json.loads(r['payload']).get('kind') for r in conn.execute('SELECT id,payload FROM review_graph_nodes')}
    children=defaultdict(list)
    for a,b in conn.execute("SELECT from_id,to_id FROM review_graph_edges WHERE relation='contains'"):children[a].append(b)
    cache={}
    def collect(nid,trail):
        if nid in cache:return cache[nid]
        if nid in trail:return set()
        ids={qid for qid,scopes in links.get(nid,{}).items() if any(not project_id or s.get('project_id','') in ('',project_id) for s in scopes)}
        if kinds.get(nid)=='knowledge':
            for child in children[nid]:ids.update(collect(child,trail|{nid}))
        cache[nid]=ids;return ids
    return {nid:len(collect(nid,set())) for nid in kinds}


def inventory(conn,text='',state='',offset=0,limit=80,category=''):
    """Read-only question browser; unmapped and partially covered items remain findable."""
    links=index(conn);reverse_links=defaultdict(list)
    for nid,qs in links.items():
        for qid in qs:reverse_links[qid].append(nid)
    pending={r['question_id']:r['reason'] for r in conn.execute('SELECT question_id,reason FROM question_link_pending')} if exists(conn,'question_link_pending') else {}
    from . import question_categories
    category_map=defaultdict(list)
    if exists(conn,'question_categories'):
        for qid,tag in conn.execute('SELECT question_id,category FROM question_categories'):category_map[qid].append(tag)
    rows=[];totals={'all':0,'linked':0,'unlinked':0,'needs_work':0};category_counts=defaultdict(int)
    for r in conn.execute('SELECT id,stem,origin,level,group_key,source_ref,variants FROM questions ORDER BY id'):
        q=dict(r);nids=reverse_links.get(q['id'],[]);ref=json.loads(q.pop('source_ref'));q['knowledge_count']=len(nids)
        q['categories']=category_map.get(q['id']) or question_categories.suggest(q['stem'],q['id'])
        for tag in q['categories']:category_counts[tag]+=1
        q['pending_reason']=pending.get(q['id'],'')
        q['association_status']='partial' if nids and q['pending_reason'] else 'linked' if nids else 'pending'
        q['source_count']=len(sources(ref));totals['all']+=1;totals['linked' if nids else 'unlinked']+=1
        if q['pending_reason'] or not nids:totals['needs_work']+=1
        search=' '.join([q['stem'],q['group_key'],q.pop('variants'),json.dumps(ref,ensure_ascii=False)]).lower()
        if text and text.lower() not in search:continue
        if category and category not in q['categories']:continue
        if state=='pending' and nids and not q['pending_reason']:continue
        if state=='unlinked' and nids:continue
        rows.append(q)
    offset=max(0,int(offset));limit=max(1,min(int(limit),200))
    return {'totals':totals,'categories':[{'id':k,'label':v,'count':category_counts[k]} for k,v in question_categories.LABELS.items()],
            'matched':len(rows),'offset':offset,'limit':limit,'items':rows[offset:offset+limit]}


def reverse(conn,question_id,links=None):
    links=index(conn) if links is None else links
    result=[]
    for nid,qs in links.items():
        if question_id not in qs:continue
        row=conn.execute('SELECT payload FROM review_graph_nodes WHERE id=?',(nid,)).fetchone()
        n=json.loads(row[0]);result.append({'id':nid,'kind':n.get('kind'),'title':n.get('title',nid),'contexts':qs[question_id]})
    return result
