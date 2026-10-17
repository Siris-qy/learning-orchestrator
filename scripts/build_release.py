"""Build a source distribution for GitHub handoff, excluding personal content."""
import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('dist/learning-orchestrator-0.2.0-source.zip'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    files = []
    for directory in ('src/learning_orchestrator', 'dashboard_static', 'skills', 'examples'):
        files.extend(p for p in (root / directory).rglob('*') if p.is_file()
                     and '__pycache__' not in p.parts and '.egg-info' not in str(p)
                     and not (directory == 'dashboard_static'
                              and 'note-assets' in p.relative_to(root / directory).parts))
    for name in ('README.md', 'KNOWLEDGE_STANDARD.md', 'pyproject.toml', '.gitignore',
                 '.codex-plugin/plugin.json', 'packaging/README.md', 'packaging/.mcp.json',
                 'docs/design/2026-10-16-统一接口实现与目录说明.md',
                 'docs/design/LO接口使用规范.md', 'docs/使用指南.md',
                 'docs/requirements/2026-10-10-知识图接口使用说明.md',
                 'scripts/launch_dashboard.cmd', 'scripts/launch_dashboard.sh',
                 'scripts/launch_mcp.cmd', 'scripts/launch_mcp.sh',
                 'scripts/make_mcp_config.py', 'scripts/publish_content_pack.py',
                 'scripts/publish_flow_steps.py', 'scripts/build_release.py'):
        files.append(root / name)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(args.output, 'w', compression=ZIP_DEFLATED) as archive:
        for file in files:
            archive.write(file, 'learning-orchestrator/' + file.relative_to(root).as_posix())
        archive.write(root / 'packaging/.mcp.json', 'learning-orchestrator/.mcp.json')
    print(str(args.output.resolve()))


if __name__ == '__main__':
    main()
