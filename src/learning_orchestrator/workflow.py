"""Explicit application operations with discoverable contracts and local strategies.

Historical stage calls are translated in workflow_compat. Domain handlers never
select behavior by guessing fields in a new AI artifact.
"""
from copy import deepcopy
import json

from . import operation_contracts as contracts
from . import operation_handlers as handlers
from . import production, review_graph, workflow_board, workflow_compat as compat
from .db import transaction
from .graph import ValidationError

CONTRACT = 'lo.workflow.v2'
LEGACY_CONTRACT = 'lo.workflow.v1'
DEFAULTS = {
    'plan': '围绕目标和范围规划阶段与依赖，当前阶段才细化。计划不等于正式知识或掌握。',
    'context': '只选本次目标必要的来源、前置与正文，保留定位、内容和缺口，不展开全量历史。',
    'lesson': '生成可交给外部AI的自包含教案，小节数和分批方式随内容决定。',
    'record': '区分用户提问、AI讲解、用户确认和实际作答，保留并列/递归问题及未收口项。',
    'assessment': '只判断真实回答覆盖的范围；公共理解和项目应用分开，不以解释过代替理解。',
    'note': '生成连贯可读的正式正文，公共知识复用身份，项目笔记解释职责与实际处理通路。',
    'organize': '先查已有身份和正文，再提交明确关系与考察覆盖；不凭关键词合并知识或题目。',
    'review': '登记用户实际接触过的原题批次，保留原题身份和范围，不自动改为掌握或另出题。',
}
# Import-time compatibility templates only. An open workspace has its own copy.
METHODS = {}


def register_strategy(strategy_id, stage, instructions, prepare=None, transform=None):
    if stage not in DEFAULTS or not strategy_id or not instructions:
        raise ValidationError('Unknown workflow stage or empty strategy')
    METHODS[strategy_id] = dict(id=strategy_id, stage=stage, instructions=instructions,
                                prepare=prepare, transform=transform)


class StrategyRegistry:
    def __init__(self):
        self.entries = {sid: dict(id=sid, stage=stage, instructions=text,
                                prepare=None, transform=None)
                        for stage, text in DEFAULTS.items() for sid in ['default.' + stage]}
        self.entries.update(deepcopy(METHODS))
        for sid, method in production.STRATEGIES.items():
            self.entries[sid] = dict(method, stage=method['operation'],
                                      operation=method['operation'] + '.publish', transform=None)

    def register(self, strategy_id, operation, instructions, prepare=None, transform=None, profile=None):
        descriptor = contracts.get(operation)
        if not strategy_id or not instructions:
            raise ValidationError('A strategy needs id and instructions')
        self.entries[strategy_id] = dict(id=strategy_id, operation=operation,
            stage=descriptor['stage'], profile=profile, instructions=instructions,
            prepare=prepare, transform=transform)

    def select(self, strategy_id, operation, profile=None):
        method = self.entries.get(strategy_id)
        if (not method or method['stage'] != contracts.get(operation)['stage']
                or method.get('operation', operation) != operation
                or profile and method.get('profile') not in (None, profile)):
            raise ValidationError('Unknown or incompatible strategy: ' + str(strategy_id))
        return method

    def describe(self, operation=None, include_instructions=False):
        excluded = ('prepare', 'transform') if include_instructions else ('prepare', 'transform', 'instructions')
        return [{k: v for k, v in item.items() if k not in excluded}
                for item in self.entries.values()
                if operation is None or (item['stage'] == contracts.get(operation)['stage']
                                        and item.get('operation', operation) == operation)]


def available(orch, operation=None):
    return {'contract': CONTRACT, 'stages': list(DEFAULTS),
            'operations': contracts.describe(operation),
            'strategies': orch._strategies.describe(operation),
            'compatibility': {'stage': 'deprecated; new callers select operation explicitly',
                              'tickets': [LEGACY_CONTRACT, CONTRACT]}}


