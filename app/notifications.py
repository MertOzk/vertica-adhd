"""Home Assistant Companion push notifications.

We call HA's /api/services/notify/<target> REST endpoint. HA takes care of the
platform-specific plumbing (APNs for iOS, FCM for Android) via the Companion
app on the phone.

Actionable buttons arrive back at /webhook/ha via a small HA automation that
listens for `mobile_app_notification_action` events.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.config import settings


@dataclass
class Action:
    action: str        # identifier we'll see in the webhook
    title: str         # button text the user sees


async def notify(
    title: str,
    message: str,
    *,
    url: str | None = None,
    actions: list[Action] | None = None,
    time_sensitive: bool = False,
    critical: bool = False,
) -> None:
    """Send a push via Home Assistant to the configured phone.

    Silently no-ops if HA isn't configured (so dev machines without HA still work).
    """
    if not settings.ha_token or not settings.ha_notify_target:
        return

    data: dict[str, object] = {}
    if url:
        data["url"] = url
    if time_sensitive:
        data.setdefault("push", {})
        data["push"] = {**data["push"], "interruption-level": "time-sensitive"}  # type: ignore[dict-item]
    if critical:
        data.setdefault("push", {})
        data["push"] = {**data["push"], "interruption-level": "critical", "sound": {  # type: ignore[dict-item]
            "name": "default",
            "critical": 1,
            "volume": 0.9,
        }}
    if actions:
        data["actions"] = [{"action": a.action, "title": a.title} for a in actions]

    payload: dict[str, object] = {"title": title, "message": message}
    if data:
        payload["data"] = data

    endpoint = f"{settings.ha_url.rstrip('/')}/api/services/notify/{settings.ha_notify_target}"
    headers = {
        "Authorization": f"Bearer {settings.ha_token}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=10.0) as http:
        await http.post(endpoint, json=payload, headers=headers)
