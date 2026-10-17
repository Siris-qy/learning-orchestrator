"""Portable workspace configuration and an explicitly requested synthetic demo."""
import argparse
import json
import os
from pathlib import Path

from .graph import ValidationError


def load(path=None):
    value = path or os.environ.get('LEARNING_ORCHESTRATOR_WORKSPACE')
    if not value:
        return None
    root = Path(value).expanduser().resolve()
    config_file = root / 'lo.json'
    config = json.loads(config_file.read_text(encoding='utf-8')) if config_file.exists() else {}
    def resolve(value):
        return str((root / value).resolve())
    seed = config.get('seed', 'empty')
    if seed not in ('empty', 'demo', 'legacy'):
        raise ValidationError('workspace seed must be empty, demo or legacy')
    return {'root': str(root), 'database': resolve(config.get('database', 'data/learning_orchestrator.db')),
            'source_roots': [resolve(p) for p in config.get('source_roots', ['sources', 'notes'])],
            'seed': seed, 'strategy_modules': config.get('strategy_modules', [])}


def seed_demo(orch):
    """No user materials or fabricated learning: just one documented request path."""
    from . import graph, questions
    if not graph.node_exists(orch.conn, 'demo-course'):
        graph.add_node(orch.conn, 'demo-course', 'demo-course', 'course', '示例：请求分发')
        graph.add_node(orch.conn, 'demo-unit', 'demo-course', 'unit', '请求分发与资源管理')
    orch.commit_review_map(request_id='demo-structure-v1', nodes=[
        {'id': 'demo-project', 'kind': 'project', 'title': '示例服务', 'summary': '请求进入后按方法分发，处理完成返回结果。'},
        {'id': 'demo-module', 'kind': 'module', 'title': '请求处理'},
        {'id': 'demo-flow', 'kind': 'flow', 'title': '按方法查找处理器'},
        {'id': 'demo-raii', 'kind': 'knowledge', 'title': 'RAII', 'domains': ['cpp']}],
        edges=[{'from': 'demo-project', 'to': 'demo-module', 'relation': 'contains'},
               {'from': 'demo-module', 'to': 'demo-flow', 'relation': 'contains'},
               {'from': 'demo-flow', 'to': 'demo-raii', 'relation': 'uses',
                'context_project_id': 'demo-project', 'usage': '处理器持有资源，由对象析构负责释放。'}])
    bodies = {
        'demo-project': '# 示例服务\n\n服务接收带有方法名的请求，找到处理器，执行后返回结果。\n\n'
            '请求入口 → 方法查找 → 处理器执行 → 响应返回。模块页可以继续看到流程和关联知识。',
        'demo-flow': '# 按方法查找处理器\n\n请求携带method和参数。分发器从处理器表按method查找，找到后传入参数执行；'
            '没有匹配项时返回未知方法错误。\n\n```cpp\nauto it = handlers.find(request.method);\n'
            'if (it == handlers.end()) return method_not_found();\nreturn it->second(request.params);\n```\n\n'
            '例如method为sum时，分发器选中求和处理器，而不需要自己知道求和算法。处理器使用的资源通过RAII管理。',
        'demo-raii': '# RAII\n\n把资源的获得和释放绑定到对象生命周期。构造成功后由对象持有资源，析构时释放。'
            '\n\n例如锁守卫在离开作用域时解锁，中途返回或异常也经过相同的释放路径。'}
    done = orch.conn.execute("SELECT 1 FROM review_graph_requests WHERE id='demo-bodies-v1'").fetchone()
    if not done:
        task = orch.prepare_content_task(operation='note', node_ids=list(bodies))
        orch.commit_content_task(request_id='demo-bodies-v1', ticket=task['ticket'],
            documents=[{'node_id': n, 'body': b} for n, b in bodies.items()])
    orch.commit_review_map(request_id='demo-steps-v1', project_id='demo-project', flow_steps=[
        {'flow_id': 'demo-flow', 'steps': [
            {'id': 'demo-step-read', 'title': '读取方法与参数', 'description': '入口取得请求的方法名和参数，交给分发器。'},
            {'id': 'demo-step-lookup', 'title': '查找处理器', 'description': '按方法名查询处理器表；找不到时返回未知方法错误。'},
            {'id': 'demo-step-execute', 'title': '执行并交回结果', 'description': '调用处理器并返回结果，处理器拥有的资源随对象生命周期释放。',
             'knowledge': [{'node_id': 'demo-raii', 'usage': '中途返回与异常也需要释放处理器获得的资源。'}]}
        ]}])
    if not orch.conn.execute("SELECT 1 FROM questions WHERE id='demo-question'").fetchone():
        questions.import_questions(orch.conn, [{'id': 'demo-question', 'course_id': 'demo-course',
            'stem': '请求如何找到处理器？处理器提前返回时资源怎样释放？',
            'answer_basis': '先按方法名查表；资源交给有明确生命周期的对象管理。'}], 'self_test')
    orch.commit_review_map(request_id='demo-question-link-v1', project_id='demo-project',
        question_links=[{'node_id': 'demo-flow', 'question_id': 'demo-question', 'focus': '请求分发与资源释放'}])
    orch.save_review_batch(request_id='demo-batch-v1', batch_id='demo-review', title='示例服务复盘',
        project_id='demo-project', items=[{'question_id': 'demo-question', 'label': 'Q1',
                                        'node_ids': ['demo-project', 'demo-flow', 'demo-raii']}])
    return {'demo': True, 'project_id': 'demo-project'}


def main():
    parser = argparse.ArgumentParser(description='Create an independent LO workspace')
    parser.add_argument('command', choices=['init'])
    parser.add_argument('--path', required=True, type=Path)
    parser.add_argument('--demo', action='store_true')
    args = parser.parse_args()
    root = args.path.resolve()
    root.mkdir(parents=True, exist_ok=True)
    config_file = root / 'lo.json'
    if not config_file.exists():
        config_file.write_text(json.dumps({'database': 'data/learning_orchestrator.db',
            'source_roots': ['sources', 'notes'], 'seed': 'demo' if args.demo else 'empty',
            'strategy_modules': []}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for directory in ('data', 'notes', 'sources', 'exports', 'documents'):
        (root / directory).mkdir(exist_ok=True)
    from .service import Orchestrator
    orch = Orchestrator(workspace=root)
    try:
        print(json.dumps(orch.initialize(), ensure_ascii=False))
    finally:
        orch.close()


if __name__ == '__main__':
    main()
