import sys
import types
import unittest
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
        fake_proc = types.SimpleNamespace(pid=4242)
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
