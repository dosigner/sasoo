"""Sasoo - analysis_supervisor: 분석 워커 스폰 (frozen/dev argv 분기, env sanitize, 디태치 Popen).

서버 프로세스는 이 모듈로 분석 워커를 별도 프로세스로 스폰한다. 워커는 서버와 완전히
독립적으로 살아남아야 하므로(PyInstaller 재실행 환경 리셋, 서버 임시 CA 파일 수명과
무관하게 동작, 서버 소켓 fd 미상속) 아래 함수들이 그 경계를 담당한다.
"""

import asyncio
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from models import analysis_runs as ar
from models.database import APP_DATA_ROOT

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent  # sasoo/backend
_LOG_DIR = APP_DATA_ROOT / "logs"

LEASE_S = 45
MAX_ATTEMPTS = 3
BACKOFF_S = 60
RECONCILE_INTERVAL_S = 15


def build_worker_argv(paper_id: int, generation: int) -> list[str]:
    """frozen(번들)=exe 직접 재실행, dev=python main.py. 둘 다 main.py argparse로 라우팅된다."""
    tail = ["--analyze-paper", str(paper_id), "--run-generation", str(generation)]
    if getattr(sys, "frozen", False):
        return [sys.executable, *tail]
    return [sys.executable, str(BACKEND_DIR / "main.py"), *tail]


def build_spawn_env(base_env: dict | None = None) -> dict:
    """워커 env: 서버 env 상속 + 워커 플래그. PyInstaller 독립 재실행 + CA 파일 수명 독립."""
    env = dict(os.environ if base_env is None else base_env)
    env["SASOO_ANALYSIS_WORKER"] = "1"
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"  # PyInstaller 6.9+: 자식이 부모 _MEIPASS 환경 리셋
    # 서버가 만든 임시 CA PEM은 서버 atexit이 삭제한다 → 상속하면 서버 종료 시 워커 HTTPS가 깨진다.
    # 워커는 main.py 로드 시 _export_os_certs()로 자기 PEM을 만들어 자기 atexit로 관리한다.
    env.pop("SSL_CERT_FILE", None)
    env.pop("REQUESTS_CA_BUNDLE", None)
    return env


def spawn_worker(paper_id: int, generation: int) -> int:
    """디태치 워커를 스폰하고 자식 pid를 반환한다. stdout/stderr는 per-run 로그로 리다이렉트."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    logpath = _LOG_DIR / f"analysis_paper{paper_id}_g{generation}_{ts}.log"
    argv = build_worker_argv(paper_id, generation)
    env = build_spawn_env()
    kwargs: dict = dict(
        stdin=subprocess.DEVNULL, close_fds=True, cwd=str(BACKEND_DIR), env=env,
    )
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    # with 블록으로 부모 핸들 수명 관리(자식은 자기 fd 복사본 유지)
    with open(logpath, "ab") as f:
        proc = subprocess.Popen(argv, stdout=f, stderr=f, **kwargs)
    return proc.pid


def _iso_shift(now: "datetime", seconds: int) -> str:
    from datetime import timedelta
    return (now - timedelta(seconds=seconds)).isoformat()


async def read_max_concurrent() -> int:
    try:
        from api.settings import _get_all_settings
        settings = await _get_all_settings()
        return max(1, int(settings.get("max_concurrent_analyses", "3")))
    except Exception:
        return 3


async def reconcile_once(conn, cap: int, spawn=spawn_worker) -> None:
    """stale 조정 → attempts 정리 → cap까지 claim+spawn."""
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    stale_cut = _iso_shift(now_dt, LEASE_S)
    fresh_cut = stale_cut
    backoff_cut = _iso_shift(now_dt, BACKOFF_S)

    await ar.reconcile_stale(conn, stale_cut=stale_cut, max_attempts=MAX_ATTEMPTS, now=now)
    await ar.mark_over_attempts_error(conn, MAX_ATTEMPTS)

    while True:
        claimed = await ar.claim_next(conn, cap=cap, now=now, fresh_cut=fresh_cut,
                                      backoff_cut=backoff_cut, max_attempts=MAX_ATTEMPTS)
        if claimed is None:
            break
        paper_id, generation = claimed
        try:
            pid = spawn(paper_id, generation)
            await ar.set_pid(conn, paper_id, generation, pid)
        except Exception as exc:  # noqa: BLE001
            logger.error("spawn failed (paper=%s gen=%s): %s → requeue", paper_id, generation, exc)
            await ar.finalize_run(conn, paper_id, generation, "queued", now)


async def _reconciler_loop(app) -> None:
    from models.database import get_db, execute_update
    try:
        conn = await get_db()
        # startup: 레거시 고아 시드(구 'analyzing→error' 한 줄 대체)
        await ar.seed_legacy(conn, datetime.now(timezone.utc).isoformat())
    except Exception as exc:  # noqa: BLE001
        logger.warning("reconciler seed failed: %s", exc)
    while True:
        try:
            conn = await get_db()
            cap = await read_max_concurrent()
            await reconcile_once(conn, cap=cap)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("reconcile_once error: %s", exc)
        await asyncio.sleep(RECONCILE_INTERVAL_S)


async def start_reconciler(app) -> None:
    app.state.reconciler_task = asyncio.create_task(_reconciler_loop(app))


async def stop_reconciler(app) -> None:
    task = getattr(app.state, "reconciler_task", None)
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
