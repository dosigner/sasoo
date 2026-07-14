import hashlib
import hmac
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException, UploadFile

from api import papers, settings
from main import app, library_asset


class ApiAuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def test_api_requires_matching_runtime_token(self) -> None:
        transport = httpx.ASGITransport(app=app)

        with patch.dict(os.environ, {"SASOO_API_TOKEN": "test-runtime-token"}):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                unauthorized = await client.get("/api/agents")
                authorized = await client.get(
                    "/api/agents",
                    headers={"Authorization": "Bearer test-runtime-token"},
                )
                health = await client.get("/health")

        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(authorized.status_code, 200)
        self.assertEqual(health.status_code, 200)
        self.assertEqual(
            health.json()["instance_proof"],
            hmac.digest(
                b"test-runtime-token",
                b"sasoo-health-v1",
                hashlib.sha256,
            ).hex(),
        )
        self.assertNotIn("library_path", health.json())

    async def test_production_refuses_api_when_token_is_missing(self) -> None:
        transport = httpx.ASGITransport(app=app)

        with patch.dict(
            os.environ,
            {"SASOO_ENV": "production", "SASOO_API_TOKEN": ""},
        ):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/agents")

        self.assertEqual(response.status_code, 503)

    async def test_cors_preflight_is_allowed_without_api_token(self) -> None:
        transport = httpx.ASGITransport(app=app)

        with patch.dict(os.environ, {"SASOO_API_TOKEN": "test-runtime-token"}):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.options(
                    "/api/agents",
                    headers={
                        "Origin": "null",
                        "Access-Control-Request-Method": "GET",
                    },
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("access-control-allow-origin"), "null")

    async def test_asset_token_cannot_authorize_api_requests(self) -> None:
        transport = httpx.ASGITransport(app=app)
        asset_token = hmac.digest(
            b"test-runtime-token",
            b"sasoo-asset-v1:/static/library/paper/example.png",
            hashlib.sha256,
        ).hex()

        with (
            patch.dict(os.environ, {"SASOO_API_TOKEN": "test-runtime-token"}),
            patch("main.fetch_one", new=AsyncMock(return_value=None)),
        ):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                allowed_asset = await client.get(
                    "/static/library/paper/example.png",
                    params={"sasoo_asset_token": asset_token},
                )
                rejected_api = await client.get(
                    "/api/agents",
                    params={"sasoo_asset_token": asset_token},
                )

        self.assertNotEqual(allowed_asset.status_code, 401)
        self.assertEqual(rejected_api.status_code, 401)


class FileBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def test_upload_filename_discards_path_components(self) -> None:
        self.assertEqual(papers.safe_pdf_filename("../../escaped.pdf"), "escaped.pdf")
        self.assertEqual(papers.safe_pdf_filename(r"C:\\Temp\\escaped.pdf"), "escaped.pdf")

    def test_library_path_rejects_filesystem_root(self) -> None:
        with self.assertRaises(HTTPException) as context:
            settings.resolve_library_path_update(Path(Path.cwd().anchor))

        self.assertEqual(context.exception.status_code, 400)

    async def test_upload_size_limit_removes_partial_file(self) -> None:
        upload = UploadFile(
            file=io.BytesIO(b"%PDF-oversized"),
            filename="paper.pdf",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            paper_dir = Path(temp_dir) / "paper"
            with (
                patch("api.papers.MAX_PDF_UPLOAD_BYTES", 8),
                patch("api.papers.get_paper_dir", return_value=paper_dir),
                patch("api.papers.ensure_text_artifacts_async", new=AsyncMock()) as parse,
            ):
                with self.assertRaises(HTTPException) as context:
                    await papers.upload_paper(upload)

        self.assertEqual(context.exception.status_code, 413)
        self.assertFalse(paper_dir.exists())
        parse.assert_not_awaited()

    async def test_static_route_rejects_unknown_paper_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            secret = root / "secret.txt"
            secret.write_text("not public", encoding="utf-8")

            with (
                patch("main.get_library_search_roots", return_value=(root,)),
                patch("main.fetch_one", new=AsyncMock(return_value=None)),
            ):
                with self.assertRaises(HTTPException) as context:
                    await library_asset("secret.txt")

        self.assertEqual(context.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
