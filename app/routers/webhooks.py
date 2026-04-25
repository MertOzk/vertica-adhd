"""Home Assistant notification-action webhook.

HA's automation pipes `mobile_app_notification_action` events here. See README
for the 10-line automation snippet.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session, select

from app.db import get_session
from app.models import Day, User
from app.scheduler import evening_ping, morning_ping

router = APIRouter()


@router.post("/webhook/ha")
async def ha_action(request: Request, session: Session = Depends(get_session)) -> dict:
    body = await request.json()
    action = (body.get("action") or "").strip()
    user = session.exec(select(User)).first()
    if not user:
        return {"ok": False, "reason": "no_user"}

    today_iso = date.today().isoformat()
    day = session.exec(select(Day).where(Day.user_id == user.id, Day.date == today_iso)).first()

    if action == "snooze_30":
        # Best-effort: we don't reschedule APScheduler; we just re-fire the
        # relevant ping in 30 minutes. For v1 we keep it simple — the ping
        # fires again immediately via a one-off timer.
        import asyncio
        which = body.get("protocol", "morning")
        async def _delayed():
            await asyncio.sleep(30 * 60)
            if which == "evening":
                await evening_ping()
            else:
                await morning_ping()
        asyncio.create_task(_delayed())
        return {"ok": True, "snoozed": 30}

    if action == "skip_today":
        if not day:
            day = Day(user_id=user.id, date=today_iso)
            session.add(day)
        day.reflection = (day.reflection or "") + "\nSkipped today (no shame, just data)."
        session.add(day)
        session.commit()
        return {"ok": True, "skipped": True}

    # open_chat is handled client-side by the notification's `url` — we never
    # see it here unless HA also forwards it.
    return {"ok": True, "noop": action}
