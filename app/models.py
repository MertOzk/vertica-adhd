"""SQLModel tables. Mirror migrations/001_initial.sql exactly."""
from __future__ import annotations

from datetime import datetime, date as date_cls
from typing import Optional

from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    timezone: str = "America/Los_Angeles"
    morning_cron: str = "0 9 * * *"
    evening_cron: str = "0 21 * * *"
    quiet_hours_start: Optional[str] = "22:30"
    quiet_hours_end: Optional[str] = "08:00"
    ha_notify_target: Optional[str] = None
    current_streak: int = 0
    longest_streak: int = 0
    total_xp: int = 0
    level: int = 1
    grace_days_used_this_month: int = 0
    grace_days_month: Optional[str] = None
    last_checkin_date: Optional[str] = None
    tone_overrides: Optional[str] = None


class Day(SQLModel, table=True):
    __tablename__ = "days"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id")
    date: str  # YYYY-MM-DD
    energy: Optional[int] = None
    meds_taken_at: Optional[str] = None
    sleep_hours: Optional[float] = None
    head_weather: Optional[str] = None
    morning_plan_completed_at: Optional[str] = None
    evening_review_completed_at: Optional[str] = None
    xp_earned: int = 0
    reflection: Optional[str] = None
    one_percent_easier_tomorrow: Optional[str] = None


class Task(SQLModel, table=True):
    __tablename__ = "tasks"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id")
    parent_day_id: Optional[int] = Field(default=None, foreign_key="days.id")
    completed_on_day_id: Optional[int] = Field(default=None, foreign_key="days.id")
    text: str
    category: str  # must | should | want | extra | adhoc
    estimate_minutes: Optional[int] = None
    actual_minutes: Optional[int] = None
    first_2min_step: Optional[str] = None
    status: str = "pending"
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    notes: Optional[str] = None


class OpenLoop(SQLModel, table=True):
    __tablename__ = "open_loops"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id")
    text: str
    next_action: str
    opened_at: str
    closed_at: Optional[str] = None
    source_task_id: Optional[int] = Field(default=None, foreign_key="tasks.id")
    notes: Optional[str] = None


class Win(SQLModel, table=True):
    __tablename__ = "wins"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id")
    day_id: Optional[int] = Field(default=None, foreign_key="days.id")
    text: str
    xp_awarded: int = 1
    logged_at: str


class Conversation(SQLModel, table=True):
    __tablename__ = "conversations"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id")
    day_id: Optional[int] = Field(default=None, foreign_key="days.id")
    kind: str  # morning | evening | unstuck | adhoc | weekly_sweep
    started_at: str
    ended_at: Optional[str] = None


class Message(SQLModel, table=True):
    __tablename__ = "messages"

    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: int = Field(foreign_key="conversations.id")
    role: str  # system | user | assistant | tool
    content: str
    tool_calls: Optional[str] = None  # JSON
    created_at: str
