"""Record Python agent parsing, domain selection, personas and chain system instructions.

Usage: backend/.venv/bin/python -I tests/agents_oracle.py <backend_dir> <out_json>
"""
import itertools
import json
import os
import sys
from pathlib import Path

os.environ["PYTHON_DOTENV_DISABLED"] = "1"
backend, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
sys.path.insert(0, str(backend))

import services.agents as agents  # noqa: E402
from api.analysis_context import build_chain_system_instruction, build_reader_profile_block  # noqa: E402
from api.settings import parse_research_areas  # noqa: E402
from services import analysis_execution as ae  # noqa: E402
from services.agents.md_loader import parse_agent_md  # noqa: E402

bundled = sorted((backend / "agents").glob("*.md"))
synthetic = {
    "quoted": "---\nname: q\ndomain: optics\npersonality: 'It''s \"fine\"'\nenabled: true\n---\n# Visual\n비주얼\n## sub\n줄\n# Deep Dive\n딥\n# Recipe\n\n레시피\n",
    "disabled": "---\nname: off\ndomain: bio\npersonality: plain text: with colon\nenabled: false\n---\n# Visual\nx\n",
    "no_frontmatter": "# Visual\n그냥 본문\n",
    "dup_domain": "---\nname: second_optics\ndomain: optics\npersonality: \"두 번째\"\nkeywords:\n  - a\n  - b\n---\n# Recipe\n두번째 레시피\n",
    "zz_other": "---\nname: zz\ndomain: zz_domain\npersonality: 마지막 # comment\n---\n",
}
texts = {p.name: p.read_text(encoding="utf-8") for p in bundled}
texts.update(synthetic)

parsed = {}
for name, text in texts.items():
    p = parse_agent_md(text)
    parsed[name] = {"agent_name": p.agent_name, "domain": p.domain, "personality": p.personality,
                    "enabled": p.enabled, "prompts": p.prompts,
                    "persona": {str(s): ae._build_persona_prompt(agents.MdAgent(p), s) for s in ["visual", "recipe", "deep_dive", None]}}

catalogs = {
    "bundled": [p.name for p in bundled],
    "bundled_plus": [p.name for p in bundled] + ["quoted", "disabled", "dup_domain", "zz_other"],
    "no_optics": [n for n in [p.name for p in bundled] if n != "photon.md"] + ["zz_other"],
    "empty": [],
}
selection = []
for cat_name, names in catalogs.items():
    profiles = [parse_agent_md(texts[n]) for n in names]
    agents.list_all_agents = lambda profiles=profiles: profiles
    agents._AGENT_CACHE.clear()
    agents.load_all_agents()
    for domain in ["optics", "bio", "ai_ml", "ee", "general", "unknown_domain", "photon", "zz_domain", ""]:
        a = agents.get_agent_for_domain(domain)
        selection.append({"catalog": cat_name, "names": names, "domain": domain, "agent_name": a.name,
                          "persona_visual": ae._build_persona_prompt(a, "visual")})

profiles = []
for areas, exp, read, role, level in itertools.product(
        [[], ["ai_ml"], ["optics_photonics", "bogus", "physics_math", "other", "ai_ml"]],
        ["major", "novice", "research", "expert", "bogus"], ["regular", "rare", "author"],
        ["grad_student", "engineer", "manager"], ["", "masters", "undergrad"]):
    profiles.append({"args": [areas, exp, read, role, level],
                     "output": build_reader_profile_block(areas, exp, read, role, level_key=level)})

chains = []
for persona, ctx, focus, level, reader in itertools.product(
        ["", "  페르소나  "], ["", " 광통신 연구 "], [None, {}, {"chips": ["theory", "bogus", "reproduction"]}, {"note": " 질문? "}, {"chips": [], "note": ""}],
        ["masters", "phd", "bogus"], ["", "독자 전공: AI·머신러닝."]):
    chains.append({"args": [persona, ctx, focus, level, reader],
                   "output": build_chain_system_instruction(persona, ctx, focus, level, reader_profile=reader)})

areas = [{"input": raw, "output": parse_research_areas(raw)} for raw in
         ["", "[]", '["ai_ml", 3, "other", "x", "y"]', "{}", "not json", '"ai_ml"', None]]
domains = [{"screening": s, "paper_domain": pd, "output": (lambda d: d.get("domain") or pd or "general")(json.loads(ae._clean_llm_json(s or "{}")))}
           for s in ['{"domain": "bio"}', '{"domain": ""}', "{}", ""] for pd in [None, "", "ee"]]
out.write_text(json.dumps({"texts": texts, "parsed": parsed, "selection": selection, "profiles": profiles,
                           "chains": chains, "areas": areas, "domains": domains}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
