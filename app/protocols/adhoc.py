"""Ad-hoc chat — user just wants to talk. All tools available.

We delegate to the other protocol handlers where possible so logic stays in one place.
"""
from __future__ import annotations

from typing import Any

from sqlmodel import Session

from app.models import Conversation, User
from app.protocols import evening as evening_mod
from app.protocols import morning as morning_mod


def handle_tool(
    name: str,
    args: dict[str, Any],
    session: Session,
    user: User,
    conversation: Conversation,
) -> str:
    # Morning-side tools
    if name in {"add_to_inbox", "log_energy", "set_top_3", "finalize_morning_plan"}:
        return morning_mod.handle_tool(name, args, session, user, conversation)
    # Evening-side tools
    if name in {
        "mark_task_done", "defer_task", "add_win", "add_open_loop",
        "close_open_loop", "finalize_evening_review",
    }:
        return evening_mod.handle_tool(name, args, session, user, conversation)
    return f"Unknown tool: {name}"
