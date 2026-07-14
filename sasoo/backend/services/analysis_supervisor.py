"""Sasoo - analysis_supervisor: 분석 워커 스폰 (frozen/dev argv 분기, env sanitize, 디태치 Popen).

서버 프로세스는 이 모듈로 분석 워커를 별도 프로세스로 스폰한다. 워커는 서버와 완전히
독립적으로 살아남아야 하므로(PyInstaller 재실행 환경 리셋, 서버 임시 CA 파일 수명과
무관하게 동작, 서버 소켓 fd 미상속) 아래 함수들이 그 경계를 담당한다.
"""

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from models.database import APP_DATA_ROOT

BACKEND_DIR = Path(__file__).resolve().parent.parent  # sasoo/backend
_LOG_DIR = APP_DATA_ROOT / "logs"


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
