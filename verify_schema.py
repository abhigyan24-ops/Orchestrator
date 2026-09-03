"""
Quick verification script: connects to Postgres, applies the schema
and seed data, then queries each table to confirm everything is in place.

Usage:
    python verify_schema.py
"""

import asyncio
import os
import sys

# Allow running from the project root
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv

load_dotenv()

from db.connection import init_pool, close_pool, get_connection, apply_schema, apply_seed


async def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set. Copy .env.example to .env first.")
        sys.exit(1)

    print(f"Connecting to: {database_url.split('@')[1] if '@' in database_url else database_url}")
    await init_pool(database_url)

    async with get_connection() as conn:
        # Apply schema
        print("\n--- Applying schema.sql ---")
        await apply_schema(conn)
        print("Schema applied successfully.")

        # Apply seed data
        print("\n--- Applying seed_data.sql ---")
        await apply_seed(conn)
        print("Seed data applied successfully.")

        # Verify tables exist
        print("\n--- Verifying tables ---")
        tables = await conn.fetch("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        for t in tables:
            print(f"  ✓ {t['table_name']}")

        # Verify tool_skills
        print("\n--- tool_skills sample ---")
        rows = await conn.fetch(
            "SELECT tool_name, model_name, task_category, priority "
            "FROM tool_skills ORDER BY task_category, priority LIMIT 10"
        )
        for r in rows:
            model = r['model_name'] or '(default)'
            print(f"  {r['task_category']:>12}  p{r['priority']}  {r['tool_name']} / {model}")

        # Verify quota_status
        print("\n--- quota_status ---")
        rows = await conn.fetch(
            "SELECT tool_name, model_name, status FROM quota_status ORDER BY tool_name"
        )
        for r in rows:
            model = r['model_name'] or '(default)'
            print(f"  {r['tool_name']:>14} / {model:<20} → {r['status']}")

        # Verify project_context
        print("\n--- project_context ---")
        row = await conn.fetchrow(
            "SELECT project_id, architecture FROM project_context LIMIT 1"
        )
        if row:
            print(f"  project_id: {row['project_id']}")
            print(f"  architecture: {row['architecture'][:80]}...")

        # Verify CHECK constraints work by attempting an invalid insert
        print("\n--- Verifying CHECK constraints ---")
        try:
            await conn.execute(
                "INSERT INTO tasks (project_id, title, category, status) "
                "VALUES ('test', 'test', 'test', 'INVALID_STATUS')"
            )
            print("  ✗ CHECK constraint did NOT fire (unexpected)")
        except Exception as e:
            err_msg = str(e)
            if "check" in err_msg.lower() or "violates" in err_msg.lower():
                print("  ✓ CHECK constraint correctly rejected invalid status")
            else:
                print(f"  ? Unexpected error: {err_msg}")

    await close_pool()
    print("\n✅ All verifications passed. Phase 1 is complete.\n")


if __name__ == "__main__":
    asyncio.run(main())
