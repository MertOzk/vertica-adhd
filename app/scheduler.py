"""APScheduler wiring. Runs inside the FastAPI process — no separate container.

Jobs:
  - morning_ping: fires at user.morning_cron, sends HA notification to invite planning
  - evening_ping: fires at user.evening_cron, same for review
  - weekly_sweep_ping: Sundays at 20:00, sends weekly-sweep invite

All jobs are idempotent — if the server restarts and misses a fire, we pick
up on the next scheduled time. Missed check-ins are no-ops; the streak logic
handles them gracefully.
"""
from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session, select

from app.config import settings
from app.db import engine
from app.models import User
from app.notifications import Action, notify

log = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def _cron(expr: str, tz: str) -> CronTrigger:
    minute, hour, dom, month, dow = expr.split()
    return CronTrigger(
        minute=minute, hour=hour, day=dom, month=month, day_of_week=dow, timezone=tz
    )


async def morning_ping() -> None:
    await notify(
        title="Morning plan",
        message="Ready to plan today? 3 tasks, 2 min to set up.",
        url=f"{settings.public_url}/m/chat?protocol=morning",
        actions=[
            Action("open_chat", "Start plan"),
            Action("snooze_30", "Snooze 30m"),
            Action("skip_today", "Skip today"),
        ],
        time_sensitive=True,
    )


async def evening_ping() -> None:
    await notify(
        title="Evening review",
        message="Quick end-of-day — 5 minutes. What moved today?",
        url=f"{settings.public_url}/m/chat?protocol=evening",
        actions=[
            Action("open_chat", "Start review"),
            Action("snooze_30", "Snooze 30m"),
            Action("skip_today", "Skip today"),
        ],
        time_sensitive=True,
    )


async def weekly_sweep_ping() -> None:
    await notify(
        title="Weekly sweep",
        message="Let's tidy the open loops list — takes about 3 minutes.",
        url=f"{settings.public_url}/m/chat?protocol=weekly_sweep",
        actions=[Action("open_chat", "Start sweep")],
    )


def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    with Session(engine) as session:
        user = session.exec(select(User)).first()
        if user is None:
            log.warning("No user row found; skipping scheduler start. Run scripts/seed.py first.")
            return AsyncIOScheduler()
        tz = user.timezone
        morning = user.morning_cron
        evening = user.evening_cron

    scheduler = AsyncIOScheduler(timezone=tz)
    scheduler.add_job(morning_ping, _cron(morning, tz), id="morning_ping", replace_existing=True)
    scheduler.add_job(evening_ping, _cron(evening, tz), id="evening_ping", replace_existing=True)
    scheduler.add_job(
        weekly_sweep_ping,
        _cron("0 20 * * 0", tz),
        id="weekly_sweep_ping",
        replace_existing=True,
    )
    scheduler.start()
    log.info("Scheduler started: morning=%s, evening=%s (tz=%s)", morning, evening, tz)
    _scheduler = scheduler
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
