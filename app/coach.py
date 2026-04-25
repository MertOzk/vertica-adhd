"""Coach prompt assembly and the tool registry.

Every protocol builds its message list with `build_system_prompt()` as message[0]
and fresh user/assistant turns after. Tool schemas are shared — the LLM sees the
same set of tools across all protocols so it can, for instance, call `add_win`
mid-unstuck conversation if that's what the moment calls for.
"""
from __future__ import annotations

from datetime import date, datetime
from textwrap import dedent
from typing import Any

from sqlmodel import Session, select

from app.config import settings
from app.models import Day, OpenLoop, Task, User

# ---------------------------------------------------------------------------
# System prompt assembly
# ---------------------------------------------------------------------------

DEFAULT_COACH_FALLBACK = dedent("""
    You are an ADHD coach. Be warm, direct, and short. Break tasks down to
    2-minute first steps. Never shame. Missing a day is data, not failure.
    Celebrate tiny wins. Use the tools below to update state.
""").strip()


def read_coach_manual() -> str:
    """Read COACH.md fresh on every call so user edits are live."""
    path = settings.coach_manual_path
    if path.exists():
        return path.read_text()
    return DEFAULT_COACH_FALLBACK


def build_system_prompt(
    user: User,
    protocol: str,
    *,
    today: date | None = None,
) -> str:
    today = today or date.today()
    return dedent(f"""
    {read_coach_manual()}

    ---

    CURRENT CONTEXT (automatically injected, do not repeat back to user):
    - Today: {today.isoformat()} ({today.strftime('%A')})
    - Protocol: {protocol}
    - User: {user.name}
    - Streak: {user.current_streak} days
    - Level {user.level}, {user.total_xp} XP total
    - Timezone: {user.timezone}
    {f"- Tone overrides: {user.tone_overrides}" if user.tone_overrides else ""}

    Use the tools when an action is warranted. Do not ask the user to do
    something the tools can do for them. Keep messages short — ADHD brains
    skim. No wall-of-text responses.
    """).strip()


def build_context_brief(session: Session, user: User, today: date) -> str:
    """A compact 'what's going on' summary appended as an assistant primer."""
    yday = session.exec(
        select(Day)
        .where(Day.user_id == user.id, Day.date < today.isoformat())
        .order_by(Day.date.desc())  # type: ignore[attr-defined]
        .limit(1)
    ).first()

    loops = session.exec(
        select(OpenLoop).where(OpenLoop.user_id == user.id, OpenLoop.closed_at.is_(None))  # type: ignore[attr-defined]
    ).all()

    today_row = session.exec(
        select(Day).where(Day.user_id == user.id, Day.date == today.isoformat())
    ).first()

    today_tasks: list[Task] = []
    if today_row:
        today_tasks = session.exec(
            select(Task).where(Task.parent_day_id == today_row.id)
        ).all()

    parts = []
    if yday:
        parts.append(f"Yesterday ({yday.date}): energy {yday.energy or '?'}/10, "
                     f"XP {yday.xp_earned}, reflection: {yday.reflection or '—'}")
    if loops:
        parts.append(f"Open loops ({len(loops)}): " + "; ".join(
            f"{ol.text} → next: {ol.next_action}" for ol in loops[:5]
        ))
    if today_tasks:
        parts.append("Today's tasks so far: " + "; ".join(
            f"{t.category} — {t.text} ({t.status})" for t in today_tasks
        ))
    return "\n".join(parts) or "No prior context."


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------
# OpenAI-compatible tool definitions. Protocols pass a filtered subset to
# the LLM (e.g. morning plan exposes set_top_3 but not mark_task_done).

