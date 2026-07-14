"""Sasoo - analysis_supervisor: 분석 워커 스폰 (frozen/dev argv 분기, env sanitize, 디태치 Popen).

서버 프로세스는 이 모듈로 분석 워커를 별도 프로세스로 스폰한다. 워커는 서버와 완전히
독립적으로 살아남아야 하므로(PyInstaller 재실행 환경 리셋, 서버 임시 CA 파일 수명과
무관하게 동작, 서버 소켓 fd 미상속) 아래 함수들이 그 경계를 담당한다.

리컨실러도 이 모듈 소관: 주기 루프가 stale run 조정(papers-terminal > cancel > attempts-error
> requeue) → attempts 상한 정리 → cap까지 큐 드레인(claim+spawn)을 반복한다.
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
    # M4: 워커는 서버 HTTP API를 호출하지 않는다 — 최소권한 원칙상 상속 금지.
    env.pop("SASOO_API_TOKEN", None)
    env.pop("SASOO_SHUTDOWN_TOKEN", None)
    return env


# 스폰한 워커 핸들. start_new_session은 세션만 새로 열 뿐 부모를 바꾸지 않으므로("디태치"는
# 터미널 신호로부터의 분리를 뜻한다) 워커는 서버의 직계 자식으로 남고, 회수는 서버 몫이다.
_CHILDREN: list[subprocess.Popen] = []


def reap_exited_workers() -> None:
    """종료한 워커를 회수해 좀비(<defunct>)를 없앤다. 리컨실러 틱과 스폰 시점에 호출된다.

    Popen 핸들을 버리면 CPython은 '다음 Popen 호출' 때만 회수하므로(subprocess._active +
    _cleanup) 다음 분석이 오기 전까지 종료한 워커가 좀비로 남는다. 좀비는 메모리도 fd도 안
    잡지만 pid 슬롯을 점유하고, 무엇보다 os.kill(pid, 0)을 통과한다 — 훗날 pid 기반 생존
    판정을 넣으면 죽은 워커를 살아있다고 오판해 재스폰이 영영 막힌다(현재 생존 판정은
    heartbeat 리스이며 pid는 정보성 필드다).
    """
    _CHILDREN[:] = [p for p in _CHILDREN if p.poll() is None]  # poll = waitpid(WNOHANG)


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
    # 핸들을 붙잡으면 Popen.__del__ → subprocess._active 경로가 안 타므로 회수는 전적으로
    # reap_exited_workers() 책임이 된다. 리컨실러가 꺼진 경로에서도 새지 않도록 여기서도 부른다.
    _CHILDREN.append(proc)
    reap_exited_workers()
    return proc.pid


def terminate_workers(grace_s: float = 5.0) -> int:
    """결정①: 정상 종료(graceful shutdown) 훅 — 살아있는 워커에 SIGTERM → grace_s 대기 →
    미종료 시 SIGKILL. 종료시킨(SIGTERM을 보낸) 워커 개수를 반환한다.

    비정상 종료(크래시/SIGKILL)는 이 함수가 호출되는 lifespan shutdown 경로 자체를 타지
    않으므로 워커가 그대로 살아남는다 — 그게 이 아키텍처의 존재 이유(리로드·크래시 내성)라
    의도적으로 건드리지 않는다. 개별 워커 처리 중 예외는 삼키고 로그만 남겨, 한 워커 정리
    실패가 나머지 워커 정리를 막지 않게 한다."""
    n = 0
    for proc in list(_CHILDREN):
        try:
            if proc.poll() is not None:
                continue  # 이미 종료됨
            proc.terminate()
            try:
                proc.wait(timeout=grace_s)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=grace_s)
                except Exception:  # noqa: BLE001
                    pass
            n += 1
        except Exception:  # noqa: BLE001
            logger.exception("워커 종료 실패 pid=%s", getattr(proc, "pid", None))
    reap_exited_workers()
    return n


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

    # 스폰 시점에만 회수하면 다음 분석이 올 때까지 좀비가 남는다 — 틱마다 회수해 창을 닫는다.
    reap_exited_workers()

    await ar.reconcile_stale(conn, stale_cut=stale_cut, max_attempts=MAX_ATTEMPTS, now=now)
    # 결함1: reconcile_stale ②(cancel-wins)는 analysis_runs만 쓰고 papers를 안 건드린다 —
    # run=terminal인데 papers='analyzing'로 영구 고착되는 좀비(취소 중 워커 사망, /cancel
    # papers UPDATE 직전 사망, /run upsert_queued 실패로 이전 terminal 행 잔존)를 역방향
    # 스윕으로 회수한다. running인 run은 건드리지 않아 정상 진행 중인 분석을 보호한다.
    await ar.sweep_orphan_analyzing_papers(conn)
    # C1: cap 초과로 queued에 머문 채 cancel_requested=1만 세워진 행은 claim_next(cancel_requested=0
    # 필터)·reconcile_stale(status='running'만 봄)·mark_over_attempts_error(attempts만 봄) 어디서도
    # 소비되지 않아 영구 좀비가 된다. attempts 정리보다 먼저 cancel-wins으로 확정한다.
    await ar.sweep_cancelled_queued(conn, now)
    await ar.mark_over_attempts_error(conn, MAX_ATTEMPTS)

    while True:
        claimed = await ar.claim_next(conn, cap=cap, now=now, fresh_cut=fresh_cut,
                                      backoff_cut=backoff_cut, max_attempts=MAX_ATTEMPTS)
        if claimed is None:
            break
        paper_id, generation = claimed
        try:
            # M1: 번들 재실행(exec) 포함 동기 spawn을 이벤트 루프에서 직접 돌리면 /run 핸들러가
            # 블로킹된다 — 스레드로 위임(spawn 주입 시그니처는 유지).
            pid = await asyncio.to_thread(spawn, paper_id, generation)
        except Exception:  # noqa: BLE001
            logger.exception("워커 스폰 실패 paper=%s gen=%s — queued 복귀", paper_id, generation)
            await ar.finalize_run(conn, paper_id, generation, "queued", now)
            continue
        try:
            await ar.set_pid(conn, paper_id, generation, pid)
        except Exception:  # noqa: BLE001
            # pid는 정보성 필드 — 워커는 이미 살아 있고 생존 판정은 heartbeat 리스가 담당.
            # 여기서 requeue하면 다음 사이클이 같은 paper를 재claim해 이중 스폰된다.
            logger.exception("set_pid 실패 paper=%s pid=%s — 워커 생존, heartbeat가 생존 신호이므로 requeue 안 함", paper_id, pid)


async def _reconciler_loop(app) -> None:
    from models.database import get_db
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
    """서브프로세스 모드에서만 리컨실러를 띄운다.

    플래그가 꺼진 in-process 모드에서 리컨실러가 돌면, 고아 시드 → claim → 워커 스폰으로
    이어져 "플래그 off = 기존 경로 그대로"라는 계약을 깨고 예상치 못한 과금이 발생한다
    (터미널로 백엔드만 직접 띄우는 개발 경로 포함). 대신 구 안전망(analyzing 고아를 error로
    정리)을 복원해, 리컨실러 없이도 프로세스 사망으로 남은 고아가 방치되지 않게 한다.
    """
    if os.environ.get("SASOO_ANALYSIS_SUBPROCESS") != "1":
        from models.database import execute_update

        try:
            await execute_update("UPDATE papers SET status='error' WHERE status='analyzing'")
        except Exception as exc:  # noqa: BLE001
            logger.warning("legacy stuck-analysis cleanup failed: %s", exc)
        return
    app.state.reconciler_task = asyncio.create_task(_reconciler_loop(app))


async def stop_reconciler(app) -> None:
    """정상 종료 훅 — main.py lifespan shutdown이 부른다.

    reconciler_task가 없으면(서브프로세스 모드 off) 워커 자체가 없으므로 아무 것도 하지
    않는다("플래그 off = 기존 경로 그대로" 계약 유지). 있으면 루프를 취소한 뒤 워커를 함께
    종료(SIGTERM→SIGKILL)하고, 중단된 running을 requeue해 다음 서버 기동 때 45초 stale
    대기 없이 곧바로 재개되게 한다. 정상 종료는 "실패"가 아니므로 attempts는 requeue_for_shutdown이
    상쇄한다. 실패는 로그만 남기고 종료 자체를 막지 않는다.

    한계: _CHILDREN은 이 서버 프로세스 메모리에만 있다 — 서버가 재기동돼 이전 서버가 남긴
    워커가 있으면 이 함수는 그 워커를 못 죽인다(빈 _CHILDREN). 그 경우는 fence(generation)와
    heartbeat 리스가 처리한다(범위 밖)."""
    task = getattr(app.state, "reconciler_task", None)
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    try:
        terminate_workers()
    except Exception as exc:  # noqa: BLE001
        logger.warning("terminate_workers 실패(정상 종료 계속 진행): %s", exc)

    try:
        from models.database import get_db
        conn = await get_db()
        await ar.requeue_for_shutdown(conn, datetime.now(timezone.utc).isoformat())
    except Exception as exc:  # noqa: BLE001
        logger.warning("requeue_for_shutdown 실패(정상 종료 계속 진행): %s", exc)
