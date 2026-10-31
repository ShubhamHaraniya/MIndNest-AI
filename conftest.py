"""Windows: psycopg's async mode (used for the agents' saved state) cannot run on the default
Proactor event loop, so every test uses the selector loop. Linux and macOS are unaffected."""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
