"""Learning Orchestrator: deterministic state/progress store for AI-guided learning.

The package is layered so that the core (db, graph, sessions, progress,
sources, context, service) is pure standard-library Python and testable
without the MCP adapter or the dashboard.
"""

__version__ = "0.2.0"