TOOLS: dict[str, dict[str, Any]] = {
    "add_to_inbox": {
        "type": "function",
        "function": {
            "name": "add_to_inbox",
            "description": "Record brain-dump items in today's inbox. Call as soon as the user mentions things rattling in their head.",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["items"],
            },
        },
    },
    "log_energy": {
        "type": "function",
        "function": {
            "name": "log_energy",
            "description": "Record the user's morning energy (1-10), meds time, sleep hours, and a one-line vibe.",
            "parameters": {
                "type": "object",
                "properties": {
                    "energy": {"type": "integer", "minimum": 1, "maximum": 10},
                    "meds_taken_at": {"type": "string", "description": "ISO time or null"},
                    "sleep_hours": {"type": "number"},
                    "head_weather": {"type": "string"},
                },
                "required": ["energy"],
            },
        },
    },
    "set_top_3": {
        "type": "function",
        "function": {
            "name": "set_top_3",
            "description": "Set the top 3 tasks for today. Must include one MUST, one SHOULD, one WANT. Each needs a first_2min_step.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 3,
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "category": {"type": "string", "enum": ["must", "should", "want"]},
                                "estimate_minutes": {"type": "integer"},
                                "first_2min_step": {"type": "string"},
                            },
                            "required": ["text", "category", "first_2min_step"],
                        },
                    },
                },
                "required": ["tasks"],
            },
        },
    },
    "finalize_morning_plan": {
        "type": "function",
        "function": {
            "name": "finalize_morning_plan",
            "description": "Close the morning conversation. Call only after top 3 is set. The closing_message is what the user sees as the final nudge.",
            "parameters": {
                "type": "object",
                "properties": {
                    "closing_message": {"type": "string"},
                },
                "required": ["closing_message"],
            },
        },
    },
    "mark_task_done": {
        "type": "function",
        "function": {
            "name": "mark_task_done",
            "description": "Mark a task completed. Awards XP and writes a win.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer"},
                    "actual_minutes": {"type": "integer"},
                },
                "required": ["task_id"],
            },
        },
    },
    "defer_task": {
        "type": "function",
        "function": {
            "name": "defer_task",
            "description": "Move an unfinished task somewhere. destination is one of: tomorrow, open_loop, break_down, delete.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer"},
                    "destination": {"type": "string", "enum": ["tomorrow", "open_loop", "break_down", "delete"]},
                    "next_action": {"type": "string", "description": "Required if destination is open_loop"},
                },
                "required": ["task_id", "destination"],
            },
        },
    },
    "add_win": {
        "type": "function",
        "function": {
            "name": "add_win",
            "description": "Log a win. Accepts anything: 'ate lunch', 'answered email', 'took meds'. No win is too small.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "xp": {"type": "integer", "default": 1},
                },
                "required": ["text"],
            },
        },
    },
    "add_open_loop": {
        "type": "function",
        "function": {
            "name": "add_open_loop",
            "description": "Add something started-but-not-finished to the open-loops list. MUST include next_action (the literal next physical action).",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "next_action": {"type": "string"},
                },
                "required": ["text", "next_action"],
            },
        },
    },
    "close_open_loop": {
        "type": "function",
        "function": {
            "name": "close_open_loop",
            "description": "Close an open loop. resolution: done | deleted | scheduled.",
            "parameters": {
                "type": "object",
                "properties": {
                    "loop_id": {"type": "integer"},
                    "resolution": {"type": "string", "enum": ["done", "deleted", "scheduled"]},
                },
                "required": ["loop_id", "resolution"],
            },
        },
    },
    "finalize_evening_review": {
        "type": "function",
        "function": {
            "name": "finalize_evening_review",
            "description": "Close the evening conversation. reflection is a short freeform note; one_percent_easier_tomorrow is the single concrete thing for tomorrow.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reflection": {"type": "string"},
                    "one_percent_easier_tomorrow": {"type": "string"},
                    "closing_message": {"type": "string"},
                },
                "required": ["closing_message"],
            },
        },
    },
}


def tools_for(protocol: str) -> list[dict[str, Any]]:
    sets = {
        "morning": ["add_to_inbox", "log_energy", "set_top_3", "add_open_loop", "finalize_morning_plan"],
        "evening": ["mark_task_done", "defer_task", "add_win", "add_open_loop", "close_open_loop", "finalize_evening_review"],
        "unstuck": ["add_win", "add_open_loop"],
        "weekly_sweep": ["close_open_loop"],
        "adhoc": list(TOOLS.keys()),
    }
    names = sets.get(protocol, [])
    return [TOOLS[n] for n in names if n in TOOLS]
