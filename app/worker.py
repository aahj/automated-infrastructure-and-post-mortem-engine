import asyncio
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from dotenv import load_dotenv

load_dotenv()

# added src/ to python path before any imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from constants import (
    CONNECTION_ESTABLISH_COOL_DOWN_PERIOD_SEC,
    MAX_CONCURRENT_JOBS,
    JobStatus,
)
from graph.state import initial_state
from graph.workflow import build_graph
from observability.langfuse_setup import flush_langfuse, get_langfuse_run

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

keep_running = True


def handle_exit(signum, frame):
    global keep_running
    print("[WORKER] " "Received termination signal")
    keep_running = False
    time.sleep(1)
    sys.exit(0)


signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)

semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)  # limit concurrent jobs


async def process_job(job, pool: AsyncConnectionPool, graph):
    async with semaphore:
        job_id = job["id"]
        # The queue row is changed to `processing` when it is claimed. Use the
        # status captured before that update to decide whether this is a new
        # graph invocation or a resume from the human-approval interrupt.
        claimed_from_status = job["claimed_from_status"]
        session_id = job["session_id"]
        raw_alert_payload = job["payload"]
        fallback_incident_timestamp = (
            cast(datetime, job["created_at"]).astimezone(timezone.utc).isoformat()
        )

        print("[WORKER] ", f"CLAIMED INCIDENT FOUND - job: {job_id}, session_id: {session_id}")

        try:
            # initializing state
            state = initial_state(raw_alert_payload, session_id, fallback_incident_timestamp)

            config, trace = get_langfuse_run(session_id)

            with trace:
                # Invoking graph
                match claimed_from_status:
                    case JobStatus.PENDING.value:
                        graph_input = state
                    case JobStatus.AUTO_MITIGATION_APPROVED.value:
                        graph_input = Command(resume="approve")
                    case JobStatus.MANUAL_MITIGATION_REQUIRED.value:
                        graph_input = Command(resume="reject")
                    case _:
                        raise ValueError(f"Unsupported claimed job status: {claimed_from_status}")

                graph_res = await graph.ainvoke(graph_input, config=config)

                if "__interrupt__" in graph_res:
                    print(
                        f"[WORKER] Job: {job_id}, session_id: {session_id} hit interrupt gate. Saving state and releasing worker."
                    )
                    async with pool.connection() as con:
                        await con.execute(
                            "UPDATE incident_ingress_queue SET status = %s WHERE id = %s",
                            (
                                JobStatus.AWAITING_APPROVAL.value,
                                job_id,
                            ),
                        )
                    return

                    # interrupt_payload = graph_res["__interrupt__"][0].value
                    # details = interrupt_payload.get("details", {})
                    # if details:
                    #     print(f"\n{'='*60}")
                    #     print("INCIDENT DETAILS:")
                    #     print(f"{'='*60}")
                    #     print(f"Incident ID: {details.get('incident_id')}")
                    #     print(f"Incident Occurred At: {details.get('incident_occurred_at')}")
                    #     print(f"Severity Level: {details.get('severity_level')}")
                    #     print(f"Service Name: {details.get('service_name')}")
                    #     print(f"Error Summary: {details.get('error_summary')}")
                    #     print(f"Root Cause: {details.get('root_cause')}")
                    #     print(f"Diagnostics: {str(details.get('diagnostics'))}")

                    # print(f"\n{interrupt_payload.get("prompt","Continue?")}")
                    # user_input = input("> ").strip()
                    # # Resume the graph with the user's decision.
                    # # Command(resume=value) is how you pass input back to the interrupted node.
                    # graph_res = await graph.ainvoke(Command(resume=user_input), config=config)

            async with pool.connection() as con:
                await con.execute(
                    """
                    UPDATE incident_ingress_queue SET status= %s WHERE id = %s
                    """,
                    (
                        JobStatus.COMPLETED.value,
                        job_id,
                    ),
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
                    UPDATE incident_ingress_queue SET status= %s, retry_count = retry_count + 1
                    WHERE id = %s
                    """,
                    (JobStatus.FAILED.value, job_id),
                )


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
                if not semaphore.locked():
                    job = None
                    async with pool.connection() as con:
                        async with con.cursor() as cur:
                            await cur.execute(
                                """
                                WITH next_job AS (
                                    SELECT id, status AS claimed_from_status
                                    FROM incident_ingress_queue
                                    WHERE status IN (%s, %s, %s)
                                    ORDER BY 
                                        CASE status
                                            WHEN %s THEN 1
                                            WHEN %s THEN 2
                                            WHEN %s THEN 3
                                        END,
                                    created_at ASC
                                    LIMIT 1
                                    FOR UPDATE SKIP LOCKED
                                )
                                UPDATE incident_ingress_queue AS queue
                                SET status = %s, locked_at = NOW()
                                FROM next_job
                                WHERE queue.id = next_job.id
                                RETURNING
                                    queue.id,
                                    queue.status,
                                    next_job.claimed_from_status,
                                    queue.session_id,
                                    queue.payload,
                                    queue.created_at
                                """,
                                (
                                    JobStatus.PENDING.value,
                                    JobStatus.AUTO_MITIGATION_APPROVED.value,
                                    JobStatus.MANUAL_MITIGATION_REQUIRED.value,
                                    # priority order
                                    JobStatus.PENDING.value,
                                    JobStatus.AUTO_MITIGATION_APPROVED.value,
                                    JobStatus.MANUAL_MITIGATION_REQUIRED.value,
                                    JobStatus.PROCESSING.value,
                                ),
                            )
                            job = await cur.fetchone()

                    if job:
                        # spawn a background task to process the job
                        asyncio.create_task(process_job(job, pool, graph))
                    else:
                        # No jobs or lock acquired
                        await asyncio.sleep(1)

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
