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
    LIBRARY_ROOT,
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
    "null",                     # file:// protocol (Electron production)
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Static file mount (unified library directory)
# ---------------------------------------------------------------------------

LIBRARY_ROOT.mkdir(parents=True, exist_ok=True)

app.mount(
    "/static/library",
    StaticFiles(directory=str(LIBRARY_ROOT)),
    name="library",
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
# Run directly with: python main.py [--host HOST] [--port PORT]
# Production usage: sasoo-backend.exe --host 127.0.0.1 --port 8000
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys
    import uvicorn

    parser = argparse.ArgumentParser(description="Sasoo Backend Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (dev only)")

    args = parser.parse_args()

    # Determine if we're running as a bundled executable
    is_bundled = getattr(sys, 'frozen', False)

    # In bundled mode, run the app object directly (no reload)
    # In development, allow reload
    if is_bundled:
        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            log_level="info",
        )
    else:
        uvicorn.run(
            "main:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
            reload_dirs=[str(Path(__file__).resolve().parent)] if args.reload else None,
        )
