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
        if not hasattr(os, "waitid"):
            self.skipTest("os.waitid is unavailable on this platform")
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


class TerminateWorkersTests(unittest.TestCase):
    """결정①: 정상 종료 시 워커도 함께 종료 — SIGTERM → grace_s 대기 → 미종료 시 SIGKILL."""

    def test_sigterm_then_sigkill_when_still_alive_after_grace(self):
        from services import analysis_supervisor as sup
        import subprocess as sp

        self.addCleanup(sup._CHILDREN.clear)
        proc = MagicMock()
        proc.pid = 111
        proc.poll.side_effect = [None, 0]  # 진입 시 생존 확인 -> 회수 시엔 종료 확인
        proc.wait.side_effect = [sp.TimeoutExpired(cmd="x", timeout=5), 0]
        sup._CHILDREN.clear()
        sup._CHILDREN.append(proc)

        n = sup.terminate_workers(grace_s=5.0)

        self.assertEqual(n, 1)
        proc.terminate.assert_called_once()
        proc.kill.assert_called_once()
        self.assertEqual(sup._CHILDREN, [])  # 종료 후 reap되어 목록에서 빠짐

    def test_no_sigkill_when_terminates_within_grace(self):
        from services import analysis_supervisor as sup

        self.addCleanup(sup._CHILDREN.clear)
        proc = MagicMock()
        proc.pid = 222
        proc.poll.side_effect = [None, 0]
        proc.wait.side_effect = [0]  # SIGTERM만으로 grace 내 종료
        sup._CHILDREN.clear()
        sup._CHILDREN.append(proc)

        n = sup.terminate_workers(grace_s=5.0)

        self.assertEqual(n, 1)
        proc.terminate.assert_called_once()
        proc.kill.assert_not_called()

    def test_skips_already_exited_children(self):
        from services import analysis_supervisor as sup

        self.addCleanup(sup._CHILDREN.clear)
        proc = MagicMock()
        proc.pid = 333
        proc.poll.return_value = 0  # 이미 종료됨
        sup._CHILDREN.clear()
        sup._CHILDREN.append(proc)

        n = sup.terminate_workers(grace_s=5.0)

        self.assertEqual(n, 0)
        proc.terminate.assert_not_called()

    def test_swallows_per_worker_exception_and_continues(self):
        from services import analysis_supervisor as sup

        self.addCleanup(sup._CHILDREN.clear)
        bad = MagicMock()
        bad.pid = 444
        bad.poll.return_value = None
        bad.terminate.side_effect = RuntimeError("boom")
        good = MagicMock()
        good.pid = 555
        good.poll.side_effect = [None, 0]
        good.wait.side_effect = [0]
        sup._CHILDREN.clear()
        sup._CHILDREN.extend([bad, good])

        n = sup.terminate_workers(grace_s=5.0)

        self.assertEqual(n, 1)  # bad는 예외로 실패, good은 성공
        good.terminate.assert_called_once()

    def test_returns_zero_when_no_children(self):
        from services import analysis_supervisor as sup
        self.addCleanup(sup._CHILDREN.clear)
        sup._CHILDREN.clear()
        self.assertEqual(sup.terminate_workers(), 0)


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


