"""Chat endpoints.

POST /chat/{protocol}/start   → creates a conversation row, returns its id and initial greeting
POST /chat/{protocol}/send    → appends a user message, runs a tool-loop round, returns assistant reply
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.coach import build_context_brief, build_system_prompt, tools_for
from app.db import get_session
from app.llm import chat as llm_chat
from app.models import Conversation, Message, User
from app.protocols import PROTOCOLS

router = APIRouter(prefix="/chat", tags=["chat"])

MAX_TOOL_ROUNDS = 5


class SendBody(BaseModel):
    conversation_id: int
    text: str


def _user(session: Session) -> User:
    user = session.exec(select(User)).first()
    if not user:
        raise HTTPException(500, "No user row — run scripts/seed.py first.")
    return user


def _messages_for_conv(session: Session, conv: Conversation) -> list[dict[str, Any]]:
    rows = session.exec(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.id)  # type: ignore[arg-type]
    ).all()
    out: list[dict[str, Any]] = []
    for m in rows:
        msg: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.tool_calls:
            msg["tool_calls"] = json.loads(m.tool_calls)
        out.append(msg)
    return out


def _persist(session: Session, conv: Conversation, role: str, content: str, tool_calls: Any = None) -> Message:
    m = Message(
        conversation_id=conv.id,
        role=role,
        content=content,
        tool_calls=json.dumps(tool_calls) if tool_calls else None,
        created_at=datetime.utcnow().isoformat(),
    )
    session.add(m)
    session.commit()
    session.refresh(m)
    return m


@router.post("/{protocol}/start")
async def start(protocol: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    if protocol not in PROTOCOLS:
        raise HTTPException(404, f"Unknown protocol {protocol}")
    user = _user(session)
    conv = Conversation(
        user_id=user.id,
        kind=protocol,
        started_at=datetime.utcnow().isoformat(),
    )
    session.add(conv)
    session.commit()
    session.refresh(conv)

    system = build_system_prompt(user, protocol)
    brief = build_context_brief(session, user, datetime.utcnow().date())
    _persist(session, conv, "system", system)
    _persist(session, conv, "system", f"Context brief:\n{brief}")

    # Ask the LLM for an opening message.
    opener_prompt = {
        "morning": "Greet the user warmly and briefly. Ask about energy, meds, sleep — one line each, concise.",
        "evening": "Greet the user. Ask 'what moved today?' — don't ask 'did you finish everything'.",
        "unstuck": "Ask what they're stuck on. Short. Warm. No assumptions.",
        "weekly_sweep": "Introduce the weekly sweep. Say we'll walk through old open loops. Short.",
        "adhoc": "Greet, ask what's up. Short.",
    }[protocol]
    _persist(session, conv, "user", opener_prompt)

    response = await llm_chat(
        messages=_messages_for_conv(session, conv),
        tools=tools_for(protocol),
    )
    reply = response["choices"][0]["message"]
    _persist(session, conv, "assistant", reply.get("content") or "", reply.get("tool_calls"))

    return {
        "conversation_id": conv.id,
        "reply": reply.get("content") or "",
    }


@router.post("/send")
async def send(body: SendBody, session: Session = Depends(get_session)) -> dict[str, Any]:
    conv = session.get(Conversation, body.conversation_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    user = _user(session)
    protocol_mod = PROTOCOLS[conv.kind]

    _persist(session, conv, "user", body.text)

    tool_rounds = 0
    final_text = ""
    while tool_rounds < MAX_TOOL_ROUNDS:
        response = await llm_chat(
            messages=_messages_for_conv(session, conv),
            tools=tools_for(conv.kind),
        )
        choice = response["choices"][0]
        msg = choice["message"]
        tool_calls = msg.get("tool_calls") or []
        _persist(session, conv, "assistant", msg.get("content") or "", tool_calls)

        if not tool_calls:
            final_text = msg.get("content") or ""
            break

        # Execute tools, feed results back
        for call in tool_calls:
            name = call["function"]["name"]
            args = json.loads(call["function"]["arguments"] or "{}")
            try:
                result = protocol_mod.handle_tool(name, args, session, user, conv)
            except Exception as e:  # noqa: BLE001
                result = f"ERROR executing {name}: {e}"
            m = Message(
                conversation_id=conv.id,
                role="tool",
                content=result,
                tool_calls=json.dumps({"tool_call_id": call.get("id"), "name": name}),
                created_at=datetime.utcnow().isoformat(),
            )
            session.add(m)
        session.commit()
        tool_rounds += 1

    return {"reply": final_text, "rounds": tool_rounds}
