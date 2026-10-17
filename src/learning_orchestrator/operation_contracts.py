"""Discoverable business contracts. Stages are navigation, not dispatch rules.

Schemas describe the public artifact, not arbitrary kwargs for an old method.
Domain implementations remain responsible for references and state semantics.
"""
from copy import deepcopy

from .graph import ValidationError


def obj(properties=None, required=(), **extra):
    return dict(type='object', properties=properties or {}, required=list(required), **extra)


TEXT = {'type': 'string'}
ARRAY = {'type': 'array'}
OBJECT = {'type': 'object'}
INTEGER = {'type': 'integer'}
SCOPE = obj({k: TEXT for k in ('course_id', 'section_id', 'project_id', 'batch_id', 'profile')}
            | {'node_ids': {'type': 'array', 'items': TEXT}, 'teaching_item_id': INTEGER})


def spec(stage, handler, fields, required=(), scope_required=(), writes=(), **extra):
    return dict(stage=stage, handler=handler, version=1,
        scope_schema=dict(deepcopy(SCOPE), required=list(scope_required)),
        artifact_schema=obj(fields, required, additionalProperties=False),
        writes=list(writes), retry='same request_id and input returns original receipt', **extra)


OPERATIONS = {
    'curriculum.register': spec('plan', 'curriculum',
        {'title': TEXT, 'kind': {'enum': ['course', 'project']}, 'sections': ARRAY},
        ['title'], ['course_id'], ['curriculum_structure']),
    'plan.save': spec('plan', 'plan',
        {'milestones': ARRAY, 'stage_key': TEXT, 'created_by': TEXT},
        ['milestones'], ['course_id', 'section_id'], ['teaching_plan', 'teaching_position']),
    'context.prepare': spec('context', 'context',
        {'goal': TEXT, 'materials': ARRAY, 'targets': ARRAY, 'missing': ARRAY},
        writes=['material_snapshot']),
    'lesson.publish': spec('lesson', 'content',
        {'documents': ARRAY}, ['documents'], ['node_ids'], ['lesson_version']),
    'record.learning': spec('record', 'learning',
        {'analysis': OBJECT, 'items_add': ARRAY, 'items_update': ARRAY,
         'position': obj({'current_item_id': INTEGER, 'current_item_key': TEXT,
                          'base_state_version': INTEGER}, additionalProperties=False),
         'role': {'enum': ['main', 'detail', 'control']}, 'turn_record': OBJECT},
        ['analysis'], ['course_id'], ['learning_records', 'question_tree', 'explicit_teaching_position']),
    'record.review': spec('record', 'review_record',
        {'attempts': ARRAY, 'gaps': ARRAY, 'unmatched': ARRAY, 'source_ticket': OBJECT,
         'recall_results': ARRAY, 'source_updates': ARRAY},
        scope_required=['batch_id'], writes=['batch_attempts', 'batch_gaps', 'source_checkpoint',
                                           'explicit_covered_recall']),
    'assessment.record': spec('assessment', 'assessment',
        {'assessments': ARRAY, 'recall_results': ARRAY, 'question_id': TEXT},
        writes=['explicit_assessments', 'explicit_recall_schedule']),
    'note.publish': spec('note', 'content',
        {'documents': ARRAY, 'edges': ARRAY, 'question_links': ARRAY, 'flow_steps': ARRAY},
        ['documents'], ['node_ids'], ['published_body', 'content_index', 'explicit_graph_links']),
    'graph.commit': spec('organize', 'graph',
        {k: ARRAY for k in ('nodes', 'edges', 'findings', 'question_links', 'legacy_bindings', 'flow_steps')},
        writes=['explicit_graph_delta']),
    'questions.commit': spec('organize', 'questions',
        {'entries': ARRAY, 'source_ref': OBJECT}, ['entries'], writes=['questions', 'question_links']),
    'review.save': spec('review', 'review',
        {'title': TEXT, 'items': ARRAY, 'source_ref': TEXT}, ['title', 'items'], ['batch_id'],
        ['review_batch_membership']),
}

