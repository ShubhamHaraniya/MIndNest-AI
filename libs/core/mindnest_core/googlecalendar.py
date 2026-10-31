"""A small client for the Google Calendar API (only what MindNest uses).

MindNest asks for the narrow `calendar.app.created` permission: it can make its own calendar
and manage events on that calendar, and cannot see or change anything else in the student's
Google Calendar.
"""

from typing import Any

import httpx

API = "https://www.googleapis.com/calendar/v3"
SCOPE = "https://www.googleapis.com/auth/calendar.app.created"


class CalendarApiError(Exception):
    def __init__(self, status: int, reason: str = "") -> None:
        super().__init__(f"Google Calendar answered {status} {reason}".strip())
        self.status = status
        self.reason = reason

    @property
    def missing(self) -> bool:
        return self.status in (404, 410)

    @property
    def duplicate(self) -> bool:
        """An event with the id we chose already exists (a repeated request)."""
        return self.status == 409

    @property
    def rate_limited(self) -> bool:
        return self.status == 429 or self.reason in ("rateLimitExceeded", "userRateLimitExceeded")

    @property
    def unauthorized(self) -> bool:
        return self.status == 401


class CalendarApi:
    """Tests replace this class with a fake that records calls."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None, timeout: float = 15.0) -> None:
        self._http = httpx.AsyncClient(timeout=timeout, transport=transport)

    async def _call(
        self, method: str, url: str, token: str, body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = await self._http.request(
                method, url, json=body, params=params, headers={"authorization": f"Bearer {token}"}
            )
        except httpx.HTTPError as exc:
            raise CalendarApiError(0, "network") from exc
        if response.status_code >= 400:
            reason = ""
            try:
                errors = response.json().get("error", {}).get("errors", [])
                reason = str(errors[0].get("reason", "")) if errors else ""
            except (ValueError, AttributeError, IndexError):
                pass
            raise CalendarApiError(response.status_code, reason)
        if response.status_code == 204 or not response.content:
            return {}
        try:
            data = response.json()
        except ValueError as exc:
            raise CalendarApiError(502, "unreadable") from exc
        return data if isinstance(data, dict) else {}

    async def create_calendar(self, token: str, name: str) -> str:
        data = await self._call("POST", f"{API}/calendars", token, {"summary": name})
        calendar_id = data.get("id")
        if not isinstance(calendar_id, str) or not calendar_id:
            raise CalendarApiError(502, "no calendar id")
        return calendar_id

    async def create_event(self, token: str, calendar_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Add an event and return Google's answer (it holds `id` and `htmlLink`). If `body` has an
        `id` of our own choosing and that id exists already, Google answers 409."""
        data = await self._call("POST", f"{API}/calendars/{_q(calendar_id)}/events", token, body)
        if not isinstance(data.get("id"), str) or not data["id"]:
            raise CalendarApiError(502, "no event id")
        return data

    async def insert_event(self, token: str, calendar_id: str, body: dict[str, Any]) -> str:
        return str((await self.create_event(token, calendar_id, body))["id"])

    async def get_event(self, token: str, calendar_id: str, event_id: str) -> dict[str, Any]:
        return await self._call("GET", f"{API}/calendars/{_q(calendar_id)}/events/{_q(event_id)}", token)

    async def list_events(
        self, token: str, calendar_id: str, time_min: str, time_max: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Events that overlap [time_min, time_max) (RFC 3339 with an offset), in start order."""
        data = await self._call(
            "GET", f"{API}/calendars/{_q(calendar_id)}/events", token,
            params={
                "timeMin": time_min, "timeMax": time_max, "singleEvents": "true",
                "orderBy": "startTime", "maxResults": max(1, min(limit, 250)),
            },
        )
        items = data.get("items")
        return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []

    async def patch_event(
        self, token: str, calendar_id: str, event_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._call(
            "PATCH", f"{API}/calendars/{_q(calendar_id)}/events/{_q(event_id)}", token, body
        )

    async def delete_event(self, token: str, calendar_id: str, event_id: str) -> None:
        await self._call("DELETE", f"{API}/calendars/{_q(calendar_id)}/events/{_q(event_id)}", token)

    async def delete_calendar(self, token: str, calendar_id: str) -> None:
        await self._call("DELETE", f"{API}/calendars/{_q(calendar_id)}", token)

    async def aclose(self) -> None:
        await self._http.aclose()


def _q(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")
