import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class SpawnBuilderTests(unittest.TestCase):
    def test_argv_frozen_uses_executable_directly(self):
        from services import analysis_supervisor as sup
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "executable", "/opt/sasoo/sasoo-backend"):
            argv = sup.build_worker_argv(7, 3)
        self.assertEqual(argv, ["/opt/sasoo/sasoo-backend", "--analyze-paper", "7", "--run-generation", "3"])

    def test_argv_dev_prepends_main_py(self):
        from services import analysis_supervisor as sup
        if hasattr(sys, "frozen"):
            self.skipTest("frozen attr present")
        with patch.object(sys, "executable", "/venv/bin/python"):
            argv = sup.build_worker_argv(7, 3)
        self.assertEqual(argv[0], "/venv/bin/python")
        self.assertTrue(argv[1].endswith("main.py"))
        self.assertEqual(argv[2:], ["--analyze-paper", "7", "--run-generation", "3"])

    def test_env_sets_pyinstaller_reset_and_pops_ca(self):
        from services import analysis_supervisor as sup
        env = sup.build_spawn_env({"SSL_CERT_FILE": "/tmp/x.pem", "REQUESTS_CA_BUNDLE": "/tmp/x.pem",
                                    "GEMINI_API_KEY": "k"})
        self.assertEqual(env["PYINSTALLER_RESET_ENVIRONMENT"], "1")
        self.assertEqual(env["SASOO_ANALYSIS_WORKER"], "1")
        self.assertNotIn("SSL_CERT_FILE", env)          # 서버 atexit 삭제 대상이라 상속 금지
        self.assertNotIn("REQUESTS_CA_BUNDLE", env)
        self.assertEqual(env["GEMINI_API_KEY"], "k")     # API 키는 상속

    def test_env_pops_api_and_shutdown_tokens(self):
        # M4: 워커는 서버 HTTP API를 쓰지 않으니 최소권한 원칙상 API/셧다운 토큰은 상속 금지.
        from services import analysis_supervisor as sup
        env = sup.build_spawn_env({
            "SASOO_API_TOKEN": "secret-api-token",
            "SASOO_SHUTDOWN_TOKEN": "secret-shutdown-token",
            "GEMINI_API_KEY": "k",
        })
        self.assertNotIn("SASOO_API_TOKEN", env)
        self.assertNotIn("SASOO_SHUTDOWN_TOKEN", env)
        self.assertEqual(env["GEMINI_API_KEY"], "k")   # 분석에 필요한 키는 계속 상속

    def test_spawn_worker_uses_detach_flags(self):
        from services import analysis_supervisor as sup
        self.addCleanup(sup._CHILDREN.clear)   # 모듈 전역 회수 목록이 테스트 간 새지 않게
        # poll()=0 → 이미 종료한 셈이라 spawn_worker의 회수 패스가 곧바로 목록에서 제거한다.
        fake_proc = types.SimpleNamespace(pid=4242, poll=lambda: 0)
        with patch("services.analysis_supervisor.subprocess.Popen", return_value=fake_proc) as popen, \
             patch("services.analysis_supervisor.open", create=True):
            pid = sup.spawn_worker(7, 3)
        self.assertEqual(pid, 4242)
        _, kwargs = popen.call_args
        self.assertTrue(kwargs.get("close_fds"))
        if sys.platform == "win32":
            self.assertIn("creationflags", kwargs)
        else:
            self.assertTrue(kwargs.get("start_new_session"))

    def test_reap_exited_workers_reaps_without_a_new_spawn(self):
        """분석이 더 오지 않아도 종료한 워커를 회수한다 — 좀비(<defunct>) 잔존 방지.

        start_new_session은 세션만 새로 열 뿐 부모를 바꾸지 않으므로 워커는 서버의 직계
        자식으로 남는다. CPython은 핸들이 버려진 자식을 '다음 Popen 호출' 때만 회수하므로
        (subprocess._active + _cleanup), 다음 분석이 없으면 종료한 워커가 백엔드 수명 내내
        좀비로 남는다. 좀비 pid는 os.kill(pid, 0)을 통과하니, 훗날 pid 기반 생존 판정을
        넣으면 죽은 워커를 살아있다고 오판해 재스폰이 영영 막힌다.
        """
        if sys.platform == "win32":
            self.skipTest("좀비는 POSIX 시맨틱")
        from services import analysis_supervisor as sup
        with tempfile.TemporaryDirectory() as td, \
             patch.object(sup, "_LOG_DIR", Path(td)), \
             patch.object(sup, "build_worker_argv", return_value=[sys.executable, "-c", ""]):
            pid = sup.spawn_worker(1, 1)
            # 종료만 기다리고 회수는 하지 않는다(WNOWAIT) — 회수는 프로덕션 코드 몫이어야 한다.
            os.waitid(os.P_PID, pid, os.WEXITED | os.WNOWAIT)
            sup.reap_exited_workers()   # 새 스폰 없이 회수돼야 한다
        # 회수됐다면 pid는 더 이상 우리 자식이 아니다.
        with self.assertRaises(ChildProcessError):
            os.waitpid(pid, os.WNOHANG)


if __name__ == "__main__":
    unittest.main()


class ReconcilerFlagGateTests(unittest.IsolatedAsyncioTestCase):
    """플래그 off에서 리컨실러가 워커를 스폰하면 '기존 경로 그대로' 계약이 깨진다(과금 위험)."""

    async def test_start_reconciler_noop_and_legacy_cleanup_when_flag_off(self):
        import os
        from unittest.mock import AsyncMock
        from services import analysis_supervisor as sup

        app = types.SimpleNamespace(state=types.SimpleNamespace())
        saved = os.environ.pop("SASOO_ANALYSIS_SUBPROCESS", None)
        try:
            with patch("models.database.execute_update", new=AsyncMock()) as cleanup:
                await sup.start_reconciler(app)
        finally:
            if saved is not None:
                os.environ["SASOO_ANALYSIS_SUBPROCESS"] = saved

        self.assertIsNone(getattr(app.state, "reconciler_task", None))  # 루프 미기동
        cleanup.assert_awaited_once()  # 구 안전망(analyzing→error) 복원
        self.assertIn("status='analyzing'", cleanup.await_args.args[0])

    async def test_start_reconciler_starts_loop_when_flag_on(self):
        import os
        from unittest.mock import AsyncMock
        from services import analysis_supervisor as sup

        app = types.SimpleNamespace(state=types.SimpleNamespace())
        with patch.dict(os.environ, {"SASOO_ANALYSIS_SUBPROCESS": "1"}), \
             patch.object(sup, "_reconciler_loop", new=AsyncMock()):
            await sup.start_reconciler(app)
            self.assertIsNotNone(app.state.reconciler_task)
            await sup.stop_reconciler(app)