class StopReconcilerShutdownTests(unittest.IsolatedAsyncioTestCase):
    """결정①: 정상 종료 시 stop_reconciler가 워커를 함께 종료하고 running을 requeue한다.

    비정상 종료(크래시/SIGKILL)는 이 코드 경로 자체를 안 타므로 범위 밖 — lifespan shutdown이
    도는 정상 종료에서만 적용된다."""

    async def test_stop_reconciler_terminates_workers_and_requeues_when_reconciler_was_running(self):
        # 결함1: 워커 종료·requeue는 SASOO_ENV=='production'(프로덕션 정상 종료)에서만 돈다.
        import asyncio
        from unittest.mock import AsyncMock
        from services import analysis_supervisor as sup

        app = types.SimpleNamespace(state=types.SimpleNamespace())
        app.state.reconciler_task = asyncio.create_task(asyncio.sleep(10))

        fake_conn = object()
        with patch.dict(os.environ, {"SASOO_ENV": "production"}), \
             patch.object(sup, "terminate_workers", return_value=2) as terminate_mock, \
             patch("models.database.get_db", new=AsyncMock(return_value=fake_conn)), \
             patch.object(sup.ar, "requeue_for_shutdown", new=AsyncMock(return_value=3)) as requeue_mock:
            await sup.stop_reconciler(app)

        terminate_mock.assert_called_once()
        requeue_mock.assert_awaited_once()
        self.assertIs(requeue_mock.await_args.args[0], fake_conn)

    async def test_stop_reconciler_preserves_workers_when_env_is_development(self):
        # 결함1: dev의 uvicorn --reload SIGTERM도 이 lifespan shutdown 경로를 태우지만,
        # 리로드일 뿐 진짜 앱 종료가 아니므로 워커를 죽이면 안 된다(진행 중 유료 분석 보호).
        # 리컨실러 태스크 취소는 env와 무관하게 항상 일어나야 한다.
        import asyncio
        from unittest.mock import AsyncMock
        from services import analysis_supervisor as sup

        app = types.SimpleNamespace(state=types.SimpleNamespace())
        app.state.reconciler_task = asyncio.create_task(asyncio.sleep(10))

        with patch.dict(os.environ, {"SASOO_ENV": "development"}), \
             patch.object(sup, "terminate_workers") as terminate_mock, \
             patch.object(sup.ar, "requeue_for_shutdown", new=AsyncMock()) as requeue_mock:
            await sup.stop_reconciler(app)

        terminate_mock.assert_not_called()
        requeue_mock.assert_not_awaited()
        self.assertTrue(app.state.reconciler_task.cancelled())

    async def test_stop_reconciler_preserves_workers_when_env_unset(self):
        # 결함1: SASOO_ENV 미설정(맨 터미널 dev 실행 포함)도 dev와 동일하게 워커를 보존한다.
        import asyncio
        from unittest.mock import AsyncMock
        from services import analysis_supervisor as sup

        app = types.SimpleNamespace(state=types.SimpleNamespace())
        app.state.reconciler_task = asyncio.create_task(asyncio.sleep(10))

        saved = os.environ.pop("SASOO_ENV", None)
        try:
            with patch.object(sup, "terminate_workers") as terminate_mock, \
                 patch.object(sup.ar, "requeue_for_shutdown", new=AsyncMock()) as requeue_mock:
                await sup.stop_reconciler(app)
        finally:
            if saved is not None:
                os.environ["SASOO_ENV"] = saved

        terminate_mock.assert_not_called()
        requeue_mock.assert_not_awaited()
        self.assertTrue(app.state.reconciler_task.cancelled())

    async def test_stop_reconciler_does_not_touch_workers_when_flag_was_off(self):
        # start_reconciler가 플래그 off에서 reconciler_task를 아예 세우지 않으므로,
        # stop_reconciler는 워커 정리를 시도하지 말아야 한다(off 모드엔 워커가 없다).
        from services import analysis_supervisor as sup

        app = types.SimpleNamespace(state=types.SimpleNamespace())
        with patch.object(sup, "terminate_workers") as terminate_mock, \
             patch.object(sup.ar, "requeue_for_shutdown") as requeue_mock:
            await sup.stop_reconciler(app)

        terminate_mock.assert_not_called()
        requeue_mock.assert_not_called()

    async def test_stop_reconciler_swallows_requeue_failure(self):
        # 정상 종료(production) 자체를 막으면 안 된다 — DB 접근 실패는 로그만 남기고 넘어간다.
        import asyncio
        from unittest.mock import AsyncMock
        from services import analysis_supervisor as sup

        app = types.SimpleNamespace(state=types.SimpleNamespace())
        app.state.reconciler_task = asyncio.create_task(asyncio.sleep(10))

        with patch.dict(os.environ, {"SASOO_ENV": "production"}), \
             patch.object(sup, "terminate_workers", return_value=0), \
             patch("models.database.get_db", new=AsyncMock(side_effect=RuntimeError("db closed"))):
            await sup.stop_reconciler(app)  # 예외 없이 반환돼야 함


class ReadBudgetStateTests(unittest.IsolatedAsyncioTestCase):
    """결정②: 리컨실러 재개 경로도 /run과 같은 예산 계산식을 써야 한다."""

    @staticmethod
    def _settings_stub(settings: dict):
        async def _fake(*args, **kwargs):
            return settings
        stub = types.ModuleType("api.settings")
        stub._get_all_settings = _fake
        return stub

    async def test_returns_spending_and_limit(self):
        from unittest.mock import AsyncMock
        from services import analysis_supervisor as sup

        rows = [{"cost_usd": 3.0}, {"cost_usd": None}, {"cost_usd": 2.25}]
        with patch.dict(sys.modules, {"api.settings": self._settings_stub({"monthly_budget_limit": "12.5"})}), \
             patch("models.database.fetch_all", new=AsyncMock(return_value=rows)):
            spending, limit = await sup.read_budget_state()

        self.assertEqual(limit, 12.5)
        self.assertEqual(spending, 5.25)   # None은 0.0으로 취급(/run과 동일)

    async def test_defaults_limit_to_50_when_setting_missing(self):
        from unittest.mock import AsyncMock
        from services import analysis_supervisor as sup

        with patch.dict(sys.modules, {"api.settings": self._settings_stub({})}), \
             patch("models.database.fetch_all", new=AsyncMock(return_value=[])):
            spending, limit = await sup.read_budget_state()

        self.assertEqual(limit, 50.0)
        self.assertEqual(spending, 0.0)

    async def test_query_excludes_error_phase_and_scopes_to_current_month(self):
        # /run의 SQL(phase != 'error', created_at >= month_start AND < month_end)과 동일한지
        # fetch_all에 전달되는 쿼리·파라미터로 확인한다.
        from unittest.mock import AsyncMock
        from services import analysis_supervisor as sup

        fetch_mock = AsyncMock(return_value=[])
        with patch.dict(sys.modules, {"api.settings": self._settings_stub({"monthly_budget_limit": "50.0"})}), \
             patch("models.database.fetch_all", new=fetch_mock):
            await sup.read_budget_state()

        query, params = fetch_mock.await_args.args
        self.assertIn("phase != 'error'", query)
        self.assertIn("analysis_results", query)
        self.assertEqual(len(params), 2)  # month_start, month_end
        self.assertRegex(params[0], r"^\d{4}-\d{2}-01$")
        self.assertRegex(params[1], r"^\d{4}-\d{2}-01$")
