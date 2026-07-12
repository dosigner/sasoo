"""
Tests for Task 8: agent API reduction to read-only endpoints.

Follows the mock-based unittest.IsolatedAsyncioTestCase style used elsewhere
in api/ (this project has no pytest-asyncio / FastAPI TestClient fixture
wired up). Uses httpx.AsyncClient with ASGITransport against the real `app`
from main.py so we exercise actual FastAPI routing (404 vs 405 depends on
whether the path exists at all vs. exists with a different method).
"""

import unittest

import httpx

from main import app


class AgentReadOnlyApiTests(unittest.IsolatedAsyncioTestCase):
    async def _client(self) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app)
        return httpx.AsyncClient(transport=transport, base_url="http://test")

    async def test_agent_crud_endpoints_removed(self) -> None:
        async with await self._client() as client:
            self.assertIn(
                (await client.post("/api/agents", json={})).status_code, (404, 405)
            )
            self.assertIn(
                (await client.put("/api/agents/photon", json={})).status_code, (404, 405)
            )
            self.assertIn(
                (await client.delete("/api/agents/photon")).status_code, (404, 405)
            )
            self.assertIn(
                (await client.post("/api/agents/generate", json={})).status_code, (404, 405)
            )
            self.assertIn(
                (await client.post("/api/agents/photon/duplicate")).status_code, (404, 405)
            )
            self.assertIn(
                (await client.patch("/api/agents/photon/toggle", json={"enabled": False})).status_code,
                (404, 405),
            )
            self.assertIn(
                (await client.get("/api/agents/photon/export")).status_code, (404, 405)
            )
            self.assertIn(
                (await client.post("/api/agents/import")).status_code, (404, 405)
            )

    async def test_agent_read_endpoints_kept(self) -> None:
        async with await self._client() as client:
            resp = await client.get("/api/agents")
            self.assertEqual(resp.status_code, 200)
            agents = resp.json()
            self.assertGreaterEqual(len(agents), 1)

            first_name = agents[0]["name"]
            detail_resp = await client.get(f"/api/agents/{first_name}")
            self.assertEqual(detail_resp.status_code, 200)
            self.assertEqual(detail_resp.json()["name"], first_name)

    async def test_agent_get_unknown_name_still_404s(self) -> None:
        async with await self._client() as client:
            resp = await client.get("/api/agents/__does_not_exist__")
            self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
