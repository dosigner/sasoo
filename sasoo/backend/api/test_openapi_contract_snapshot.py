"""Freeze the public HTTP contract before moving route responsibilities."""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import httpx

from main import app


SNAPSHOT = Path(__file__).parent / "fixtures" / "openapi_snapshot.json"


def test_openapi_snapshot_and_non_openapi_mounts():
    assert app.openapi() == json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    direct_paths = {getattr(route, "path", None) for route in app.routes}
    assert "/static/library/{requested_path:path}" in direct_paths
    assert "/shutdown" in direct_paths


def test_unauthorized_cors_response_contract():
    asyncio.run(_assert_unauthorized_cors())


async def _assert_unauthorized_cors():
    transport = httpx.ASGITransport(app=app)
    with patch.dict("os.environ", {"SASOO_API_TOKEN": "contract-test-token"}):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/agents", headers={"Origin": "null"})
    assert response.status_code == 401
    assert response.json() == {"detail": "Missing or invalid local API token"}
    assert "access-control-allow-origin" not in response.headers
