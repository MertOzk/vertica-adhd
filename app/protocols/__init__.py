"""Protocol handlers. One module per coaching protocol.

Each module exposes:
  - handle_tool(name, args, session, user, conversation) -> str
    (returns a human-readable tool result that goes back to the LLM as a `tool` message)

Add new protocols here by creating a new file and appending to PROTOCOLS.
"""
from __future__ import annotations

from app.protocols import adhoc, evening, morning, unstuck, weekly_sweep

PROTOCOLS = {
    "morning": morning,
    "evening": evening,
    "unstuck": unstuck,
    "weekly_sweep": weekly_sweep,
    "adhoc": adhoc,
}
