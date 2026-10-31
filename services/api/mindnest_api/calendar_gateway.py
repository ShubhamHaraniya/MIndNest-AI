"""The API's way to Google Calendar: ask the calendar MCP server.

The API holds no Google Calendar code of its own. Each call opens a short Model Context Protocol
session to the calendar server and sends a token made for exactly that call: this student, this
tool, these arguments, valid about a minute (see mindnest_core.mcptoken). The Calendar page and
the chat's calendar agent both use this class.
"""

import asyncio
import json
import logging
from typing import Any
from uuid import UUID

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mindnest_core.calevent import EventIn, Op
from mindnest_core.mcptoken import mint
from mindnest_core.settings import Settings

log = logging.getLogger("mindnest.calendar")


class CalendarToolError(Exception):
    """The calendar server could not do it. `code` is a stable word such as `gcal_reconnect`,
    `gcal_not_connected`, `not_found`, `rate_limited`, `google_403` or `calendar_unavailable`."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CalendarGateway:
    def __init__(self, settings: Settings, url: str | None = None) -> None:
        self.settings = settings
        self.url = url or settings.calendar_mcp_url

    async def call(self, user_id: UUID | str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        token = mint(
            self.settings.secret_key, str(user_id), tool, args, ttl=self.settings.calendar_mcp_token_ttl_seconds
        )
        timeout = self.settings.calendar_mcp_timeout_seconds
        try:
            async with asyncio.timeout(timeout):
                async with httpx.AsyncClient(
                    headers={"Authorization": f"Bearer {token}"}, timeout=timeout
                ) as http:
                    async with streamable_http_client(self.url, http_client=http) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            result = await session.call_tool(tool, args)
        except Exception as exc:  # the server is down, refused the token, or took too long
            log.warning("calendar server call %s failed: %s", tool, type(exc).__name__)
            raise CalendarToolError("calendar_unavailable") from exc
        if result.isError:
            log.warning("calendar server call %s answered with an error", tool)
            raise CalendarToolError("calendar_error")
        data = _payload(result)
        if not data.get("ok"):
            raise CalendarToolError(str(data.get("error") or "calendar_error"))
        return data

    # --- typed helpers ------------------------------------------------------------------------
    async def status(self, user_id: UUID | str) -> dict[str, Any]:
        return await self.call(user_id, "calendar_status", {})

    async def ensure_calendar(self, user_id: UUID | str) -> dict[str, Any]:
        return await self.call(user_id, "ensure_calendar", {})

    async def list_events(
        self, user_id: UUID | str, start: str, end: str, timezone: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        data = await self.call(
            user_id, "list_events", {"start": start, "end": end, "timezone": timezone, "limit": limit}
        )
        return list(data.get("events", []))

    async def get_event(self, user_id: UUID | str, event_id: str) -> dict[str, Any]:
        return dict((await self.call(user_id, "get_event", {"event_id": event_id}))["event"])

    async def create_event(self, user_id: UUID | str, request_key: str, event: EventIn) -> dict[str, Any]:
        data = await self.call(
            user_id, "create_event", {"request_key": request_key, "event": event.model_dump(mode="json")}
        )
        return dict(data["event"])

    async def update_event(self, user_id: UUID | str, event_id: str, event: EventIn) -> dict[str, Any]:
        data = await self.call(
            user_id, "update_event", {"event_id": event_id, "event": event.model_dump(mode="json")}
        )
        return dict(data["event"])

    async def delete_event(self, user_id: UUID | str, event_id: str) -> None:
        await self.call(user_id, "delete_event", {"event_id": event_id})

    async def apply_changes(self, user_id: UUID | str, ops: list[Op]) -> list[dict[str, Any]]:
        data = await self.call(user_id, "apply_changes", {"ops": [op.model_dump(mode="json") for op in ops]})
        return list(data["results"])

    async def remove_calendar(self, user_id: UUID | str) -> None:
        await self.call(user_id, "remove_calendar", {})


def _payload(result: Any) -> dict[str, Any]:
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        inner = structured.get("result")
        return inner if isinstance(inner, dict) and "ok" in inner and "ok" not in structured else structured
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            try:
                data = json.loads(text)
            except ValueError:
                continue
            if isinstance(data, dict):
                return data
    return {"ok": False, "error": "calendar_error"}
