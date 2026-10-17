"""Historical stage tickets stay readable, but cannot define new operations."""
from copy import deepcopy
from .graph import ValidationError

STAGES = {'plan': 'plan.save', 'context': 'context.prepare', 'lesson': 'lesson.publish',
          'record': 'record.learning', 'assessment': 'assessment.record', 'note': 'note.publish',
          'organize': 'graph.commit', 'review': 'review.save'}


def operation(stage, scope):
    if stage == 'record' and scope.get('batch_id'):
        return 'record.review'
    if stage not in STAGES:
        raise ValidationError('Unknown workflow stage: ' + str(stage))
    return STAGES[stage]


def translate(ticket, artifact):
    """Field-based dispatch exists ONLY for tickets already issued by v1."""
    scope, data = dict(ticket['scope']), deepcopy(artifact)
    op = operation(ticket['stage'], scope)
    if op == 'plan.save' and 'curriculum' in data:
        data = dict(data['curriculum'])
        scope['course_id'] = data.pop('course_id')
        op = 'curriculum.register'
    elif op == 'graph.commit' and 'question_entries' in data:
        data['entries'] = data.pop('question_entries')
        op = 'questions.commit'
    return op, scope, data


def commit_learning(orch, scope, artifact):
    from .operation_handlers import learning_turn
    data = dict(artifact, course_id=scope['course_id'], section_id=scope['section_id'])
    data.setdefault('role', 'detail')
    return learning_turn(orch, **data)


def invoke(orch, operation_name, **kwargs):
    """Translate historical Python/MCP argument shape into the shared handler.

    Return the historical domain receipt, not a new outer workflow envelope.
    Domain validation and writes remain identical to the explicit operation.
    """
    from . import operation_contracts as contracts, operation_handlers as handlers
    descriptor = contracts.get(operation_name)
    data = dict(kwargs)
    request_id = data.pop('request_id', None)
    scope = {k: data.pop(k) for k in contracts.SCOPE_FIELDS[operation_name] if k in data}
    ticket = {}
    if descriptor['handler'] == 'content':
        ticket['content_ticket'] = data.pop('ticket')
    return handlers.COMMITTERS[descriptor['handler']](orch, request_id, scope, data, ticket)
