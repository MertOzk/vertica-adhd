"""Evening review protocol — fully wired.

Shares the same shape as morning.py. See that file for the commentary.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlmodel import Session, select

from app.brain_sync import sync_all
from app.models import Conversation, Day, OpenLoop, Task, User, Win
from app.xp import award_xp, recompute_streak, xp_for_task_complete


def handle_tool(
    name: str,
    args: dict[str, Any],
    session: Session,
    user: User,
    conversation: Conversation,
) -> str:
    today = date.today()
    now = datetime.utcnow().isoformat()
    day = session.exec(
        select(Day).where(Day.user_id == user.id, Day.date == today.isoformat())
    ).first()

    if name == "mark_task_done":
        task = session.get(Task, args["task_id"])
        if not task:
            return f"Task {args['task_id']} not found."
        task.status = "done"
        task.completed_at = now
        task.completed_on_day_id = day.id if day else None
        if args.get("actual_minutes"):
            task.actual_minutes = args["actual_minutes"]
        session.add(task)

        # All-top-3-done bonus: did this close the sweep?
        top3_ids = [
            t.id for t in session.exec(
                select(Task).where(
                    Task.parent_day_id == day.id if day else 0,
                    Task.category.in_(["must", "should", "want"]),  # type: ignore[attr-defined]
                )
            ).all()
        ]
        done_in_top3 = session.exec(
            select(Task).where(
                Task.id.in_(top3_ids),  # type: ignore[attr-defined]
                Task.status == "done",
            )
        ).all()
        all_top3_done = len(done_in_top3) == len(top3_ids) and len(top3_ids) == 3

        xp = xp_for_task_complete(task, all_top3_done)
        award_xp(session, user, xp, day)

        # Auto-log a win
        session.add(Win(
            user_id=user.id,
            day_id=day.id if day else None,
            text=f"Completed: {task.text}",
            xp_awarded=xp,
            logged_at=now,
        ))
        session.commit()
        return f"Marked done: {task.text}. +{xp} XP."

    if name == "defer_task":
        task = session.get(Task, args["task_id"])
        if not task:
            return f"Task {args['task_id']} not found."
        dest = args["destination"]
        if dest == "delete":
            task.status = "deleted"
        elif dest == "tomorrow":
            task.status = "moved"
            # Create a fresh copy with tomorrow's day attached — done on the
            # next morning plan, we just mark it moved here.
            task.notes = (task.notes or "") + f"\nMoved to tomorrow at {now}"
        elif dest == "open_loop":
            next_action = args.get("next_action") or "(define next action)"
            session.add(OpenLoop(
                user_id=user.id,
                text=task.text,
                next_action=next_action,
                opened_at=now,
                source_task_id=task.id,
            ))
            task.status = "moved"
        elif dest == "break_down":
            task.status = "moved"
            task.notes = (task.notes or "") + "\nMarked for breakdown in next morning plan"
        session.add(task)
        session.commit()
        return f"Deferred '{task.text}' → {dest}"

    if name == "add_win":
        xp = args.get("xp", 1)
        session.add(Win(
            user_id=user.id,
            day_id=day.id if day else None,
            text=args["text"],
            xp_awarded=xp,
            logged_at=now,
        ))
        award_xp(session, user, xp, day)
        session.commit()
        return f"Logged win: {args['text']} (+{xp} XP)"

    if name == "add_open_loop":
        session.add(OpenLoop(
            user_id=user.id,
            text=args["text"],
            next_action=args["next_action"],
            opened_at=now,
        ))
        session.commit()
        return f"Open loop added: {args['text']}"

    if name == "close_open_loop":
        loop = session.get(OpenLoop, args["loop_id"])
        if not loop:
            return f"Loop {args['loop_id']} not found."
        loop.closed_at = now
        loop.notes = (loop.notes or "") + f"\nResolution: {args['resolution']}"
        session.add(loop)
        session.commit()
        return f"Closed loop: {loop.text}"

    if name == "finalize_evening_review":
        if day:
            day.evening_review_completed_at = now
            day.reflection = args.get("reflection")
            day.one_percent_easier_tomorrow = args.get("one_percent_easier_tomorrow")
            award_xp(session, user, 3, day)  # +3 for completing evening review
            session.add(day)
        conversation.ended_at = now
        session.add(conversation)
        session.commit()
        recompute_streak(session, user, today)
        session.commit()
        sync_all(session)
        return f"Evening review done. Streak: {user.current_streak}. +3 XP."

    return f"Unknown tool: {name}"
