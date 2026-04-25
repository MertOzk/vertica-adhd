"""Weekly sweep — walks old open loops, offers close/delete/schedule decisions."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import Session

from app.models import Conversation, OpenLoop, User


def handle_tool(
    name: str,
    args: dict[str, Any],
    session: Session,
    user: User,
    conversation: Conversation,
) -> str:
    now = datetime.utcnow().isoformat()
    if name == "close_open_loop":
        loop = session.get(OpenLoop, args["loop_id"])
        if not loop:
            return f"Loop {args['loop_id']} not found."
        loop.closed_at = now
        loop.notes = (loop.notes or "") + f"\nSwept: {args['resolution']}"
        session.add(loop)
        session.commit()
        return f"Closed '{loop.text}' ({args['resolution']})"
    return f"Unknown tool: {name}"
