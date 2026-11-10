"""Check the backend against the same HMAC vectors as Electron."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from main import app


VECTORS = json.loads((Path(__file__).resolve().parents[2] / "contract-fixtures/hmac-vectors.json").read_text())


def test_health_and_asset_hmac_vectors():
    asyncio.run(_check_vectors())


async def _check_vectors():
    with patch.dict("os.environ", {"SASOO_API_TOKEN": VECTORS["token"]}), patch(
        "main.fetch_one", new=AsyncMock(return_value=None)
    ), patch("api.papers.fetch_one", new=AsyncMock(return_value=None)):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            health = await client.get("/health")
            assert health.json()["instance_proof"] == VECTORS["health"]
            for path, token in VECTORS["assets"].items():
                accepted = await client.get(path, params={"sasoo_asset_token": token})
                rejected = await client.get(path, params={"sasoo_asset_token": "0" * 64})
                assert accepted.status_code != 401
                assert rejected.status_code == 401
