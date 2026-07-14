import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from main import shutdown


class GracefulShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_requests_uvicorn_exit_without_killing_process(self) -> None:
        # Given
        server = SimpleNamespace(should_exit=False)

        # When
        with (
            patch.dict(os.environ, {"SASOO_SHUTDOWN_TOKEN": "shutdown-token"}),
            patch("main._shutdown_server", server),
            patch("main.os.kill") as kill_process,
        ):
            response = await shutdown("shutdown-token")

        # Then
        self.assertEqual(response, {"status": "shutting_down"})
        self.assertTrue(server.should_exit)
        kill_process.assert_not_called()

    async def test_shutdown_is_disabled_without_a_configured_token(self) -> None:
        # Given
        with patch.dict(os.environ, {"SASOO_SHUTDOWN_TOKEN": ""}):
            # When
            with self.assertRaises(HTTPException) as context:
                await shutdown(None)

        # Then
        self.assertEqual(context.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
