import os
import glob
import logging
from sqlalchemy import text
from src.core.database import engine

logger = logging.getLogger("pbx.migrator")


async def run_migrations():
    """
    Automatically tracks and applies pending SQL migrations in alphabetical order.
    Safe to run on every startup (idempotent via schema_migrations table).
    Ensures seamless database setup on new PCs or production deployments.
    """
    candidates = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "migrations"),
        "/app/migrations",
        os.path.abspath("migrations")
    ]

    migrations_dir = None
    for c in candidates:
        if os.path.exists(c) and os.path.isdir(c):
            migrations_dir = c
            break

    if not migrations_dir:
        logger.warning(f"Migrations directory not found in candidates: {candidates}")
        return

    sql_files = sorted(glob.glob(os.path.join(migrations_dir, "*.sql")))
    if not sql_files:
        logger.info(f"No SQL migration files found in {migrations_dir}")
        return

    logger.info(f"Checking database migrations in {migrations_dir} ({len(sql_files)} files found)...")

    async with engine.connect() as conn:
        # Create schema_migrations tracking table if not exists
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(255) PRIMARY KEY,
                applied_at TIMESTAMPTZ DEFAULT NOW()
            );
        """))
        await conn.commit()

        # Fetch already applied migrations
        result = await conn.execute(text("SELECT version FROM schema_migrations;"))
        applied = {row[0] for row in result.fetchall()}

        # If base tables already exist (e.g. from postgres container entrypoint),
        # mark 001_initial_schema.sql as applied
        table_check = await conn.execute(text("SELECT to_regclass('public.users');"))
        has_base_schema = table_check.scalar() is not None

        if has_base_schema and "001_initial_schema.sql" not in applied:
            await conn.execute(
                text("INSERT INTO schema_migrations (version) VALUES ('001_initial_schema.sql') ON CONFLICT DO NOTHING;")
            )
            await conn.commit()
            applied.add("001_initial_schema.sql")

        raw_conn = (await conn.get_raw_connection()).driver_connection

        for filepath in sql_files:
            filename = os.path.basename(filepath)
            if filename in applied:
                continue

            logger.info(f"Applying migration: {filename}...")
            with open(filepath, "r", encoding="utf-8") as f:
                sql_content = f.read()

            try:
                # Use raw asyncpg execute for multi-statement DDL execution
                await raw_conn.execute(sql_content)
                await conn.execute(
                    text("INSERT INTO schema_migrations (version) VALUES (:v) ON CONFLICT (version) DO NOTHING;"),
                    {"v": filename}
                )
                await conn.commit()
                logger.info(f"Successfully applied migration: {filename}")
            except Exception as e:
                logger.error(f"Error applying migration {filename}: {e}")
                raise e
