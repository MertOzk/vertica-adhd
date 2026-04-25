"""Keep the DB and the markdown brain folder in sync.

Principle: the DB is the fast queryable projection; markdown is the human-
readable source of truth. On every write we rewrite the affected markdown
file from the DB. On startup we parse any markdown files that are newer than
their DB counterpart (so a human edit in a text editor propagates back).

For v1 we implement the write path (DB -> markdown). The parse path is
stubbed and called on boot; we'll expand it as the file formats stabilize.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

from app.config import settings
from app.models import Day, OpenLoop, Task, User, Win


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content)
    tmp.replace(path)


def render_day(session: Session, day: Day) -> str:
    """Render a single day's file from DB state."""
    tasks = session.exec(
        select(Task).where(Task.parent_day_id == day.id).order_by(Task.id)  # type: ignore[arg-type]
    ).all()
    wins = session.exec(
        select(Win).where(Win.day_id == day.id).order_by(Win.logged_at)  # type: ignore[arg-type]
    ).all()

    date_obj = datetime.fromisoformat(day.date).date()
    heading = date_obj.strftime("%A, %B %-d, %Y")

    def box(t: Task) -> str:
        return "[x]" if t.status == "done" else "[ ]"

    top3 = [t for t in tasks if t.category in ("must", "should", "want")]
    extras = [t for t in tasks if t.category == "extra"]

    lines = [
        f"# {heading}",
        "",
        "## Morning check-in",
        f"- Energy: {day.energy or '__'}/10",
        f"- Meds: {day.meds_taken_at or '[ ] taken at __'}",
        f"- Sleep: {day.sleep_hours if day.sleep_hours is not None else '__'} hrs",
        f"- Weather in my head: {day.head_weather or ''}",
        "",
        "## Top 3",
    ]
    for i, t in enumerate(top3, 1):
        est = f"(est: {t.estimate_minutes} min)" if t.estimate_minutes else ""
        lines.append(f"{i}. {box(t)} {t.category.upper()}: {t.text} {est}".rstrip())
        if t.first_2min_step:
            lines.append(f"   - First 2-min step: {t.first_2min_step}")
    if not top3:
        lines.append("_(not set yet — open chat to plan)_")

    lines += ["", "## Extras"]
    for t in extras:
        lines.append(f"- {box(t)} {t.text}")
    if not extras:
        lines.append("_(none)_")

    lines += ["", "## Wins today"]
    for w in wins:
        lines.append(f"- {w.text}  (+{w.xp_awarded} XP)")
    if not wins:
        lines.append("_(none yet)_")

    lines += [
        "",
        "## Evening review",
        f"- Top 3 status: {sum(1 for t in top3 if t.status == 'done')}/{len(top3)}",
        f"- XP earned today: {day.xp_earned}",
        f"- Morning plan: {'✓' if day.morning_plan_completed_at else '—'}",
        f"- Evening review: {'✓' if day.evening_review_completed_at else '—'}",
        "",
        "## Reflection",
        day.reflection or "",
        "",
        "## 1% easier tomorrow",
        day.one_percent_easier_tomorrow or "",
        "",
    ]
    return "\n".join(lines)


def write_day_markdown(session: Session, day: Day) -> None:
    path = settings.daily_dir / f"{day.date}.md"
    _atomic_write(path, render_day(session, day))


def write_streaks_json(user: User) -> None:
    from app.xp import level_name
    data = {
        "current_streak": user.current_streak,
        "longest_streak": user.longest_streak,
        "total_xp": user.total_xp,
        "level": user.level,
        "level_name": level_name(user.level),
        "grace_days_used_this_month": user.grace_days_used_this_month,
        "grace_days_month": user.grace_days_month,
        "last_checkin_date": user.last_checkin_date,
    }
    _atomic_write(settings.brain_dir / "streaks.json", json.dumps(data, indent=2) + "\n")


def write_open_loops_markdown(session: Session, user: User) -> None:
    active = session.exec(
        select(OpenLoop).where(OpenLoop.user_id == user.id, OpenLoop.closed_at.is_(None))  # type: ignore[attr-defined]
    ).all()
    closed = session.exec(
        select(OpenLoop)
        .where(OpenLoop.user_id == user.id, OpenLoop.closed_at.is_not(None))  # type: ignore[attr-defined]
        .order_by(OpenLoop.closed_at.desc())  # type: ignore[attr-defined]
        .limit(20)
    ).all()
    lines = [
        "# Open Loops",
        "",
        "## Active",
        "",
    ]
    if active:
        for loop in active:
            lines.append(f"- [ ] {loop.text} — opened {loop.opened_at[:10]} — next: {loop.next_action}")
    else:
        lines.append("_(nothing active)_")
    lines += ["", "## Recently closed", ""]
    for loop in closed:
        lines.append(f"- [x] {loop.text} — closed {loop.closed_at[:10] if loop.closed_at else ''}")
    _atomic_write(settings.brain_dir / "open-loops.md", "\n".join(lines) + "\n")


def write_wins_markdown(session: Session, user: User, limit: int = 200) -> None:
    wins = session.exec(
        select(Win)
        .where(Win.user_id == user.id)
        .order_by(Win.logged_at.desc())  # type: ignore[attr-defined]
        .limit(limit)
    ).all()
    lines = ["# Wins", "", "Every win, no matter how small.", ""]
    current_date = None
    for w in wins:
        d = w.logged_at[:10]
        if d != current_date:
            lines += ["", f"## {d}"]
            current_date = d
        lines.append(f"- {w.text}  (+{w.xp_awarded} XP)")
    _atomic_write(settings.brain_dir / "wins.md", "\n".join(lines) + "\n")


def sync_all(session: Session) -> None:
    """Convenience: rewrite every derived file. Called after big protocol completions."""
    user = session.exec(select(User)).first()
    if not user:
        return
    write_streaks_json(user)
    write_open_loops_markdown(session, user)
    write_wins_markdown(session, user)
    # Today's day file, if present
    today = datetime.utcnow().date().isoformat()
    day = session.exec(select(Day).where(Day.user_id == user.id, Day.date == today)).first()
    if day:
        write_day_markdown(session, day)
