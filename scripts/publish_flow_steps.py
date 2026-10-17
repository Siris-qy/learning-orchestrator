"""Publish an authored flow/step/knowledge pack through the ordinary workflow."""
import argparse
import json
from pathlib import Path

from learning_orchestrator.service import Orchestrator


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('pack', type=Path)
    p.add_argument('--workspace')
    args = p.parse_args()
    pack = json.loads(args.pack.read_text(encoding='utf-8'))
    o = Orchestrator(workspace=args.workspace)
    try:
        job = o.prepare_workflow(operation='graph.commit', scope={'project_id': pack['project_id']},
            inputs={'goal': '登记已审阅的流程步骤和逐步知识用途'})
        receipt = o.commit_workflow(request_id=pack['request_id'], ticket=job['ticket'],
                                    artifact={'flow_steps': pack['flow_steps']})
        print(json.dumps(dict(success=receipt['success'], flows=len(pack['flow_steps']),
            steps=sum(len(f['steps']) for f in pack['flow_steps']), request_id=pack['request_id']), ensure_ascii=False))
    finally:
        o.close()


if __name__ == '__main__':
    main()
