"""
Sasoo - AI Co-Scientist Backend
FastAPI entry point.

Runs on http://localhost:8000 by default.
"""

import os
import ssl
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# SSL: Use OS certificate store for all outbound HTTPS connections.
# Fixes SSL errors on corporate/university networks with SSL inspection proxies.
# Two-layer approach:
#   1. Export Windows cert store → temp PEM file → SSL_CERT_FILE env var
#      (covers httpx verify=certifi.where(), requests, urllib3, etc.)
#   2. truststore.inject_into_ssl() patches ssl.SSLContext directly
#      (covers ssl.create_default_context() callers)
# ---------------------------------------------------------------------------
def _export_os_certs():
    """Export OS certificate store to PEM file and set SSL env vars."""
    import sys
    if sys.platform != "win32":
        return
    # Skip if user already set these (e.g., corporate IT policy)
    if os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE"):
        return
    try:
        import base64, tempfile, atexit
        ctx = ssl.create_default_context()          # loads Windows Certificate Store
        certs = ctx.get_ca_certs(binary_form=True)
        if not certs:
            return
        pem = b""
        for der in certs:
            pem += b"-----BEGIN CERTIFICATE-----\n"
            pem += base64.encodebytes(der)
            pem += b"-----END CERTIFICATE-----\n"
        fd, path = tempfile.mkstemp(suffix=".pem", prefix="sasoo_certs_")
        os.write(fd, pem)
        os.close(fd)
        os.environ["SSL_CERT_FILE"] = path
        os.environ["REQUESTS_CA_BUNDLE"] = path
        atexit.register(lambda: os.unlink(path) if os.path.exists(path) else None)
    except Exception:
        pass  # non-critical — fall back to default cert handling

_export_os_certs()  # BEFORE truststore — get raw Windows certs first

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from models.database import (
    APP_DATA_ROOT,
    close_db,
    get_library_root,
    get_library_search_roots,
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

    # Set up centralized logging (file + console)
    from services.log_setup import setup_logging
    import logging
    log_level = logging.DEBUG if os.environ.get("SASOO_ENV") != "production" else logging.INFO
    setup_logging(level=log_level)
    print(f"[Sasoo] App data root: {APP_DATA_ROOT}")
    print(f"[Sasoo] Database: {APP_DATA_ROOT / 'sasoo.db'}")
    print(f"[Sasoo] Library root: {get_library_root()}")

    # Load API keys from database into environment variables (with decryption)
    from models.database import fetch_all
    from services.crypto import decrypt_value
    try:
        rows = await fetch_all("SELECT key, value FROM settings WHERE key IN ('gemini_api_key', 'anthropic_api_key')")
        for row in rows:
            k, v = row["key"], row["value"]
            if v:
                decrypted = decrypt_value(v)
                if decrypted:
                    if k == "gemini_api_key":
                        os.environ["GEMINI_API_KEY"] = decrypted
                    elif k == "anthropic_api_key":
                        os.environ["ANTHROPIC_API_KEY"] = decrypted
        print("[Sasoo] API keys loaded from database into environment.")
    except Exception as exc:
        print(f"[Sasoo] Warning: Could not load API keys from DB: {exc}")

    # Always sync GOOGLE_API_KEY with GEMINI_API_KEY (PaperBanana uses this)
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if gemini_key:
        os.environ["GOOGLE_API_KEY"] = gemini_key

    # Load .md agent profiles and initialize domain router
    from services.agents import load_all_agents
    load_all_agents()
    print("[Sasoo] Agent profiles loaded from .md files.")

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
        "powered by Gemini 3.1 + Claude Sonnet 4.5 dual LLM."
    ),
    version="0.6.6",
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

APP_DATA_ROOT.mkdir(parents=True, exist_ok=True)
get_library_root().mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

from api.papers import router as papers_router              # noqa: E402
from api.analysis_routes import router as analysis_router   # noqa: E402
from api.settings import router as settings_router          # noqa: E402
from api.agents import router as agents_router              # noqa: E402

app.include_router(papers_router)
app.include_router(analysis_router)
app.include_router(settings_router)
app.include_router(agents_router)


# ---------------------------------------------------------------------------
# Root health-check
# ---------------------------------------------------------------------------

@app.get("/", tags=["health"])
async def root():
    return {
        "service": "sasoo",
        "status": "running",
        "version": "0.6.6",
        "library_path": str(get_library_root()),
    }


@app.get("/health", tags=["health"])
async def health_check():
    return {
        "status": "ok",
        "library_path": str(get_library_root()),
    }


@app.get("/static/library/{requested_path:path}", include_in_schema=False)
async def library_asset(requested_path: str):
    relative_path = Path(requested_path)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise HTTPException(status_code=400, detail="Invalid library asset path")

    for root in get_library_search_roots():
        resolved_root = root.resolve(strict=False)
        candidate = (root / relative_path).resolve(strict=False)
        try:
            candidate.relative_to(resolved_root)
        except ValueError:
            continue
        if candidate.is_file():
            return FileResponse(candidate)

    raise HTTPException(status_code=404, detail="Library asset not found")


@app.post("/shutdown", tags=["health"])
async def shutdown(x_shutdown_token: Optional[str] = Header(None)):
    """Graceful shutdown endpoint (called by Electron on app quit).
    Requires X-Shutdown-Token header matching SASOO_SHUTDOWN_TOKEN env var."""
    expected_token = os.environ.get("SASOO_SHUTDOWN_TOKEN", "")
    if expected_token and x_shutdown_token != expected_token:
        raise HTTPException(status_code=403, detail="Invalid shutdown token")

    import signal

    os.kill(os.getpid(), signal.SIGINT)
    return {"status": "shutting_down"}


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
