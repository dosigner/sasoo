"""
Sasoo - Database Layer
Async SQLite database management using aiosqlite.

DB location:
  - Development: <project>/backend/library/sasoo.db
  - Production:  %APPDATA%/Sasoo/library/sasoo.db (Windows)
                 ~/Library/Application Support/Sasoo/library (macOS)
                 ~/.local/share/Sasoo/library (Linux)
"""

import os
import sys
import aiosqlite
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _is_bundled() -> bool:
    """Check if running as a PyInstaller bundle or in Electron production mode."""
    # PyInstaller bundle check
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return True
    # Electron production mode check (set by python-manager.ts)
    if os.environ.get('SASOO_ENV') == 'production':
        return True
    return False


def _get_library_root() -> Path:
    """
    Determine the library root directory based on environment.

    - Development: backend/library/ (relative to source)
    - Production: User's app data directory
    """
    if _is_bundled():
        # Production: Use platform-specific app data directory
        if sys.platform == 'win32':
            base = Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming'))
        elif sys.platform == 'darwin':
            base = Path.home() / 'Library' / 'Application Support'
        else:
            base = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share'))

        return base / 'Sasoo' / 'library'
    else:
        # Development: Use local library folder
        return Path(__file__).resolve().parent.parent / "library"


LIBRARY_ROOT = _get_library_root()
DB_PATH = LIBRARY_ROOT / "sasoo.db"

# ---------------------------------------------------------------------------
# SQL Schema
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    authors TEXT,
    year INTEGER,
    journal TEXT,
    doi TEXT,
    domain TEXT DEFAULT 'optics',
    agent_used TEXT DEFAULT 'photon',
    folder_name TEXT NOT NULL,
    tags TEXT,
    status TEXT DEFAULT 'pending',
    analyzed_at DATETIME,
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analysis_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER REFERENCES papers(id) ON DELETE CASCADE,
    phase TEXT NOT NULL,
    result TEXT NOT NULL,
    model_used TEXT,
    tokens_in INTEGER,
    tokens_out INTEGER,
    cost_usd REAL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS figures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER REFERENCES papers(id) ON DELETE CASCADE,
    figure_num TEXT,
    caption TEXT,
    file_path TEXT,
    ai_analysis TEXT,
    quality TEXT,
    detailed_explanation TEXT
);

CREATE INDEX IF NOT EXISTS idx_papers_status ON papers(status);
CREATE INDEX IF NOT EXISTS idx_papers_domain ON papers(domain);
CREATE INDEX IF NOT EXISTS idx_papers_year ON papers(year);
CREATE INDEX IF NOT EXISTS idx_analysis_paper_id ON analysis_results(paper_id);
CREATE INDEX IF NOT EXISTS idx_analysis_phase ON analysis_results(phase);
CREATE INDEX IF NOT EXISTS idx_analysis_created_at ON analysis_results(created_at);
CREATE INDEX IF NOT EXISTS idx_analysis_cost ON analysis_results(cost_usd);
CREATE INDEX IF NOT EXISTS idx_figures_paper_id ON figures(paper_id);
"""

# ---------------------------------------------------------------------------
# Settings table (key-value store for app configuration)
# ---------------------------------------------------------------------------

SETTINGS_SQL = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

# ---------------------------------------------------------------------------
# Connection Pool (singleton pattern for async context)
# ---------------------------------------------------------------------------

_db_connection: Optional[aiosqlite.Connection] = None


async def init_db() -> None:
    """
    Initialize the database:
    1. Create library directories if missing.
    2. Open the SQLite connection.
    3. Apply schema migrations (idempotent).
    """
    global _db_connection

    # Ensure directories exist
    LIBRARY_ROOT.mkdir(parents=True, exist_ok=True)

    _db_connection = await aiosqlite.connect(str(DB_PATH))
    _db_connection.row_factory = aiosqlite.Row

    # Enable WAL mode for better concurrent read performance
    await _db_connection.execute("PRAGMA journal_mode=WAL")
    # Enable foreign key enforcement
    await _db_connection.execute("PRAGMA foreign_keys=ON")

    await _db_connection.executescript(SCHEMA_SQL)
    await _db_connection.executescript(SETTINGS_SQL)
    await _db_connection.commit()

    # Migration: Add detailed_explanation column if it doesn't exist
    try:
        await _db_connection.execute("ALTER TABLE figures ADD COLUMN detailed_explanation TEXT")
        await _db_connection.commit()
    except Exception:
        pass  # Column already exists


async def get_db() -> aiosqlite.Connection:
    """
    Return the shared database connection.
    Raises RuntimeError if called before init_db().
    """
    if _db_connection is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _db_connection


async def close_db() -> None:
    """Close the database connection gracefully."""
    global _db_connection
    if _db_connection is not None:
        await _db_connection.close()
        _db_connection = None


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

async def fetch_one(query: str, params: tuple = ()) -> Optional[dict]:
    """Execute a query and return a single row as dict, or None."""
    db = await get_db()
    cursor = await db.execute(query, params)
    row = await cursor.fetchone()
    if row is None:
        return None
    return dict(row)


async def fetch_all(query: str, params: tuple = ()) -> list[dict]:
    """Execute a query and return all rows as list of dicts."""
    db = await get_db()
    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def execute_insert(query: str, params: tuple = ()) -> int:
    """Execute an INSERT and return the lastrowid."""
    db = await get_db()
    cursor = await db.execute(query, params)
    await db.commit()
    return cursor.lastrowid


async def execute_update(query: str, params: tuple = ()) -> int:
    """Execute an UPDATE/DELETE and return the number of rows affected."""
    db = await get_db()
    cursor = await db.execute(query, params)
    await db.commit()
    return cursor.rowcount


def get_paper_dir(folder_name: str) -> Path:
    """Return the absolute path to a paper's folder inside the library."""
    return LIBRARY_ROOT / folder_name


def get_figures_dir(folder_name: str) -> Path:
    """Return the absolute path to a paper's figures directory."""
    d = LIBRARY_ROOT / folder_name / "figures"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_paperbanana_dir(folder_name: str) -> Path:
    """Return the absolute path for PaperBanana output."""
    d = LIBRARY_ROOT / folder_name / "paperbanana"
    d.mkdir(parents=True, exist_ok=True)
    return d
