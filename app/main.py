"""FastAPI entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import apply_migrations, engine
from app.routers import api, chat, dashboard, mobile, webhooks
from app.scheduler import shutdown_scheduler, start_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("vertica-adhd")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting Vertica ADHD coach")
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.daily_dir.mkdir(parents=True, exist_ok=True)
    _seed_coach_manual()
    apply_migrations()
    _seed_if_needed()
    start_scheduler()
    yield
    shutdown_scheduler()
    engine.dispose()


def _seed_coach_manual() -> None:
    """If COACH.md is missing in the data dir, copy the bundled default."""
    target = settings.coach_manual_path
    if target.exists():
        return
    bundled = Path("/app/seed/COACH.md")
    if bundled.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(bundled.read_text(encoding="utf-8"), encoding="utf-8")
        log.info("Seeded COACH.md → %s", target)


def _seed_if_needed() -> None:
    from sqlmodel import Session, select

    from app.brain_sync import sync_all
    from app.models import User

    with Session(engine) as session:
        user = session.exec(select(User)).first()
        if user is None:
            user = User(
                name=settings.user_name,
                timezone=settings.user_timezone,
                morning_cron=settings.morning_cron,
                evening_cron=settings.evening_cron,
                ha_notify_target=settings.ha_notify_target or None,
            )
            session.add(user)
            session.commit()
            log.info("Seeded user row for %s", user.name)
        # Write initial derived files
        sync_all(session)


app = FastAPI(
    title="Vertica ADHD Coach",
    version="0.1.0",
    lifespan=lifespan,
)

static_dir = Path(__file__).parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

app.include_router(dashboard.router)
app.include_router(mobile.router)
app.include_router(chat.router)
app.include_router(api.router)
app.include_router(webhooks.router)
