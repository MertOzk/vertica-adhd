"""Portrait dashboard view — always-on kiosk page."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.db import get_session
from app.models import Day, Task, User, Win
from app.xp import level_name

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _context(session: Session) -> dict:
    user = session.exec(select(User)).first()
    if not user:
        return {"error": "no_user"}

    today_iso = date.today().isoformat()
    today_row = session.exec(
        select(Day).where(Day.user_id == user.id, Day.date == today_iso)
    ).first()

    top3: list[Task] = []
    current: Task | None = None
    if today_row:
        top3 = session.exec(
            select(Task).where(
                Task.parent_day_id == today_row.id,
                Task.category.in_(["must", "should", "want"]),  # type: ignore[attr-defined]
            ).order_by(Task.id)  # type: ignore[arg-type]
        ).all()
        current = next((t for t in top3 if t.status == "in_progress"), None)

    wins = session.exec(
        select(Win).where(Win.user_id == user.id).order_by(Win.logged_at.desc()).limit(8)  # type: ignore[attr-defined]
    ).all()

    xp_in_level = user.total_xp % 100
    return {
        "user": user,
        "now": datetime.now(),
        "today": today_row,
        "top3": top3,
        "current": current,
        "wins": wins,
        "level_name": level_name(user.level),
        "xp_in_level": xp_in_level,
        "xp_needed": 100,
    }


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    ctx = _context(session)
    ctx["request"] = request
    return templates.TemplateResponse("dashboard.html", ctx)


@router.get("/partials/status", response_class=HTMLResponse)
async def status_partial(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    """HTMX polls this every 20s to refresh the live parts without a full reload."""
    ctx = _context(session)
    ctx["request"] = request
    return templates.TemplateResponse("partials/status.html", ctx)


@router.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}
