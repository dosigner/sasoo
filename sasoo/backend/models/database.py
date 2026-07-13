"""
Sasoo - Database Layer
Async SQLite database management using aiosqlite.

Paths:
  App data (DB, config, agent_profiles):
    - Development: <project>/backend/library/
    - Production:  %APPDATA%/Sasoo/ (Windows)

  Paper library (user-configurable):
    - Development: <project>/backend/library/
    - Production:  %APPDATA%/Sasoo/library/ (default, changeable in Settings)
"""

import os
import re
import sqlite3
import sys
import time
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


def _get_app_data_root() -> Path:
    """
    App-internal data directory (DB, config, agent_profiles).
    Fixed path — users should not modify this directly.

    - Development: backend/library/ (same as library root)
    - Production:  %APPDATA%/Sasoo/ (Windows)
                   ~/Library/Application Support/Sasoo/ (macOS)
                   ~/.local/share/Sasoo/ (Linux)
    """
    if _is_bundled():
        if sys.platform == 'win32':
            base = Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming'))
        elif sys.platform == 'darwin':
            base = Path.home() / 'Library' / 'Application Support'
        else:
            base = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share'))
        return base / 'Sasoo'
    else:
        return Path(__file__).resolve().parent.parent / "library"


def _get_default_library_root() -> Path:
    """
    Default paper library root directory.

    - Development: backend/library/ (relative to source)
    - Production:  %APPDATA%/Sasoo/library/ by default.
    """
    if _is_bundled():
        return _get_app_data_root() / "library"
    return Path(__file__).resolve().parent.parent / "library"


LEGACY_LIBRARY_PATH_KEY = "library_path"


def library_path_setting_key() -> str:
    """
    The settings key holding this machine's library path.

    The library path is per-machine, so it is stored per-platform. A settings
    database that travels between a Mac and a Windows box (synced, copied, or
    restored from backup) must not hand one platform the other's path.
    """
    return f"library_path_{sys.platform}"


_WINDOWS_PATH_MARKER = re.compile(r"[A-Za-z]:[\\/]|\\")


def usable_library_path(raw: object) -> Optional[Path]:
    """
    Interpret a stored library path, or None if it is not usable here.

    Two things make a stored path unusable on this machine.

    It is not absolute here. "C:\\Users\\dongj\\..." is not an absolute path on
    POSIX -- it is a perfectly legal *relative filename* whose backslashes carry
    no meaning -- so Path.resolve() glues it onto the process's working
    directory. The mirror image happens to a POSIX path read on Windows.

    Or it carries the other platform's syntax. Rejecting non-absolute paths is
    not enough, because an older build already did that gluing and persisted
    the result:

        /Users/dongj/dev/.../sasoo/backend/C:\\Users\\dongj\\...\\library

    which *is* absolute on POSIX and would sail through, still pointing at a
    directory that has never existed. A drive letter or a backslash anywhere in
    a POSIX path means the value came from Windows, intact or mangled.
    """
    text = str(raw or "").strip()
    if not text:
        return None

    if sys.platform != "win32" and _WINDOWS_PATH_MARKER.search(text):
        return None

    candidate = Path(text).expanduser()
    return candidate if candidate.is_absolute() else None


def _read_configured_library_root() -> Optional[Path]:
    """Read this platform's configured library path from SQLite, if usable."""
    db_path = _get_app_data_root() / "sasoo.db"
    if not db_path.exists():
        return None

    try:
        conn = sqlite3.connect(str(db_path))
        try:
            cursor = conn.execute(
                "SELECT key, value FROM settings WHERE key IN (?, ?)",
                (library_path_setting_key(), LEGACY_LIBRARY_PATH_KEY),
            )
            rows = {str(k): v for k, v in cursor.fetchall()}
        finally:
            conn.close()
    except Exception:
        return None

    # This platform's own key wins. The legacy single-platform key is only a
    # fallback, and only when it happens to be valid here -- on the machine it
    # was written for, it will be; on any other, it will not.
    for key in (library_path_setting_key(), LEGACY_LIBRARY_PATH_KEY):
        resolved = usable_library_path(rows.get(key))
        if resolved is not None:
            return resolved

    return None


# get_library_root() runs inside async request handlers on nearly every
# endpoint, and an uncached read opens a synchronous SQLite connection on the
# event loop. The setting changes only through api/settings.py, which
# invalidates explicitly; the TTL covers writes we cannot see (another process
# editing the DB). Keyed on (db path, platform key) so a changed app-data root
# or platform never serves a stale entry.
_LIBRARY_ROOT_TTL_SECONDS = 3.0
_library_root_cache: Optional[tuple[tuple[str, str], float, Optional[Path]]] = None


