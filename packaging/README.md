# Source distribution and local plugin

LO 0.2 source handoff: follow the root README to create an independent workspace.
`scripts/make_mcp_config.py --workspace <path>` uses the recipient's Python, without
the maintainer's drive or cache paths. `scripts/build_release.py` packages source,
the frontend and a synthetic demo; private notes and runtime data stay outside it.

The bundled .mcp.json is a generic example. For actual use generate configuration
with the installed virtual-environment Python so both that executable and the
workspace path resolve on the recipient's machine. Load the skill together with
its reference directory in the AI client. See docs/使用指南.md for the normal flow.

The source distribution includes the application, local frontend libraries and
their notices, skills, documentation and synthetic examples. It omits runtime
databases, private notes, transcripts, imported documents and personal note images.