def prepare(orch, stage=None, scope=None, inputs=None, strategy_id=None, operation=None, controls=None):
    scope, inputs = deepcopy(scope or {}), deepcopy(inputs or {})
    legacy = operation is None
    operation = operation or compat.operation(stage, scope)
    descriptor = contracts.get(operation)
    if stage and stage != descriptor['stage']:
        raise ValidationError('stage does not match operation')
    schema = deepcopy(descriptor['scope_schema'])
    if legacy:
        schema['additionalProperties'] = True
    if legacy and operation == 'plan.save' and not scope.get('section_id'):
        schema['required'] = []
    contracts.validate(scope, schema, 'scope')
    contracts.validate(inputs, {'type': 'object'} if legacy else descriptor['input_schema'], 'inputs')
    inputs, strategy_id, cfg = workflow_board.configure(orch, operation, scope, inputs, strategy_id, controls)
    if strategy_id and not scope.get('profile') and descriptor['handler'] == 'content':
        chosen = orch._strategies.entries.get(strategy_id)
        if chosen and chosen.get('profile'):
            scope['profile'] = chosen['profile']
    ticket = {'contract': CONTRACT, 'operation': operation,
              'operation_version': descriptor['version'], 'stage': descriptor['stage'], 'scope': scope}
    if legacy:
        ticket['legacy_stage'] = True
    handler = descriptor['handler']
    if handler == 'content':
        selected = None if strategy_id in (None, 'default.note', 'default.lesson') else strategy_id
        context, prepared = handlers.PREPARERS[handler](orch, scope, inputs,
            descriptor['stage'], selected)
        ticket['strategy_id'] = prepared['content_ticket']['strategy_id']
        instructions = prepared.pop('content_instructions')
    else:
        strategy_id = strategy_id or 'default.' + descriptor['stage']
        method = orch._strategies.select(strategy_id, operation, scope.get('profile'))
        ticket['strategy_id'] = strategy_id
        if legacy and operation == 'plan.save' and not scope.get('course_id'):
            context, prepared = {}, {}
        else:
            context, prepared = handlers.PREPARERS[handler](orch, scope, inputs)
        instructions = method['instructions']
        # Material bundles do not echo a complete transcript alongside its delta.
        context = dict(goal=inputs.get('goal', ''), scope=scope,
                       targets=[], materials=inputs.get('materials', []), state=context, missing=[])
        if legacy:
            context.update(context['state'])
        if method.get('prepare'):
            context = method['prepare'](deepcopy(context))
            context['scope'] = deepcopy(scope)
    ticket.update(prepared)
    json.dumps(context)
    return workflow_board.attach({'ticket': ticket, 'instructions': instructions, 'context': context,
            'artifact_schema': deepcopy(descriptor['artifact_schema']),
            'effects': descriptor['writes'],
            'next': 'Generate the artifact, then commit_workflow(request_id,ticket,artifact)'}, cfg)


def commit(orch, request_id, ticket, artifact):
    if not isinstance(request_id, str) or not request_id.strip():
        raise ValidationError('request_id is required')
    contracts.validate(ticket, {'type': 'object'}, 'ticket')
    contracts.validate(artifact, {'type': 'object'}, 'artifact')
    digest, previous = review_graph._request(orch.conn, request_id, 'workflow',
                                           dict(ticket=ticket, artifact=artifact))
    if previous is not None:
        return previous
    if ticket.get('contract') not in (CONTRACT, LEGACY_CONTRACT):
        raise ValidationError('Unsupported workflow contract')
    legacy = ticket.get('contract') == LEGACY_CONTRACT or ticket.get('legacy_stage', False)
    if legacy:
        operation, scope, data = compat.translate(ticket, artifact)
    else:
        operation, scope, data = ticket.get('operation'), dict(ticket['scope']), deepcopy(artifact)
    descriptor = contracts.get(operation)
    if not legacy and ticket.get('operation_version') != descriptor['version']:
        raise ValidationError('Unsupported operation version; prepare again')
    method = orch._strategies.select(ticket['strategy_id'], operation, scope.get('profile'))
    if method.get('transform') and descriptor['handler'] != 'content':
        data = method['transform'](data)
    if not legacy:
        contracts.validate(scope, descriptor['scope_schema'], 'scope')
        contracts.validate(data, descriptor['artifact_schema'], 'artifact')
    with transaction(orch.conn):
        if legacy and operation == 'record.learning':
            result = compat.commit_learning(orch, scope, data)
        else:
            result = handlers.COMMITTERS[descriptor['handler']](
                orch, request_id + ':' + operation, scope, data, ticket)
        workflow_board.record_result(orch, request_id, ticket, result)
        return review_graph._receipt(orch.conn, request_id, 'workflow', digest,
            {'success': True, 'operation': operation, 'stage': descriptor['stage'], 'result': result})