def invalidate_library_root_cache() -> None:
    """Force the next get_library_root() to re-read the settings DB."""
    global _library_root_cache
    _library_root_cache = None


def _cached_configured_library_root() -> Optional[Path]:
    global _library_root_cache
    key = (str(_get_app_data_root() / "sasoo.db"), library_path_setting_key())
    cached = _library_root_cache
    now = time.monotonic()
    if cached is not None and cached[0] == key and now < cached[1]:
        return cached[2]

    configured = _read_configured_library_root()
    _library_root_cache = (key, now + _LIBRARY_ROOT_TTL_SECONDS, configured)
    return configured


def get_library_root() -> Path:
    """
    Determine the active paper library root directory.

    Reads the current setting from SQLite when available so runtime changes
    apply without requiring a backend restart.
    """
    configured = _cached_configured_library_root()
    return configured if configured is not None else _get_default_library_root()


def get_library_search_roots() -> tuple[Path, ...]:
    """
    Return candidate library roots for resolving existing paper folders.

    The default bundled root is kept as a fallback so papers uploaded before a
    path change remain readable.
    """
    current_root = get_library_root()
    default_root = _get_default_library_root()
    roots: list[Path] = []

    for candidate in (current_root, default_root):
        normalized = candidate.expanduser()
        if normalized not in roots:
            roots.append(normalized)

    return tuple(roots)


APP_DATA_ROOT = _get_app_data_root()
LIBRARY_ROOT = get_library_root()
DB_PATH = APP_DATA_ROOT / "sasoo.db"
CONFIG_PATH = APP_DATA_ROOT / "config.json"

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
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    explanation_level TEXT,
    analysis_focus TEXT,
    pdf_file_uri TEXT,
    pdf_file_expires_at TEXT
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
    input_hash TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    interaction_id TEXT
);

CREATE TABLE IF NOT EXISTS figures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER REFERENCES papers(id) ON DELETE CASCADE,
    figure_num TEXT,
    caption TEXT,
    file_path TEXT,
    ai_analysis TEXT,
    quality TEXT,
    detailed_explanation TEXT,
    page_number INTEGER,
    bbox_json TEXT,
    extraction_engine TEXT,
    confidence REAL,
    classifier_label TEXT,
    classifier_model TEXT,
    parent_figure_id INTEGER REFERENCES figures(id) ON DELETE SET NULL,
    is_composite INTEGER,
    resolver_version TEXT,
    extraction_status TEXT
);

CREATE TABLE IF NOT EXISTS tables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER REFERENCES papers(id) ON DELETE CASCADE,
    table_num TEXT,
    caption TEXT,
    page_number INTEGER,
    bbox_json TEXT,
    csv_path TEXT,
    html_path TEXT,
    markdown_text TEXT,
    confidence REAL,
    parse_method TEXT,
    classifier_model TEXT,
    resolver_version TEXT,
    extraction_status TEXT,
    repair_attempted INTEGER DEFAULT 0,
    repair_reason TEXT,
    repair_confidence REAL,
    review_required INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_papers_status ON papers(status);
CREATE INDEX IF NOT EXISTS idx_papers_domain ON papers(domain);
CREATE INDEX IF NOT EXISTS idx_papers_year ON papers(year);
CREATE INDEX IF NOT EXISTS idx_analysis_paper_id ON analysis_results(paper_id);
CREATE INDEX IF NOT EXISTS idx_analysis_phase ON analysis_results(phase);
CREATE INDEX IF NOT EXISTS idx_analysis_created_at ON analysis_results(created_at);
CREATE INDEX IF NOT EXISTS idx_analysis_cost ON analysis_results(cost_usd);
CREATE INDEX IF NOT EXISTS idx_analysis_cache ON analysis_results(paper_id, phase, input_hash);
CREATE INDEX IF NOT EXISTS idx_figures_paper_id ON figures(paper_id);
CREATE INDEX IF NOT EXISTS idx_tables_paper_id ON tables(paper_id);
CREATE INDEX IF NOT EXISTS idx_tables_sort ON tables(paper_id, page_number, table_num);

CREATE TABLE IF NOT EXISTS analysis_cache_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER REFERENCES papers(id) ON DELETE CASCADE,
    phase TEXT NOT NULL,
    input_hash TEXT,
    source_model TEXT,
    estimated_cost_usd REAL DEFAULT 0,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_analysis_cache_events_created_at ON analysis_cache_events(created_at);
CREATE INDEX IF NOT EXISTS idx_analysis_cache_events_phase ON analysis_cache_events(phase);

