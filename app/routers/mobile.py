"""Mobile PWA endpoints. Stubbed — the dashboard router is the full reference
implementation; mobile follows the same pattern with a different template.

TODO for v1 → v1.1:
  - GET  /m/             landing (today view)
  - GET  /m/chat         chat with protocol query-param
  - GET  /m/today        today view (task list, streak)
  - GET  /m/loops        open loops management
  - POST /m/win          quick-log win endpoint (for the big + button)
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.db import get_session
from app.models import User

router = APIRouter(prefix="/m")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def mobile_index(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    user = session.exec(select(User)).first()
    return templates.TemplateResponse(
        "mobile/index.html",
        {"request": request, "user": user},
    )


@router.get("/chat", response_class=HTMLResponse)
async def mobile_chat(
    request: Request,
    protocol: str = "adhoc",
    session: Session = Depends(get_session),
) -> HTMLResponse:
    user = session.exec(select(User)).first()
    return templates.TemplateResponse(
        "mobile/chat.html",
        {"request": request, "user": user, "protocol": protocol},
    )
