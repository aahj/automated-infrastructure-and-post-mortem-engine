import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from psycopg_pool import AsyncConnectionPool

# Force psycopg to use SelectorEventLoop on Windows
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def run_database_migrations(migrations_dir: str = "migrations"):

    mig_path = Path(__file__).parent / migrations_dir

    if not mig_path.exists():
        print(f"Migration directory '{mig_path}' not found. Skipping.")
        return

    async with AsyncConnectionPool(
        conninfo=os.getenv("POSTGRES_CONNECTION_URI"),
        open=False,
    ) as pool:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:

                # 1. Find and sort available local migration scripts
                sql_files = sorted([f for f in os.listdir(mig_path) if f.endswith(".sql")])

                # 2. Iterate and apply missing files sequentially
                for sql_file in sql_files:

                    print(f"Applying database migration: {sql_file}")
                    file_content = (mig_path / sql_file).read_text()

                    # Execute individual script inside an explicit sub-transaction block
                    try:
                        async with conn.transaction():
                            # Execute target migration file statements
                            await cur.execute(file_content)

                        print(f"Successfully applied: {sql_file}")
                    except Exception as file_err:
                        print(f"FATAL: Failed to apply migration file {sql_file}: {file_err}")
                        raise file_err


if __name__ == "__main__":
    asyncio.run(run_database_migrations())
