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
