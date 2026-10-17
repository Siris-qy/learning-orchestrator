"""Example: add examples.strategy_ext to lo.json strategy_modules."""
def register(orch):
    orch.register_workflow_strategy('example.scenario-note', 'note.publish',
        '以一个输入案例组织项目笔记，解释每一步为什么需要下一步；保留必要代码和知识入口。',
        prepare=lambda context: dict(context, output_style='scenario'))