SCOPE_FIELDS = {
    'curriculum.register': ('course_id',), 'plan.save': ('course_id', 'section_id'),
    'context.prepare': ('node_ids', 'project_id', 'profile'),
    'lesson.publish': ('node_ids', 'project_id', 'profile', 'teaching_item_id'),
    'note.publish': ('node_ids', 'project_id', 'profile'),
    'record.learning': ('course_id', 'section_id'), 'record.review': ('batch_id', 'project_id'),
    'assessment.record': ('project_id',), 'graph.commit': ('project_id', 'node_ids'),
    'questions.commit': (), 'review.save': ('batch_id', 'project_id'),
}
COMMON_INPUTS = {'goal': TEXT, 'materials': ARRAY, 'document_selections': ARRAY}
RECORD_INPUTS = dict(COMMON_INPUTS, transcript=TEXT, path=TEXT, source_ref=TEXT,
                     source_key=TEXT, offset=INTEGER, max_chars=INTEGER)
MEANINGS = {
    'curriculum.register': '登记类型与章节，不创建学习或掌握记录。',
    'plan.save': '保存教学路线；条目状态和正式知识掌握分开。',
    'context.prepare': '材料只作本次交接快照，不发布正式知识。',
    'lesson.publish': '保存教案不等于已讲解或理解。',
    'note.publish': '正文发布不推进学习、掌握或排期。',
    'record.learning': '讲解、确认和验证分开；子问题关闭不关闭父项或同级项。',
    'record.review': '原题身份不变；补学和确认不自动变为答题通过；只对显式覆盖更新排期。',
    'assessment.record': '只判断本次实际覆盖对象，项目应用通过context_edge_id表达。',
    'graph.commit': '显式关系增量；uses不继承全部基础题或掌握。',
    'questions.commit': '复用题目、追加来源和关联；未匹配保留待关联，不推断亲历或掌握。',
    'review.save': '原题批次是入口和顺序，不是另一份题库或另一套知识排期。',
}
for _name, _spec in OPERATIONS.items():
    _spec['scope_schema']['properties'] = {k: deepcopy(SCOPE['properties'][k])
                                           for k in SCOPE_FIELDS[_name]}
    _spec['scope_schema']['additionalProperties'] = False
    _spec['input_schema'] = obj(deepcopy(RECORD_INPUTS if _spec['stage'] == 'record'
                                        else COMMON_INPUTS), additionalProperties=False)
    _spec['meaning'] = MEANINGS[_name]
    _spec['result_schema'] = obj({'success': {'type': 'boolean'}, 'operation': TEXT,
                                  'stage': TEXT, 'result': OBJECT},
                                 ['success', 'operation', 'stage', 'result'])

DOCUMENT = obj({'node_id': TEXT, 'body': TEXT, 'area': TEXT,
                'source_refs': ARRAY, 'covered_entry_ids': ARRAY}, ['node_id', 'body'],
               additionalProperties=False)
FLOW_STEPS = {'type': 'array', 'items': obj({'flow_id': TEXT, 'steps': {'type': 'array', 'items': obj({
    'id': TEXT, 'title': TEXT, 'description': TEXT, 'knowledge': {'type': 'array', 'items': obj({
        'node_id': TEXT, 'usage': TEXT, 'used_parts': ARRAY, 'required_depth': TEXT}, ['node_id', 'usage'])}},
    ['id', 'title', 'description'])}, 'connections': ARRAY}, ['flow_id', 'steps'])}
for _name in ('note.publish', 'graph.commit'):
    OPERATIONS[_name]['artifact_schema']['properties']['flow_steps'] = FLOW_STEPS
