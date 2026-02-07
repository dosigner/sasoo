"""
Sasoo - AI Co-Scientist Backend
FastAPI entry point.

Runs on http://localhost:8000 by default.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from models.database import (
    FIGURES_DIR,
    LIBRARY_ROOT,
    PAPERBANANA_DIR,
    PAPERS_DIR,
    close_db,
    init_db,
)

# Load .env from project root (if present)
_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: initialize resources on startup, clean up on shutdown."""
    # --- Startup ---
    await init_db()
    print(f"[Sasoo] Database initialized at {LIBRARY_ROOT / 'sasoo.db'}")
    print(f"[Sasoo] Library root: {LIBRARY_ROOT}")

    yield

    # --- Shutdown ---
    await close_db()
    print("[Sasoo] Database connection closed.")


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Sasoo - AI Co-Scientist",
    description=(
        "Backend API for Sasoo, an AI Co-Scientist desktop application "
        "that analyzes research papers using a 4-phase engineering analysis strategy "
        "(Screening -> Visual Verification -> Recipe Extraction -> Deep Dive) "
        "powered by Gemini 3.0 + Claude Sonnet 4.5 dual LLM."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS Middleware
# ---------------------------------------------------------------------------

ALLOWED_ORIGINS = [
    "http://localhost:3000",    # Vite dev server
    "http://localhost:5173",    # Vite default
    "http://localhost:8080",    # Alternative dev port
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8080",
    "app://.",                  # Electron origin
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Static file mounts (figures, PaperBanana images, uploaded PDFs)
# ---------------------------------------------------------------------------

# Ensure directories exist before mounting
for d in (FIGURES_DIR, PAPERBANANA_DIR, PAPERS_DIR):
    d.mkdir(parents=True, exist_ok=True)

app.mount(
    "/static/figures",
    StaticFiles(directory=str(FIGURES_DIR)),
    name="figures",
)
app.mount(
    "/static/paperbanana",
    StaticFiles(directory=str(PAPERBANANA_DIR)),
    name="paperbanana",
)
app.mount(
    "/static/papers",
    StaticFiles(directory=str(PAPERS_DIR)),
    name="papers",
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

from api.papers import router as papers_router      # noqa: E402
from api.analysis import router as analysis_router  # noqa: E402
from api.settings import router as settings_router  # noqa: E402

app.include_router(papers_router)
app.include_router(analysis_router)
app.include_router(settings_router)


# ---------------------------------------------------------------------------
# Root health-check
# ---------------------------------------------------------------------------

@app.get("/", tags=["health"])
async def root():
    return {
        "service": "sasoo",
        "status": "running",
        "version": "0.1.0",
        "library_path": str(LIBRARY_ROOT),
    }


@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Run directly with: python main.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=[str(Path(__file__).resolve().parent)],
    )