CREATE TABLE IF NOT EXISTS experiment_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER REFERENCES papers(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    model_used TEXT,
    tokens_in INTEGER,
    tokens_out INTEGER,
    cost_usd REAL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_experiment_plans_paper_id ON experiment_plans(paper_id);
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
    APP_DATA_ROOT.mkdir(parents=True, exist_ok=True)
    get_library_root().mkdir(parents=True, exist_ok=True)

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
        pass  # Column already exists — expected on subsequent startups

    # Figure metadata migrations for ODL-backed extraction
    for ddl in (
        "ALTER TABLE figures ADD COLUMN page_number INTEGER",
        "ALTER TABLE figures ADD COLUMN bbox_json TEXT",
        "ALTER TABLE figures ADD COLUMN extraction_engine TEXT",
        "ALTER TABLE figures ADD COLUMN confidence REAL",
        "ALTER TABLE figures ADD COLUMN classifier_label TEXT",
        "ALTER TABLE figures ADD COLUMN classifier_model TEXT",
        "ALTER TABLE figures ADD COLUMN parent_figure_id INTEGER",
        "ALTER TABLE figures ADD COLUMN is_composite INTEGER",
        "ALTER TABLE figures ADD COLUMN resolver_version TEXT",
        "ALTER TABLE figures ADD COLUMN extraction_status TEXT",
    ):
        try:
            await _db_connection.execute(ddl)
            await _db_connection.commit()
        except Exception:
            pass

    for ddl in (
        """
        CREATE TABLE IF NOT EXISTS tables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id INTEGER REFERENCES papers(id) ON DELETE CASCADE,
            table_num TEXT,
            caption TEXT,
            page_number INTEGER,
            bbox_json TEXT,
            csv_path TEXT,
            html_path TEXT,
            markdown_text TEXT,
            confidence REAL,
            parse_method TEXT,
            classifier_model TEXT,
            resolver_version TEXT,
            extraction_status TEXT,
            repair_attempted INTEGER DEFAULT 0,
            repair_reason TEXT,
            repair_confidence REAL,
            review_required INTEGER DEFAULT 0
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_tables_paper_id ON tables(paper_id)",
        "CREATE INDEX IF NOT EXISTS idx_tables_sort ON tables(paper_id, page_number, table_num)",
    ):
        try:
            await _db_connection.execute(ddl)
            await _db_connection.commit()
        except Exception:
            pass

    for ddl in (
        "ALTER TABLE tables ADD COLUMN repair_attempted INTEGER DEFAULT 0",
        "ALTER TABLE tables ADD COLUMN repair_reason TEXT",
        "ALTER TABLE tables ADD COLUMN repair_confidence REAL",
        "ALTER TABLE tables ADD COLUMN review_required INTEGER DEFAULT 0",
    ):
        try:
            await _db_connection.execute(ddl)
            await _db_connection.commit()
        except Exception:
            pass

    # Migration: Add input_hash column for LLM response caching
    try:
        await _db_connection.execute("ALTER TABLE analysis_results ADD COLUMN input_hash TEXT")
        await _db_connection.commit()
    except Exception:
        pass  # Column already exists

    for ddl in (
        """
        CREATE TABLE IF NOT EXISTS analysis_cache_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id INTEGER REFERENCES papers(id) ON DELETE CASCADE,
            phase TEXT NOT NULL,
            input_hash TEXT,
            source_model TEXT,
            estimated_cost_usd REAL DEFAULT 0,
            tokens_in INTEGER DEFAULT 0,
            tokens_out INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_analysis_cache ON analysis_results(paper_id, phase, input_hash)",
        "CREATE INDEX IF NOT EXISTS idx_analysis_cache_events_created_at ON analysis_cache_events(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_analysis_cache_events_phase ON analysis_cache_events(phase)",
    ):
        try:
            await _db_connection.execute(ddl)
            await _db_connection.commit()
        except Exception:
            pass

    # Migration: Analysis params + Interactions API chain checkpoint columns
    for ddl in (
        "ALTER TABLE papers ADD COLUMN explanation_level TEXT",
        "ALTER TABLE papers ADD COLUMN analysis_focus TEXT",
        "ALTER TABLE papers ADD COLUMN pdf_file_uri TEXT",
        "ALTER TABLE papers ADD COLUMN pdf_file_expires_at TEXT",
        "ALTER TABLE analysis_results ADD COLUMN interaction_id TEXT",
    ):
        try:
            await _db_connection.execute(ddl)
            await _db_connection.commit()
        except Exception:
            pass  # column already exists


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
    for root in get_library_search_roots():
        candidate = root / folder_name
        if candidate.exists():
            return candidate
    return get_library_root() / folder_name


def get_paperbanana_dir(folder_name: str) -> Path:
    """Return the absolute path for PaperBanana output."""
    d = get_paper_dir(folder_name) / "paperbanana"
    d.mkdir(parents=True, exist_ok=True)
    return d
