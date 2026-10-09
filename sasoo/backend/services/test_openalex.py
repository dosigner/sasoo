import unittest
from unittest.mock import patch

import httpx

from api.papers import classify_domain
from services import openalex
from services.agents.md_loader import AgentProfile


def _agent(name, domain, subfields=(), keywords=(), builtin=True):
    profile = AgentProfile(
        agent_name=name, domain=domain, keywords=list(keywords),
        openalex_subfields=list(subfields),
    )
    profile.builtin = builtin
    return profile


AGENTS = [
    _agent("photon", "optics", [3107], ["laser", "optical"]),
    _agent("circuit", "ee", [2208], ["circuit", "transistor"]),
    _agent("channel", "optical_communications", [2208], ["link budget", "optical"], builtin=False),
    _agent("general", "general"),
]


class ClassifyDomainTests(unittest.TestCase):
    def setUp(self):
        patcher = patch("services.agents.list_all_agents", return_value=AGENTS)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_subfield_goes_to_the_agent_that_declares_it(self):
        self.assertEqual(classify_domain("transistor circuit", 3107), ("optics", "photon"))

    def test_shared_subfield_is_decided_by_keywords(self):
        self.assertEqual(classify_domain("transistor circuit design", 2208), ("ee", "circuit"))
        self.assertEqual(classify_domain("optical link budget", 2208), ("optical_communications", "channel"))

    def test_shared_subfield_tie_prefers_user_defined_agent(self):
        self.assertEqual(classify_domain("no matching words", 2208), ("optical_communications", "channel"))

    def test_subfield_without_agent_goes_to_general(self):
        # 2505 Materials Chemistry: 범위 안이지만 선언한 에이전트가 없다.
        self.assertEqual(classify_domain("laser optical", 2505), ("general", "general"))

    def test_without_subfield_keywords_decide_and_no_match_is_general(self):
        self.assertEqual(classify_domain("laser optical beam", None), ("optics", "photon"))
        self.assertEqual(classify_domain("protein folding", None), ("general", "general"))


def _client_returning(handler):
    real_client = httpx.AsyncClient

    def factory(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    return patch("services.openalex.httpx.AsyncClient", side_effect=factory)


class LookupSubfieldTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_in_scope_subfield_and_strips_doi_prefix(self):
        seen = []

        def handler(request):
            seen.append(str(request.url))
            return httpx.Response(200, json={"primary_topic": {
                "score": 0.99, "subfield": {"id": "https://openalex.org/subfields/3107"},
            }})

        with _client_returning(handler):
            self.assertEqual(await openalex.lookup_subfield("https://doi.org/10.1364/OE.1"), 3107)
        self.assertIn("/works/doi:10.1364/OE.1", seen[0])

    async def test_out_of_scope_subfield_is_none(self):
        # 2701은 Medicine 소분야라 15개 대분야 표에 없다.
        def handler(request):
            return httpx.Response(200, json={"primary_topic": {"subfield": {"id": "https://openalex.org/subfields/2701"}}})

        with _client_returning(handler):
            self.assertIsNone(await openalex.lookup_subfield("10.1/x"))

    async def test_http_failure_and_missing_doi_are_none(self):
        with _client_returning(lambda request: httpx.Response(429)):
            self.assertIsNone(await openalex.lookup_subfield("10.1/x"))
        with _client_returning(lambda request: httpx.Response(404)):
            self.assertIsNone(await openalex.lookup_subfield("10.1/x"))
        self.assertIsNone(await openalex.lookup_subfield(None))
        self.assertIsNone(await openalex.lookup_subfield("  "))

    def test_bundled_table_covers_fifteen_fields(self):
        table = openalex.subfields()
        self.assertEqual(len({entry["field"] for entry in table.values()}), 15)
        self.assertEqual(openalex.field_name(2505), "Materials Science")
        self.assertIsNone(openalex.field_name(None))


if __name__ == "__main__":
    unittest.main()
