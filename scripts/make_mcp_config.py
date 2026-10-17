"""Generate this machine's MCP configuration, using its own Python/workspace."""
import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    config = {'mcpServers': {'learning_orchestrator': {
        'command': sys.executable, 'args': ['-m', 'learning_orchestrator.mcp_server'],
        'env': {'LEARNING_ORCHESTRATOR_WORKSPACE': str(args.workspace.resolve())}}}}
    text = json.dumps(config, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.write_text(text, encoding='utf-8')
    else:
        print(text)


if __name__ == '__main__':
    main()
