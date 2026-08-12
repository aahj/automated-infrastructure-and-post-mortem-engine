import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast
from uuid import UUID

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import BaseModel

from constants import JobStatus
from graph.workflow import build_graph
from observability.langfuse_setup import get_langfuse_run

# added src/ to python path before any imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Request, status
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

graph = None


class ApproveIncidentRequest(BaseModel):
    incident_id: UUID
    approve: bool


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
                VALUES (%s, %s, %s)
                """,
                (session_id, Jsonb(raw_alert_payload), JobStatus.PENDING.value),
            )

    return {"success": True, "session_id": session_id}


@app.get("/incident/awaiting-approval")
async def get_all_awaiting_approval_jobs(request: Request):
    db_pool = cast(AsyncConnectionPool, request.app.state.db_pool)
    async with db_pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM incident_ingress_queue WHERE status = %s",
                (JobStatus.AWAITING_APPROVAL.value,),
            )
            jobs = await cur.fetchall()

    return {"success": True, "data": {"jobs": jobs}}


@app.get("/incident/{incident_id}/review")
async def get_incident_for_review(incident_id: str):
    global graph
    config, _ = get_langfuse_run(session_id=incident_id)
    # Read state directly from Postgres checkpointer
    state = await graph.aget_state(config)
    if not state.tasks or not state.tasks[0].interrupts:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No human pending approval found for this incident.",
        )

    # extract the payload passed to the interrupt
    interrupt_payload = state.tasks[0].interrupts[0].value
    return {"success": True, "data": {"status": "awaiting_approval", "payload": interrupt_payload}}


@app.post("/incident/approve")
async def approve_incident(body: ApproveIncidentRequest):
    db_pool = cast(AsyncConnectionPool, app.state.db_pool)
    async with db_pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM incident_ingress_queue WHERE incident_id = %s AND status = %s",
                (
                    body.incident_id,
                    JobStatus.AWAITING_APPROVAL.value,
                ),
            )
            incident = await cur.fetchone()
            if not incident:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found"
                )

            await cur.execute(
                "UPDATE incident_ingress_queue SET status = %s WHERE incident_id = %s",
                (
                    (
                        JobStatus.AUTO_MITIGATION_APPROVED.value
                        if body.approve
                        else JobStatus.MANUAL_MITIGATION_REQUIRED.value
                    ),
                    body.incident_id,
                ),
            )
            affected_rows = await cur.rowcount

    if affected_rows == 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update incident status",
        )

    return {"success": True}
