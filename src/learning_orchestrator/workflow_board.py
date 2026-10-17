"""Persistent project controls for the four user-facing production processes."""
from copy import deepcopy
import hashlib
import json

from . import documents, review_graph
from .db import transaction
from .graph import ValidationError, now_iso

PROCESSES = {
    'lesson': dict(title='生成教案', operations=['lesson.publish'],
        input_requirements='依据选定教材章节、项目材料及本次学习目标筛选必要内容。',
        output_requirements='自包含教案：目标、必要背景、自然分段的讲解、例子或核心代码。'),
    'record': dict(title='学习记录登记', operations=['record.learning', 'record.review'],
        input_requirements='分析所选聊天记录的新增部分，结合对应教案及已有位置。',
        output_requirements='记录用户提问、讲解和确认；保留父子追问、未回应和未确认项，给出续接位置。'),
    'note': dict(title='笔记生成', operations=['note.publish'],
        input_requirements='结合材料、已有正文及实际学习记录，明确本次整理范围和读者。',
        output_requirements='可读正文及稳定定位；项目流程说明目的、步骤衔接和关键机制，关联各步使用的知识。'),
    'associate': dict(title='知识点关联', operations=['graph.commit'],
        input_requirements='从本次项目或知识正文出发，先查已有知识身份，再判断具体用途和关系。',
        output_requirements='明确的节点与关系增量、流程步骤及知识用途；不确定的对应保留为待处理项。'),
}

BUILTIN_CONSTRAINTS = [
    dict(id='builtin.self-contained', title='自包含材料', effect='output', applies_to=['lesson', 'note'],
         instructions='面向看不到本地材料的读者，嵌入必要背景、解释及核心示例；本地路径只用于来源定位。', version=1),
    dict(id='builtin.project-flow', title='按业务步骤复盘', effect='output', applies_to=['lesson', 'note', 'associate'],
         instructions='解释模块目的与输入输出，沿实际处理步骤串联实现；每步注明使用的公共知识及用途。', version=1),
    dict(id='builtin.confirmation', title='区分讲解与确认', effect='method', applies_to=['record'],
         instructions='分别提取用户问题、讲解、用户确认和实际作答。保留父子与并列问题，明确未回应和已讲未确认项。', version=1),
    dict(id='builtin.selected-material', title='限定本次材料范围', effect='input', applies_to=list(PROCESSES),
         instructions='优先依据本次选择的文档片段与已有正式内容，缺少必要材料时标出具体缺口。', version=1),
]


