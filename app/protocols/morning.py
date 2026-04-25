"""Morning plan protocol — the fully-wired reference implementation.

The chat loop itself lives in app/routers/chat.py (since it's HTTP-driven).
This module owns the tool handlers: what happens when the LLM calls a tool
during a morning conversation.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from sqlmodel import Session, select

from app.brain_sync import sync_all, write_day_markdown
from app.models import Conversation, Day, OpenLoop, Task, User
from app.xp import award_xp, recompute_streak


def _get_or_create_today(session: Session, user: User, today: date) -> Day:
    day = session.exec(
        select(Day).where(Day.user_id == user.id, Day.date == today.isoformat())
    ).first()
    if day is None:
        day = Day(user_id=user.id, date=today.isoformat())  # type: ignore[arg-type]
        session.add(day)
        session.commit()
        session.refresh(day)
    return day


def handle_tool(
    name: str,
    args: dict[str, Any],
    session: Session,
    user: User,
    conversation: Conversation,
) -> str:
    today = date.today()
    day = _get_or_create_today(session, user, today)
    now = datetime.utcnow().isoformat()

    if name == "add_to_inbox":
        # Inbox items become adhoc tasks with status=pending. They're not
        # part of top 3 but show up on the dashboard so nothing is lost.
        items = args.get("items", [])
        for text in items:
            session.add(Task(
                user_id=user.id,
                parent_day_id=day.id,
                text=text,
                category="adhoc",
                status="pending",
                created_at=now,
            ))
        session.commit()
        return f"Added {len(items)} items to today's inbox."

    if name == "log_energy":
        day.energy = args.get("energy")
        day.meds_taken_at = args.get("meds_taken_at")
        day.sleep_hours = args.get("sleep_hours")
        day.head_weather = args.get("head_weather")
        session.add(day)
        session.commit()
        return f"Logged: energy {day.energy}/10, sleep {day.sleep_hours}h."

    if name == "set_top_3":
        # Wipe any previous top-3 for today, then insert new ones.
        existing = session.exec(
            select(Task).where(
                Task.parent_day_id == day.id,
                Task.category.in_(["must", "should", "want"]),  # type: ignore[attr-defined]
            )
        ).all()
        for t in existing:
            session.delete(t)

        tasks_in = args.get("tasks", [])
        for t in tasks_in:
            session.add(Task(
                user_id=user.id,
                parent_day_id=day.id,
                text=t["text"],
                category=t["category"],
                estimate_minutes=t.get("estimate_minutes"),
                first_2min_step=t["first_2min_step"],
                status="pending",
                created_at=now,
            ))
        session.commit()
        write_day_markdown(session, day)
        return f"Top 3 set: " + ", ".join(f"{t['category']}: {t['text']}" for t in tasks_in)

    if name == "add_open_loop":
        loop = OpenLoop(
            user_id=user.id,
            text=args["text"],
            next_action=args["next_action"],
            opened_at=now,
        )
        session.add(loop)
        session.commit()
        return f"Open loop added: {loop.text}"

    if name == "finalize_morning_plan":
        day.morning_plan_completed_at = now
        award_xp(session, user, 3, day)  # +3 for completing morning plan
        conversation.ended_at = now
        session.add(conversation)
        session.commit()
        recompute_streak(session, user, today)
        session.commit()
        sync_all(session)
        return f"Morning plan finalized. Streak: {user.current_streak} days. +3 XP."

    return f"Unknown tool: {name}"
