"""Windows: psycopg's async mode cannot run on the default (Proactor) event loop, and the saved
agent state uses psycopg. Use the selector loop for these tests. Linux and macOS are unaffected."""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