def setup(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS workflow_controls(
      project_id TEXT NOT NULL, process TEXT NOT NULL, version INTEGER NOT NULL,
      payload TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(project_id,process));
    CREATE TABLE IF NOT EXISTS workflow_control_versions(
      project_id TEXT NOT NULL, process TEXT NOT NULL, version INTEGER NOT NULL,
      payload TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(project_id,process,version));
    CREATE TABLE IF NOT EXISTS workflow_run_receipts(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS workflow_constraint_modules(id TEXT PRIMARY KEY, version INTEGER NOT NULL, payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS workflow_prepared_tasks(
      id TEXT PRIMARY KEY, document_id TEXT NOT NULL UNIQUE, request_id TEXT NOT NULL,
      payload TEXT NOT NULL, created_at TEXT NOT NULL);
    ''')


def modules(orch):
    result = {m['id']: dict(m, builtin=True) for m in BUILTIN_CONSTRAINTS}
    for row in orch.conn.execute('SELECT payload FROM workflow_constraint_modules'):
        item = json.loads(row[0])
        result[item['id']] = item
    return list(result.values())


def save_module(orch, title, effect, instructions, applies_to, module_id=None, base_version=0):
    if not title.strip() or not instructions.strip() or effect not in ('input', 'method', 'output'):
        raise ValidationError('A constraint needs title, instructions and input/method/output effect')
    if not isinstance(applies_to, list) or not applies_to or set(applies_to) - set(PROCESSES):
        raise ValidationError('Choose the processes where this constraint applies')
    import uuid
    module_id = module_id or 'constraint-' + uuid.uuid4().hex
    if module_id.startswith('builtin.'):
        raise ValidationError('Copy a built-in constraint to customize it')
    old = orch.conn.execute('SELECT version FROM workflow_constraint_modules WHERE id=?', (module_id,)).fetchone()
    if int(base_version) != (old[0] if old else 0):
        raise ValidationError('Constraint changed; reload before saving')
    item = dict(id=module_id, title=title.strip(), effect=effect, instructions=instructions.strip(),
                applies_to=applies_to, version=int(base_version)+1)
    with transaction(orch.conn):
        orch.conn.execute('INSERT INTO workflow_constraint_modules VALUES(?,?,?) ON CONFLICT(id) '
                         'DO UPDATE SET version=excluded.version,payload=excluded.payload',
                         (module_id, item['version'], json.dumps(item, ensure_ascii=False)))
    return dict(success=True, module=item)


def process_for(operation):
    return next((p for p, d in PROCESSES.items() if operation in d['operations']), None)


def project_key(orch, identifier):
    """Use explicit identities/owner links, never project names or title guesses."""
    if not identifier:
        return ''
    identifier = review_graph._canonical(orch.conn, identifier)
    row = orch.conn.execute('SELECT payload FROM review_graph_nodes WHERE id=?', (identifier,)).fetchone()
    if row and json.loads(row[0]).get('kind') == 'project':
        return identifier
    matches = []
    for row in orch.conn.execute('SELECT id,payload FROM review_graph_nodes'):
        n = json.loads(row['payload'])
        owner = n.get('owner_ref') or {}
        if n.get('kind') == 'project' and owner.get('type') == 'project' and owner.get('id') == identifier:
            matches.append(row['id'])
    return matches[0] if len(matches) == 1 else identifier


def controls(orch, project_id='', process=None):
    if process not in PROCESSES:
        raise ValidationError('Choose lesson, record, note or associate')
    project_id = project_key(orch, project_id)
    base = dict(project_id=project_id, process=process, title=PROCESSES[process]['title'],
        goal='', input_requirements=PROCESSES[process]['input_requirements'],
        output_requirements=PROCESSES[process]['output_requirements'], strategy_id='',
        material_selections=[], constraint_ids=[], extra_instructions='', version=0)
    row = orch.conn.execute('SELECT version,payload FROM workflow_controls WHERE project_id=? AND process=?',
                            (project_id or '', process)).fetchone()
    if row:
        base.update(json.loads(row['payload']), version=row['version'])
    for selection in base['material_selections']:
        try:
            selection['title'] = documents.metadata(orch, selection['document_id'])['title']
        except ValidationError:
            selection['title'] = '文档待重新定位：' + selection['document_id']
    return base


def clarify(value):
    questions = []
    for field, question in (
        ('goal', '这次要解决什么问题、处理哪个范围？'),
        ('input_requirements', '哪些输入是依据，需要筛选或排除哪些内容？'),
        ('output_requirements', '希望拿到什么成品、写给谁看、做到什么程度？')):
        if not str(value.get(field, '')).strip():
            questions.append(dict(field=field, question=question))
    if not value.get('strategy_id'):
        questions.append(dict(field='extra_instructions', optional=True,
            question='没有专用策略时，还有什么本项目特有的分析或写作要求？可以沿用默认方法。'))
    return questions


def board(orch, project_id=''):
    projects = []
    for row in orch.conn.execute('SELECT id,payload FROM review_graph_nodes'):
        n = json.loads(row['payload'])
        if n.get('kind') == 'project':
            owner_id = (n.get('owner_ref') or {}).get('id') or row['id']
            projects.append(dict(id=row['id'], title=n.get('title', row['id']), course_id=owner_id))
    known = {p['id'] for p in projects}
    for row in orch.conn.execute("SELECT id,title FROM nodes WHERE type='course'"):
        if row['id'] not in known and project_key(orch, row['id']) not in known:
            projects.append(dict(row, course_id=row['id']))
    return dict(projects=projects, processes=[dict(id=p, **d) for p, d in PROCESSES.items()],
                controls=[controls(orch, project_id, p) for p in PROCESSES],
                strategies=orch._strategies.describe(include_instructions=True), constraint_modules=modules(orch))


def save(orch, project_id, process, values, base_version=0):
    project_id = project_key(orch, project_id)
    old = controls(orch, project_id, process)
    if int(base_version) != old['version']:
        raise ValidationError('Configuration changed in another window; reload before saving')
    allowed = ('goal', 'input_requirements', 'output_requirements', 'strategy_id',
               'material_selections', 'extra_instructions', 'constraint_ids')
    if set(values) - set(allowed):
        raise ValidationError('Unknown control field')
    data = {k: deepcopy(values.get(k, old[k])) for k in allowed}
    for key in allowed:
        if key == 'constraint_ids':
            available = {m['id'] for m in modules(orch) if process in m['applies_to']}
            if not isinstance(data[key], list) or any(mid not in available for mid in data[key]):
                raise ValidationError('Choose compatible constraint modules')
        elif key == 'material_selections':
            if not isinstance(data[key], list):
                raise ValidationError('material_selections must be an array')
            for selection in data[key]:
                documents.metadata(orch, selection['document_id'])
        elif not isinstance(data[key], str):
            raise ValidationError(key + ' must be text')
    if data['strategy_id']:
        compatible = any(s['id'] == data['strategy_id'] for operation in PROCESSES[process]['operations']
                         for s in orch._strategies.describe(operation))
        if not compatible:
            raise ValidationError('Strategy is not compatible with this process')
    with transaction(orch.conn):
        args = (project_id or '', process, old['version'] + 1,
                json.dumps(data, ensure_ascii=False), now_iso())
        orch.conn.execute('INSERT INTO workflow_controls VALUES(?,?,?,?,?) ON CONFLICT(project_id,process) '
            'DO UPDATE SET version=excluded.version,payload=excluded.payload,updated_at=excluded.updated_at', args)
        orch.conn.execute('INSERT INTO workflow_control_versions VALUES(?,?,?,?,?)', args)
    current = controls(orch, project_id, process)
    return dict(success=True, controls=current, clarification=clarify(current))


def configure(orch, operation, scope, inputs, strategy_id, override=None):
    """Select only this task's method and materials. Snapshot controls in ticket."""
    process = process_for(operation)
    if not process:
        return inputs, strategy_id, None
    project = scope.get('project_id') or scope.get('course_id') or ''
    if not project and scope.get('batch_id'):
        row = orch.conn.execute('SELECT project_id FROM review_batches WHERE id=?', (scope['batch_id'],)).fetchone()
        project = row[0] if row else ''
    cfg = controls(orch, project, process)
    if override:
        if set(override) - {'goal', 'input_requirements', 'output_requirements', 'extra_instructions'}:
            raise ValidationError('Task controls may override only task text fields')
        if any(not isinstance(v, str) for v in override.values()):
            raise ValidationError('Task controls must be text')
        cfg.update(override)
    result = deepcopy(inputs)
    goal = result.get('goal') or cfg['goal']
    result['goal'] = goal
    materials = list(result.get('materials', []))
    selections = result.pop('document_selections', None)
    if selections is None:
        selections = cfg['material_selections']
    remaining = 24000
    refs = []
    record_documents = []
    for selection in selections:
        if remaining <= 0:
            break
        selected = dict(selection)
        selected.pop('title', None)
        meta = documents.metadata(orch, selected['document_id'])
        selected['max_chars'] = (50000 if process == 'record' and meta['kind'] == 'record'
                                 else min(int(selected.get('max_chars', 8000)), remaining))
        d = documents.read(orch, **selected)
        if not (process == 'record' and d['document']['kind'] == 'record'):
            remaining -= len(d['text'])
        ref = dict(document_id=d['document']['id'], version=d['document']['version'],
                   selection=d['selection'], fingerprint=d['fingerprint'])
        refs.append(ref)
        materials.append(dict(title=d['document']['title'], text=d['text'], source_ref=ref,
                              truncated=d['truncated']))
        if d['document']['kind'] == 'record':
            record_documents.append(d)
    result['materials'] = materials
    if process == 'record' and not result.get('transcript') and not result.get('path'):
        if len(record_documents) != 1:
            raise ValidationError('Select one learning record document, or supply transcript explicitly')
        record = record_documents[0]
        if record['truncated']:
            raise ValidationError('Record exceeds 50,000 characters; select the relevant lines for this task')
        result['transcript'] = record['text']
        result['source_ref' if operation == 'record.learning' else 'source_key'] = record['document']['id']
        # The transcript is returned once, as an increment from the record
        # preparer, not again as a full material in every subsequent round.
        result['materials'] = [m for m in materials if (m.get('source_ref') or {}).get('document_id') != record['document']['id']]
    cfg['goal'] = goal
    available = {m['id']: m for m in modules(orch)}
    cfg['constraint_modules'] = [available[mid] for mid in cfg['constraint_ids'] if mid in available]
    cfg['material_refs'] = refs
    cfg['clarification'] = clarify(cfg)
    return result, strategy_id or cfg['strategy_id'] or None, cfg


def attach(task, cfg):
    if cfg is None:
        return task
    # Input/output requirements describe where they act, both are visible to the
    # producer before generation. Never append rules for unrelated processes.
    block = '\n\n本项目任务：' + (cfg['goal'] or '待澄清')
    block += '\n输入处理要求：' + cfg['input_requirements']
    block += '\n产出要求：' + cfg['output_requirements']
    if cfg['extra_instructions']:
        block += '\n本项目补充：' + cfg['extra_instructions']
    for module in cfg.get('constraint_modules', []):
        effect = {'input': '输入处理', 'method': '分析方法', 'output': '产出内容'}[module['effect']]
        block += '\n约束模块（作用于' + effect + '）' + module['title'] + '：' + module['instructions']
    task['instructions'] += block
    task['controls'] = cfg
    task['ticket']['controls'] = cfg
    task['clarification'] = cfg['clarification']
    task['ready'] = not any(not q.get('optional') for q in cfg['clarification'])
    if not task['ready']:
        task['next'] = ('Resolve missing goal/input/output fields from the user request and existing defaults; '
                        'ask only for material information still missing. Save reusable settings with '
                        'save_workflow_controls and prepare again, then generate, commit and read back the result.')
    task['handoff_markdown'] = ('# ' + cfg['title'] + '\n\n' + task['instructions'] +
        '\n\n## 本次材料与状态\n```json\n' + json.dumps(task['context'], ensure_ascii=False, indent=2) +
        '\n```\n\n## 返回格式\n请返回满足以下契约的 JSON，保留已有身份。\n```json\n' +
        json.dumps(task['artifact_schema'], ensure_ascii=False, indent=2) + '\n```')
    if not task['ready']:
        task['handoff_markdown'] = ('# 先澄清本项目的工作要求\n\n请使用逐轮盘问明确以下缺失项，沿用已确定内容。'
            '完成讨论后返回 goal、input_requirements、output_requirements、extra_instructions 四个字段，'
            '供写回项目配置。\n\n' + '\n'.join('- ' + q['question'] for q in cfg['clarification']) +
            '\n\n已有项目要求：\n```json\n' + json.dumps({k:cfg[k] for k in (
                'goal','input_requirements','output_requirements','extra_instructions')}, ensure_ascii=False, indent=2) +
            '\n```\n\n待澄清后执行的任务：\n\n' + task['handoff_markdown'])
    return task


def record_result(orch, request_id, ticket, result):
    """Store the exact task controls and references for a published result."""
    cfg = ticket.get('controls')
    if not cfg:
        return
    identifier = 'run-' + hashlib.sha256(request_id.encode()).hexdigest()
    orch.conn.execute('INSERT INTO workflow_run_receipts(id,payload) VALUES(?,?)',
        (identifier, json.dumps(dict(request_id=request_id, ticket=ticket, result=result), ensure_ascii=False)))


def save_task(orch, task, title=None):
    from .workflow import CONTRACT
    if not isinstance(task, dict) or task.get('ticket', {}).get('contract') != CONTRACT:
        raise ValidationError('Save a task returned by prepare_workflow')
    key = 'task-' + hashlib.sha256(review_graph._json(task).encode()).hexdigest()
    previous = orch.conn.execute('SELECT document_id FROM workflow_prepared_tasks WHERE id=?', (key,)).fetchone()
    if previous:
        return read_task(orch, previous[0])
    cfg = task.get('controls') or {}
    doc = documents.save(orch, document_id='doc-' + key,
        title=title or (cfg.get('title', '工作任务') + ' · ' + cfg.get('goal', '')),
        project_id=cfg.get('project_id', ''), kind='material', text=task['handoff_markdown'],
        source_refs=cfg.get('material_refs', []))['document']
    with transaction(orch.conn):
        orch.conn.execute('INSERT INTO workflow_prepared_tasks VALUES(?,?,?,?,?)',
            (key, doc['id'], key + ':commit', json.dumps(task, ensure_ascii=False), now_iso()))
    return read_task(orch, doc['id'])


def read_task(orch, document_id):
    row = orch.conn.execute('SELECT * FROM workflow_prepared_tasks WHERE document_id=?', (document_id,)).fetchone()
    if not row:
        raise ValidationError('This document is not a saved workflow task')
    previous = orch.conn.execute('SELECT receipt FROM review_graph_requests WHERE id=?', (row['request_id'],)).fetchone()
    return dict(success=True, task_id=row['id'], document_id=document_id, request_id=row['request_id'],
                task=json.loads(row['payload']), receipt=json.loads(previous[0]) if previous else None)
