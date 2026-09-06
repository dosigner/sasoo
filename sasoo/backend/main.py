"""
Sasoo - AI Co-Scientist Backend
FastAPI entry point.

Runs on http://localhost:8000 by default.
"""

import os
import ssl
from contextlib import asynccontextmanager
from hmac import compare_digest, digest
from pathlib import Path
from typing import Optional

import uvicorn

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
from fastapi.responses import FileResponse, JSONResponse

from models.database import (
    APP_DATA_ROOT,
    close_db,
    fetch_one,
    get_library_root,
    get_library_search_roots,
    init_db,
)

# Load .env from project root (if present)
_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

_shutdown_server: Optional[uvicorn.Server] = None


# ---------------------------------------------------------------------------
# Runtime bootstrap (shared by the server process and detached analysis workers)
# ---------------------------------------------------------------------------

async def bootstrap_runtime(worker: bool = False) -> None:
    """서버/워커 공통 런타임 초기화(DB 연결 + API 키 + PDF 엔진 설정 + 에이전트 로드).

    worker=True(디태치 분석 워커, `--analyze-paper`로 재실행된 프로세스)면:
      - init_db() 대신 connect_worker_db()로 연결한다(마이그레이션은 서버 기동이 이미 보장).
      - 공유 RotatingFileHandler를 여는 setup_logging()을 호출하지 않는다 — 다중 프로세스가
        같은 로그 파일에 rollover하면 충돌한다. stdout만 남기고(spawn_worker가 per-run 로그
        파일로 리다이렉트한다), 고아 정리(stuck recovery)·리컨실러도 실행하지 않는다(서버 전용).
    """
    import logging

    if worker:
        from models.database import connect_worker_db
        await connect_worker_db()
        logging.basicConfig(level=logging.INFO)
    else:
        await init_db()
        from api.settings import _ensure_defaults
        await _ensure_defaults()

        # Set up centralized logging (file + console)
        from services.log_setup import setup_logging
        log_level = logging.DEBUG if os.environ.get("SASOO_ENV") != "production" else logging.INFO
        setup_logging(level=log_level)
        print(f"[Sasoo] Database: {APP_DATA_ROOT / 'sasoo.db'}")
        print(f"[Sasoo] Library root: {get_library_root()}")

    print(f"[Sasoo] App data root: {APP_DATA_ROOT}")

    # Load API keys + PDF visual-engine preference from the settings table.
    # F7: 한 번의 fetch_all(IN 절)로 세 키를 함께 읽어 기동 시 DB 왕복을 1회로 줄인다
    # (예전엔 API 키용 fetch_all + pdf_visual_engine용 fetch_one으로 2회 왕복).
    # 처리 방식은 다르다: api 키는 암호화 저장되어 복호화가 필요하고, pdf_visual_engine은
    # 평문 문자열이다. 파싱은 개별 try로 감싸 한쪽 실패가 다른 쪽 로드를 막지 않게 한다.
    from models.database import fetch_all
    from services.api_key_runtime import load_api_keys_from_settings
    settings_map: dict[str, str] = {}
    try:
        rows = await fetch_all(
            "SELECT key, value FROM settings "
            "WHERE key IN ('gemini_api_key', 'openai_api_key', 'pdf_visual_engine')"
        )
        settings_map = {row["key"]: row["value"] for row in rows}
    except Exception as exc:
        print(f"[Sasoo] Warning: Could not load settings from DB: {exc}")

    await load_api_keys_from_settings(settings_map, worker)

    # PDF visual-engine preference: odl_parser의 _resolve_stage_engine이 호출 시점에
    # SASOO_PDF_VISUAL_ENGINE을 읽으므로, 저장된 선택을 여기서 env에 심어 이번 세션 첫
    # 파싱부터 반영한다. (신규 DB엔 행이 없어 resolver 기본값 gemini가 그대로 선다.)
    try:
        engine = str(settings_map.get("pdf_visual_engine") or "").strip().lower()
        if engine in {"gemini", "odl"}:
            os.environ["SASOO_PDF_VISUAL_ENGINE"] = engine
            print(f"[Sasoo] PDF visual engine preference loaded: {engine}")
    except Exception as exc:
        print(f"[Sasoo] Warning: Could not load PDF visual engine preference: {exc}")

    # Load .md agent profiles and initialize domain router
    from services.agents import load_all_agents
    load_all_agents()
    print("[Sasoo] Agent profiles loaded from .md files.")


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: initialize resources on startup, clean up on shutdown."""
    # --- Startup ---
    await bootstrap_runtime(worker=False)

    # 프로세스 분리: 기동 시 고아('analyzing'인데 runs 행 없음)를 큐로 시드하고 리컨실러를 띄운다.
    # (예전의 "죽은 'analyzing' → 'error' 일괄 정리"를 대체 — 이제는 정리 대신 재개를 시도한다.)
    from services.analysis_supervisor import start_reconciler
    await start_reconciler(app)

    yield

    # --- Shutdown ---
    from services.analysis_supervisor import stop_reconciler
    await stop_reconciler(app)

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
        "powered by the Gemini API (Interactions)."
    ),
    version="0.9.0",
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


@app.middleware("http")
async def require_runtime_api_token(request, call_next):
    """Require the per-launch Electron capability token for local API access.

    Browsers and other local processes can both reach a loopback server.  A
    localhost binding is therefore not an authentication boundary.  Electron
    supplies ``SASOO_API_TOKEN`` when it launches the backend, while ``/health``
    remains unauthenticated so startup can check that a newly selected port is
    listening without disclosing application data.
    """
    expected_token = os.environ.get("SASOO_API_TOKEN", "")
    if request.method == "OPTIONS" or request.url.path == "/health":
        return await call_next(request)
    if not expected_token:
        if os.environ.get("SASOO_ENV") == "production":
            return JSONResponse(
                status_code=503,
                content={"detail": "Local API token is not configured"},
            )
        return await call_next(request)

    authorization = request.headers.get("Authorization", "")
    bearer_token = (
        authorization.removeprefix("Bearer ")
        if authorization.startswith("Bearer ")
        else ""
    )
    path = request.url.path
    paper_id = path.removeprefix("/api/papers/").removesuffix("/pdf")
    is_asset_path = path.startswith("/static/library/") or (
        path == f"/api/papers/{paper_id}/pdf" and paper_id.isdigit()
    )
    supplied_asset_token = request.query_params.get("sasoo_asset_token", "")
    expected_asset_token = digest(
        expected_token.encode(),
        f"sasoo-asset-v1:{path}".encode(),
        "sha256",
    ).hex()
    has_valid_asset_token = (
        is_asset_path
        and bool(supplied_asset_token)
        and compare_digest(supplied_asset_token, expected_asset_token)
    )
    if (
        (not bearer_token or not compare_digest(bearer_token, expected_token))
        and not has_valid_asset_token
    ):
        return JSONResponse(
            status_code=401,
            content={"detail": "Missing or invalid local API token"},
        )

    return await call_next(request)

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
        "version": "0.9.0",
        "library_path": str(get_library_root()),
    }


@app.get("/health", tags=["health"])
async def health_check():
    runtime_token = os.environ.get("SASOO_API_TOKEN", "")
    return {
        "status": "ok",
        "instance_proof": (
            digest(runtime_token.encode(), b"sasoo-health-v1", "sha256").hex()
            if runtime_token
            else ""
        ),
    }


@app.get("/static/library/{requested_path:path}", include_in_schema=False)
async def library_asset(requested_path: str):
    relative_path = Path(requested_path)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise HTTPException(status_code=400, detail="Invalid library asset path")

    # Files are public only below a paper folder that exists in the database.
    # This prevents a changed library root from turning this route into a
    # general-purpose file server for the selected directory.
    if not relative_path.parts:
        raise HTTPException(status_code=404, detail="Library asset not found")
    paper = await fetch_one(
        "SELECT 1 FROM papers WHERE folder_name = ?",
        (relative_path.parts[0],),
    )
    if paper is None:
        raise HTTPException(status_code=404, detail="Library asset not found")

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
    if not expected_token:
        raise HTTPException(status_code=503, detail="Shutdown token is not configured")
    if not x_shutdown_token or not compare_digest(x_shutdown_token, expected_token):
        raise HTTPException(status_code=403, detail="Invalid shutdown token")

    if _shutdown_server is None:
        raise HTTPException(status_code=503, detail="Graceful shutdown is unavailable")
    _shutdown_server.should_exit = True
    return {"status": "shutting_down"}


# ---------------------------------------------------------------------------
# Run directly with: python main.py [--host HOST] [--port PORT]
# Production usage: sasoo-backend.exe --host 127.0.0.1 --port 8000
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Sasoo Backend Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (dev only)")
    parser.add_argument("--analyze-paper", type=int, default=None,
                         help="Run detached analysis worker for this paper id (internal — spawned by the supervisor)")
    parser.add_argument("--run-generation", type=int, default=0,
                         help="Fence token for the analysis worker (internal)")

    args = parser.parse_args()

    # Detached analysis worker mode: re-exec of this same bundle with --analyze-paper.
    # Runs the analysis in-process and exits — never reaches uvicorn.run() below.
    if args.analyze_paper is not None:
        import asyncio
        from services.analysis_worker import run_analysis_worker
        sys.exit(asyncio.run(run_analysis_worker(args.analyze_paper, args.run_generation)))

    # Determine if we're running as a bundled executable
    is_bundled = getattr(sys, 'frozen', False)

    if is_bundled or not args.reload:
        config = uvicorn.Config(
            app,
            host=args.host,
            port=args.port,
            log_level="info",
        )
        _shutdown_server = uvicorn.Server(config)
        try:
            _shutdown_server.run()
        finally:
            _shutdown_server = None
    else:
        uvicorn.run(
            "main:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
            reload_dirs=[str(Path(__file__).resolve().parent)] if args.reload else None,
        )
