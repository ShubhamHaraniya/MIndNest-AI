"""Run the calendar MCP server:  python -m mindnest_calendar_mcp"""

import asyncio
import logging

import uvicorn
from mindnest_core.db import make_engine, make_session_factory
from mindnest_core.googlecalendar import CalendarApi
from mindnest_core.googleoauth import GoogleClient
from mindnest_core.settings import get_settings

from mindnest_calendar_mcp.server import CalendarService, create_app

PORT = 8765


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    engine = make_engine(settings.database_url)
    google = GoogleClient(settings.google_client_id, settings.google_client_secret)
    calendar = CalendarApi()
    service = CalendarService(settings, make_session_factory(engine), google, calendar)
    server = uvicorn.Server(uvicorn.Config(create_app(service), host="0.0.0.0", port=PORT, log_level="info"))  # noqa: S104
    try:
        await server.serve()
    finally:
        await google.aclose()
        await calendar.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
