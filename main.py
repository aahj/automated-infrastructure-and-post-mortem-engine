import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from graph.workflow import build_graph
from observability.langfuse_setup import get_langfuse_run

# added src/ to python path before any imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request, status, HTTPException
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

graph = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = AsyncConnectionPool(
        conninfo=os.getenv("POSTGRES_CONNECTION_URI"),
        max_size=10,
        open=False,
        kwargs={
            "autocommit": True,
            "row_factory": dict_row,
        },
    )
    await pool.open()
    app.state.db_pool = pool

    global graph
    checkpointer = AsyncPostgresSaver(pool)
    # Initialize checkpoint tables if they don't exist
    await checkpointer.setup()

    graph = await build_graph(checkpointer)
    print("[FASTAPI] Graph compiled and ready.")

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


@app.get("/incident/awaiting-approval")
async def get_all_awaiting_approval_jobs(request: Request):
    db_pool = cast(AsyncConnectionPool, request.app.state.db_pool)
    async with db_pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM incident_ingress_queue WHERE status = %s", ("awaiting_approval",)
            )
            jobs = await cur.fetchall()

    return {"success": True, "data": {"jobs": jobs}}


@app.get("/incident/{incident_id}/review")
async def get_incident_for_review(incident_id: str):
    global graph
    config, trace = get_langfuse_run(session_id=incident_id)
    # Read state directly from Postgres checkpointer
    state = await graph.aget_state(config)
    if not state.tasks or not state.tasks[0].interrupts:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No human pending approval found for this incident.",
        )

    # extract the payload passed to the interrupt
    interrupt_payload = state.tasks[0].interrupts[0].value
