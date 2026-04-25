"""LLM client pointed at the Vertica router. OpenAI-compatible.

Every protocol calls `chat()` with messages + tool defs. The router decides
local vs cloud. If we need to swap Claude for a local model later, only this
file cares (and only the model string in config changes).
"""
from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI

from app.config import settings

_client: AsyncOpenAI | None = None


def client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            base_url=f"{settings.vertica_router_url.rstrip('/')}/v1",
            api_key=settings.vertica_router_api_key,
        )
    return _client


async def chat(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 2048,
) -> dict[str, Any]:
    """Single-turn completion. Returns the raw OpenAI response dict.

    Callers (protocols) handle tool-call loops themselves so that each
    protocol can decide how many rounds to permit and what to do when a
    tool response comes back.
    """
    response = await client().chat.completions.create(
        model=model or settings.default_model,
        messages=messages,  # type: ignore[arg-type]
        tools=tools,  # type: ignore[arg-type]
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.model_dump()


async def stream_chat(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    model: str | None = None,
    temperature: float = 0.7,
):
    """Server-sent events stream of chat completion deltas. Used by the mobile
    chat UI for typing indicators.
    """
    stream = await client().chat.completions.create(
        model=model or settings.default_model,
        messages=messages,  # type: ignore[arg-type]
        tools=tools,  # type: ignore[arg-type]
        temperature=temperature,
        stream=True,
    )
    async for chunk in stream:
        yield chunk.model_dump()
