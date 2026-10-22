from pathlib import Path

from runta_agent_eval.core.db import Database


async def test_database_initializes(tmp_path: Path):
    db = Database(tmp_path / "test.sqlite3")
    await db.init()
    rows = await db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
    names = {row["name"] for row in rows}
    assert "runs" in names
    assert "candidates" in names
