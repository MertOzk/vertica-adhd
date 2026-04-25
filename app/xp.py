"""XP, streak, and level logic. Kept out of the LLM — server-computed, deterministic.

Rules per COACH.md:
  +1 XP per completed task (any size)
  +5 bonus per top-3 task completed
  +10 bonus if all three top-3 done in a day
  +3 for completing morning plan
  +3 for completing evening review
  Level up every 100 XP
  Streak = consecutive days with BOTH morning plan AND evening review logged
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlmodel import Session, select

from app.models import Day, Task, User

LEVEL_NAMES = [
    "Initiate", "Apprentice", "Steady", "Committed", "Consistent",
    "Reliable", "Solid", "Formidable", "Disciplined", "Master",
]


def level_name(level: int) -> str:
    return LEVEL_NAMES[min(level - 1, len(LEVEL_NAMES) - 1)]


def level_from_xp(xp: int) -> int:
    return max(1, xp // 100 + 1)


def xp_for_task_complete(task: Task, all_top_3_done: bool) -> int:
    base = 1
    if task.category in ("must", "should", "want"):
        base += 5
    if all_top_3_done:
        base += 10  # applied once to the final task that closes the sweep
    return base


def award_xp(session: Session, user: User, amount: int, day: Day | None = None) -> None:
    user.total_xp += amount
    user.level = level_from_xp(user.total_xp)
    if day:
        day.xp_earned += amount
    session.add(user)
    if day:
        session.add(day)


def recompute_streak(session: Session, user: User, today: date) -> None:
    """Walk backwards from today and count consecutive days where both
    morning and evening review are logged. Updates current_streak and
    longest_streak in-place. Call after either protocol completes.
    """
    streak = 0
    cursor = today
    while True:
        stmt = select(Day).where(Day.user_id == user.id, Day.date == cursor.isoformat())
        day = session.exec(stmt).first()
        if (
            day is None
            or day.morning_plan_completed_at is None
            or day.evening_review_completed_at is None
        ):
            break
        streak += 1
        cursor -= timedelta(days=1)

    user.current_streak = streak
    if streak > user.longest_streak:
        user.longest_streak = streak
    user.last_checkin_date = today.isoformat()
    session.add(user)
