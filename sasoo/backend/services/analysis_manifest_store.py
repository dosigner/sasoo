"""Experimental transaction primitive; not yet connected to analysis execution.

The caller must supply a dedicated connection with no transaction in progress.
The snapshot stores the exact UTF-8 bytes of the result string.
"""

import hashlib
import uuid

import aiosqlite

DDL = """
CREATE TABLE IF NOT EXISTS manifest_executions (
    execution_id TEXT PRIMARY KEY, paper_id INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS manifest_attempts (
    attempt_id TEXT PRIMARY KEY, execution_id TEXT NOT NULL, generation INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS manifest_versions (
    version_id TEXT PRIMARY KEY, paper_id INTEGER NOT NULL, phase TEXT NOT NULL,
    result_id INTEGER NOT NULL, content_sha256 TEXT NOT NULL, result_bytes BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS manifest_events (
    event_id TEXT PRIMARY KEY, execution_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
    version_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS manifest_inputs (
    event_id TEXT NOT NULL, position INTEGER NOT NULL, role TEXT NOT NULL,
    version_id TEXT NOT NULL, PRIMARY KEY (event_id, position)
);
""" + "\n".join(
    f"CREATE TRIGGER IF NOT EXISTS {table}_no_{operation.lower()} "
    f"BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, 'append only'); END;"
    for table in ("manifest_versions", "manifest_events", "manifest_inputs")
    for operation in ("UPDATE", "DELETE")
)


class FenceLost(RuntimeError):
    """The attempt no longer owns the paper's running worker generation."""


async def save_result_version(
    db: aiosqlite.Connection, execution_id: str, attempt_id: str,
    paper_id: int, generation: int, result_id: int, phase: str,
    result: str, inputs: list[tuple[str, str]],
) -> str:
    """Save one result and its exact inputs atomically, returning the event ID."""
    if db.in_transaction:
        raise ValueError("a dedicated connection without an active transaction is required")
    data = result.encode("utf-8")
    version_id = str(uuid.uuid4())
    event_id = version_id
    try:
        await db.execute("BEGIN IMMEDIATE")
        cursor = await db.execute(
            "SELECT 1 FROM analysis_runs r JOIN manifest_executions e ON e.paper_id=r.paper_id "
            "JOIN manifest_attempts a ON a.execution_id=e.execution_id "
            "WHERE r.paper_id=? AND r.generation=? AND r.status='running' "
            "AND e.execution_id=? AND a.attempt_id=? AND a.generation=?",
            (paper_id, generation, execution_id, attempt_id, generation),
        )
        if await cursor.fetchone() is None:
            raise FenceLost("worker generation or attempt is no longer current")
        for role, input_version in inputs:
            if not role:
                raise ValueError("input role is required")
            cursor = await db.execute(
                "SELECT 1 FROM manifest_versions WHERE version_id=? AND paper_id=?",
                (input_version, paper_id),
            )
            if await cursor.fetchone() is None:
                raise ValueError("input version is missing or belongs to another paper")
        cursor = await db.execute(
            "UPDATE analysis_results SET result=? WHERE id=? AND paper_id=? AND phase=?",
            (result, result_id, paper_id, phase),
        )
        if cursor.rowcount != 1:
            raise ValueError("result does not match paper and phase")
        await db.execute(
            "INSERT INTO manifest_versions VALUES (?, ?, ?, ?, ?, ?)",
            (version_id, paper_id, phase, result_id, hashlib.sha256(data).hexdigest(), data),
        )
        await db.execute("INSERT INTO manifest_events VALUES (?, ?, ?, ?)",
                         (event_id, execution_id, attempt_id, version_id))
        for position, (role, input_version) in enumerate(inputs):
            await db.execute("INSERT INTO manifest_inputs VALUES (?, ?, ?, ?)",
                             (event_id, position, role, input_version))
        await db.commit()
    except BaseException:
        await db.rollback()
        raise
    return event_id