for _name in ('note.publish', 'lesson.publish'):
    OPERATIONS[_name]['artifact_schema']['properties']['documents'] = {
        'type': 'array', 'items': DOCUMENT}
OPERATIONS['plan.save']['artifact_schema']['properties']['milestones'] = {
    'type': 'array', 'items': obj({'title': TEXT, 'node_id': TEXT, 'material_ref': OBJECT}, ['title'])}
OPERATIONS['record.learning']['artifact_schema']['properties']['analysis'] = obj(
    {'source_ref': TEXT, 'summary': TEXT, 'fingerprint': TEXT, 'processed_chars': INTEGER,
     'prefix_fingerprint': TEXT, 'covered_ranges': ARRAY}, ['source_ref', 'summary'])
OPERATIONS['record.review']['artifact_schema']['properties']['attempts'] = {
    'type': 'array', 'items': obj({'question_id': TEXT, 'attempt_id': TEXT, 'text': TEXT,
        'kind': {'enum': ['answer', 'explanation', 'confirmation']},
        'result': {'enum': ['pass', 'deepen']}, 'coverage': ARRAY,
        'gap_note': TEXT, 'source_ref': OBJECT}, ['question_id'])}
OPERATIONS['record.review']['artifact_schema']['properties']['gaps'] = {
    'type': 'array', 'items': obj({'id': TEXT, 'title': TEXT, 'parent_id': TEXT,
        'question_id': TEXT, 'node_id': TEXT, 'note': TEXT,
        'state': {'enum': ['open', 'explained', 'resolved', 'deferred']}}, ['id'])}
OPERATIONS['review.save']['artifact_schema']['properties']['items'] = {
    'type': 'array', 'items': obj({'question_id': TEXT, 'label': TEXT,
                                  'node_ids': {'type': 'array', 'items': TEXT}}, ['question_id'])}
OPERATIONS['questions.commit']['artifact_schema']['properties']['entries'] = {
    'type': 'array', 'items': obj({'question_id': TEXT, 'client_key': TEXT, 'action': TEXT,
        'stem': TEXT, 'variants': ARRAY, 'source_ref': OBJECT, 'origin': TEXT, 'course_id': TEXT,
        'group_key': TEXT, 'context': TEXT, 'answer_basis': TEXT, 'categories': ARRAY,
        'links': ARRAY, 'pending_reason': TEXT, 'corrections': OBJECT, 'firsthand': OBJECT})}


def get(operation):
    if operation not in OPERATIONS:
        raise ValidationError('Unknown workflow operation: ' + str(operation))
    return OPERATIONS[operation]


def validate(value, schema, path):
    """Validate the public envelope; this is not a new learning state machine."""
    typ = schema.get('type')
    types = {'object': dict, 'array': list, 'string': str, 'integer': int, 'boolean': bool}
    if typ and (not isinstance(value, types[typ]) or typ == 'integer' and isinstance(value, bool)):
        raise ValidationError(path + ' must be ' + typ)
    if 'enum' in schema and value not in schema['enum']:
        raise ValidationError(path + ' must be one of ' + repr(schema['enum']))
    if typ == 'object':
        for key in schema.get('required', []):
            if key not in value or value[key] in (None, '', []):
                raise ValidationError(path + '.' + key + ' is required')
        props = schema.get('properties', {})
        for key, child in value.items():
            if key in props:
                validate(child, props[key], path + '.' + key)
            elif schema.get('additionalProperties') is False:
                raise ValidationError('Unknown ' + path + ' field: ' + key)
    if typ == 'array' and 'items' in schema:
        for index, child in enumerate(value):
            validate(child, schema['items'], path + '[' + str(index) + ']')


def describe(operation=None):
    if operation:
        item = deepcopy(get(operation))
        item.pop('handler')
        return dict(operation=operation, **item)
    return [dict(operation=name, stage=s['stage'], version=s['version'], writes=s['writes'])
            for name, s in OPERATIONS.items()]
