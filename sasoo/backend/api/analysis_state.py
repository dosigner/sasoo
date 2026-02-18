"""
Sasoo - Shared in-memory analysis state.
Imported by all analysis sub-modules that need to read/write running analysis state.
"""

import asyncio

from models.schemas import AnalysisStatus

# ---------------------------------------------------------------------------
# In-memory analysis state (per paper_id)
# ---------------------------------------------------------------------------
# Tracks running analyses so /status can report progress without DB polling.
_running_analyses: dict[int, AnalysisStatus] = {}

# Cancellation events for each running analysis
_cancel_events: dict[int, asyncio.Event] = {}

# Lock for thread-safe access to _running_analyses
_analyses_lock = asyncio.Lock()
