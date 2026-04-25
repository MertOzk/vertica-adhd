"""Task-initiation toolkit. Short protocol — most conversations are under 5 turns.

Tools exposed: add_win, add_open_loop. The coaching itself is in COACH.md;
this module just handles any tool calls that come out of it.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import Session

from app.models import Conversation, OpenLoop, User, Win


def handle_tool(
    name: str,
    args: dict[str, Any],
    session: Session,
    user: User,
    conversation: Conversation,
) -> str:
    now = datetime.utcnow().isoformat()
    if name == "add_win":
        session.add(Win(
            user_id=user.id,
            text=args["text"],
            xp_awarded=args.get("xp", 1),
            logged_at=now,
        ))
        session.commit()
        return f"Logged win: {args['text']}"
    if name == "add_open_loop":
        session.add(OpenLoop(
            user_id=user.id,
            text=args["text"],
            next_action=args["next_action"],
            opened_at=now,
        ))
        session.commit()
        return f"Open loop added: {args['text']}"
    return f"Unknown tool: {name}"
