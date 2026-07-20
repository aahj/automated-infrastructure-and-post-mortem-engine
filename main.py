import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast

# added src/ to python path before any imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request, status
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db_pool = AsyncConnectionPool(
        conninfo=os.getenv("POSTGRES_CONNECTION_URI"),
        max_size=10,
        open=False,
        kwargs={
            "autocommit": True,
            "row_factory": dict_row,
        },
    )
    await app.state.db_pool.open()
    yield
    await app.state.db_pool.close()


app = FastAPI(lifespan=lifespan)


@app.post("/webhook/alerts", status_code=status.HTTP_202_ACCEPTED)
async def receive_alerts(request: Request):
    raw_alert_payload = await request.json()
    session_id = str(uuid.uuid4())

    print("[WEBHOOK ALERTS RECEIVED] " f"Session ID: {session_id}")

    db_pool = cast(AsyncConnectionPool, request.app.state.db_pool)
    async with db_pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO incident_ingress_queue (session_id, payload, status)
                VALUES (%s, %s, 'pending')
                """,
                (
                    session_id,
                    Jsonb(raw_alert_payload),
                ),
            )

    return {"success": True, "session_id": session_id}
