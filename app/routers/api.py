"""JSON API for integrations and the dashboard's live widgets."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.db import get_session
from app.models import Day, OpenLoop, Task, User, Win
from app.xp import level_name

router = APIRouter(prefix="/api")


@router.get("/state")
def state(session: Session = Depends(get_session)) -> dict:
    user = session.exec(select(User)).first()
    if not user:
        return {"error": "no_user"}
    today_iso = date.today().isoformat()
    today_row = session.exec(select(Day).where(Day.user_id == user.id, Day.date == today_iso)).first()
    top3 = []
    if today_row:
        top3 = [
            {
                "id": t.id,
                "text": t.text,
                "category": t.category,
                "status": t.status,
                "estimate_minutes": t.estimate_minutes,
                "first_2min_step": t.first_2min_step,
            }
            for t in session.exec(
                select(Task).where(
                    Task.parent_day_id == today_row.id,
                    Task.category.in_(["must", "should", "want"]),  # type: ignore[attr-defined]
                ).order_by(Task.id)  # type: ignore[arg-type]
            ).all()
        ]
    loops = session.exec(
        select(OpenLoop).where(OpenLoop.user_id == user.id, OpenLoop.closed_at.is_(None))  # type: ignore[attr-defined]
    ).all()
    recent_wins = session.exec(
        select(Win).where(Win.user_id == user.id).order_by(Win.logged_at.desc()).limit(10)  # type: ignore[attr-defined]
    ).all()
    return {
        "user": {
            "name": user.name,
            "streak": user.current_streak,
            "longest_streak": user.longest_streak,
            "xp": user.total_xp,
            "level": user.level,
            "level_name": level_name(user.level),
            "xp_in_level": user.total_xp % 100,
        },
        "today": {
            "date": today_iso,
            "morning_done": bool(today_row and today_row.morning_plan_completed_at),
            "evening_done": bool(today_row and today_row.evening_review_completed_at),
            "xp_earned": today_row.xp_earned if today_row else 0,
            "energy": today_row.energy if today_row else None,
        },
        "top3": top3,
        "open_loops": [{"id": l.id, "text": l.text, "next_action": l.next_action} for l in loops],
        "recent_wins": [{"id": w.id, "text": w.text, "xp": w.xp_awarded, "at": w.logged_at} for w in recent_wins],
    }
