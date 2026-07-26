import asyncio
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from dotenv import load_dotenv

load_dotenv()

# added src/ to python path before any imports
sys.path.insert(0, str(Path(__file__).parent / "src"))


from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from graph.state import initial_state
from graph.workflow import build_graph
from observability.langfuse_setup import flush_langfuse, get_langfuse_run

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

keep_running = True
CONNECTION_ESTABLISH_COOL_DOWN_PERIOD_SEC = 5


def handle_exit(signum, frame):
    global keep_running
    print("[WORKER] " "Received termination signal")
    keep_running = False


signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)


async def run_worker():
    global keep_running
    print("[WORKER] " "Initializing Worker..")

    async with AsyncConnectionPool(
        conninfo=os.getenv("POSTGRES_CONNECTION_URI"),
        kwargs={
            "autocommit": True,
            "row_factory": dict_row,
        },
        max_size=10,
        open=False,  # open=False prevents it from connecting until we explicitly call .open()
    ) as pool:
        await pool.open()

        checkpointer = AsyncPostgresSaver(pool)
        # Initialize checkpoint tables if they don't exist
        await checkpointer.setup()

        #  Compile the graph workflow once, it lives for the entire process lifetime
        graph = await build_graph(checkpointer)

        print("[WORKER] " "LangGraph compiled!")
        while keep_running:
            try:
                job = None
                async with pool.connection() as con:
                    async with con.cursor() as cur:
                        await cur.execute("""
                            UPDATE incident_ingress_queue SET status= 'processing', locked_at = NOW()
                            WHERE id = (
                                SELECT id FROM incident_ingress_queue WHERE status = 'pending'
                                ORDER BY created_at ASC
                                LIMIT 1
                                FOR UPDATE SKIP LOCKED
                            )
                            RETURNING id, session_id, payload, created_at
                            """)
                        job = await cur.fetchone()

                if not job:
                    await asyncio.sleep(1)
                    continue

                job_id = job["id"]
                session_id = job["session_id"]
                raw_alert_payload = job["payload"]
                fallback_incident_timestamp = (
                    cast(datetime, job["created_at"]).astimezone(timezone.utc).isoformat()
                )

                print(
                    "[WORKER] ", f"CLAIMED INCIDENT FOUND - job: {job_id}, session_id: {session_id}"
                )

                try:
                    # initializing state
                    state = initial_state(
                        raw_alert_payload, session_id, fallback_incident_timestamp
                    )

                    config, trace = get_langfuse_run(session_id)

                    with trace:
                        # Invoking graph
                        await graph.ainvoke(state, config=config)

                    async with pool.connection() as con:
                        await con.execute(
                            """
                            UPDATE incident_ingress_queue SET status= 'completed' WHERE id = %s
                            """,
                            (job_id,),
                        )
                    print(
                        "[WORKER] "
                        f"LangGraph graph workflow execution completed for job: {job_id}, session_id: {session_id}"
                    )

                except Exception as e:
                    print(
                        "[WORKER] "
                        f"LangGraph graph workflow execution encountered an error for job: {job_id}, session_id: {session_id}: {str(e)}"
                    )
                    # update the job status to 'failed'
                    async with pool.connection() as con:
                        await con.execute(
                            """
                            UPDATE incident_ingress_queue SET status= 'failed', retry_count = retry_count + 1
                            WHERE id = %s
                            """,
                            (job_id,),
                        )

            except Exception as e:
                print("[WORKER] " f"Queue polling worker encountered an error: {str(e)}")
                print("[WORKER] " f"Wait for {CONNECTION_ESTABLISH_COOL_DOWN_PERIOD_SEC}sec")
                await asyncio.sleep(
                    CONNECTION_ESTABLISH_COOL_DOWN_PERIOD_SEC
                )  # cool down before retrying connection establish
            finally:
                flush_langfuse()

    print("[WORKER] " "Worker stopped gracefully")


if __name__ == "__main__":
    asyncio.run(run_worker())
