"""Manually seed the DB from env. The app's lifespan hook also does this,
but this script is useful for one-off runs (`docker exec ... python scripts/seed.py`).
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make the app package importable when running as a standalone script
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import Session, select  # noqa: E402

from app.brain_sync import sync_all  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import apply_migrations, engine  # noqa: E402
from app.models import User  # noqa: E402


def main() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.daily_dir.mkdir(parents=True, exist_ok=True)
    apply_migrations()
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
            print(f"Seeded user: {user.name}")
        else:
            print(f"User already exists: {user.name}")
        sync_all(session)
        print("Derived files written to", settings.brain_dir)


if __name__ == "__main__":
    main()
