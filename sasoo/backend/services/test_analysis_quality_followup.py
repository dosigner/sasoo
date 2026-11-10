"""Regression from frozen paid outputs; no provider calls or library writes."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import fitz

from services import analysis_execution as ae
from services.document_context import select_visual_source
from services.evidence_verifier import verify_recipe_reproduction
from services.viz import figure_gen

BASE = Path(__file__).resolve().parents[3] / 'docs/validation/assets/analysis-followup-20261012'
OLD = BASE.parent / 'parallel-live-20261011'
SOURCE = (BASE / 'source.md').read_text(encoding="utf-8")


def test_table_payload_reaches_description_without_prefix_truncation():
    item = {'title': 'FM OT comparison', 'description': 'Table 1 CIFAR-10 NLL FID NFE', 'diagram_type': 'additional'}
    old_prompt = json.loads((OLD / '61bf2b13fb704fe8832a2cdfb85e8045-request.json').read_text(encoding="utf-8"))['prompt']
    assert all(value not in old_prompt for value in ('2.99', '6.35', '142'))
    call = AsyncMock(return_value={'text': 'Use the verified table values.', 'model': 'gpt-6-luna', 'tokens_in': 1, 'tokens_out': 1})

    async def generate(enriched, *args, **kwargs):
        await figure_gen._plan_description(enriched, llm_provider='openai')
        return figure_gen.FigureGenResult('/mock.png', 'openai', 0, 0, None, [])

    with patch.object(figure_gen, 'generate_illustration', new=generate), patch('api.settings._get_all_settings', new=AsyncMock(return_value={})), patch('services.llm.interactions_client.call_interaction', new=call):
        result = asyncio.run(ae._generate_single_paperbanana(7, item, SOURCE, 'fixture', '', '', llm_provider='openai'))
    prompt = call.call_args.args[0]
    assert all(value in prompt for value in ('2.99', '6.35', '142', 'PDF page 8'))
    assert result['source_evidence']['status'] == 'selected_text'


def test_missing_table_is_not_sent_to_paid_generation():
    call = AsyncMock()
    with patch.object(figure_gen, 'generate_illustration', new=call):
        out = asyncio.run(ae._generate_single_paperbanana(7, {'description': 'Table 1 results'}, 'No table data', 'fixture', '', ''))
    assert out['error'] and out['requests'] == []
    call.assert_not_called()


def test_density_flow_swap_from_actual_description_is_detected():
    description = json.loads((OLD / '65ed3f5fbe0a48628bc4b9adfeb83cf5-response.json').read_text(encoding="utf-8"))['text']
    assert figure_gen.equation_role_conflicts(description, SOURCE)
    assert not figure_gen.equation_role_conflicts(r'p_t(x|x_1) = \mathcal{N}(x|mu,sigma); \psi_t(x)=sigma*x+mu', SOURCE)


def test_html_payload_contains_formula_definitions_and_positions():
    item = {'title': 'OT calculator', 'description': 'Section 4.1 Equations 10, 21–23. Compare fixed position with moving path.'}
    call = AsyncMock(return_value={'text': '<input><script>console.assert(true)</script>', 'model': 'gpt-6-luna', 'tokens_in': 1, 'tokens_out': 1})
    with patch.object(ae, 'call_interaction', new=call):
        out = asyncio.run(ae._generate_single_html(item, SOURCE, provider='openai'))
    prompt = call.call_args.args[0]
    for text in [r'\tag{21}', r'\tag{22}', r'\tag{23}', r'\tag{10}', 'PDF page 4', 'PDF page 6', '독립 변수', 'Number()']:
        assert text in prompt
    assert out['scientific_validation'] == 'unverified'


def test_source_conditions_and_absence_claims_are_separate():
    with fitz.open(BASE / 'source.pdf') as doc:
        pages = [page.get_text() for page in doc]
    for variant in ('A', 'B'):
        sample = json.loads((BASE / f'blind-sample-{variant}.json').read_text(encoding="utf-8"))
        recipe = sample['recipe']; original = deepcopy(recipe)
        out = verify_recipe_reproduction(recipe, pages)
        topics = {i['topic']: i for i in out['items']}
        assert any(e['page'] == 17 and '+ 7' in e['quote'] and e['status'] == 'needs_review' for e in topics['evaluation']['evidence'])
        assert any(e['page'] == 17 and e['status'] == 'needs_review' for e in topics['preprocessing']['evidence'])
        assert any(e['page'] in (3, 4) for e in topics['sampling']['evidence'])
        assert topics['target_loss']['evidence']
        if variant == 'A':
            assert any(c['path'].startswith('steps') for c in topics['sampling']['conflicts'])
        else:
            assert not topics['preprocessing']['conflicts']  # U-Net normalization is a different condition.
        assert all(c['status'] == 'absence_unverified' for c in out['missing_info_claims'])
        assert recipe == original
        assert len(sample['deep_dive']) == 17
        assert len(sample['deep_dive']['section_answers']) == 12
        assert len(sample['deep_dive']['transfer_checks']) == 8


def test_review_without_applicable_conditions_is_not_forced_into_a_recipe():
    out = verify_recipe_reproduction({'steps': [], 'missing_info': ['training seed not reported']}, ['A literature review of governance.'])
    assert all(i['status'] == 'source_not_located' for i in out['items'])
    assert out['status'] == 'unverified'
    assert out['missing_info_claims'][0]['status'] == 'absence_unverified'


def test_recipe_route_returns_separate_local_check_and_preserves_raw_recipe():
    from api import analysis_routes
    sample = json.loads((BASE / 'blind-sample-A.json').read_text(encoding="utf-8"))['recipe']
    original = deepcopy(sample)
    with patch.object(analysis_routes, 'get_latest_completed_phase_row', new=AsyncMock(return_value={'id': 1, 'parsed_result': sample})), patch.object(analysis_routes, 'fetch_one', new=AsyncMock(return_value={'folder_name': 'fixture'})), patch.object(analysis_routes, 'get_paper_dir', return_value=BASE), patch.object(analysis_routes, 'build_evidence_payload', new=AsyncMock(return_value=None)):
        out = asyncio.run(analysis_routes.get_recipe(7))
    assert out['recipe'] == original
    assert out['reproduction_check']['status'] == 'needs_review'
    assert out['evidence'] is None


def test_bad_description_stops_render_and_keeps_known_description_spend():
    description = json.loads((OLD / '65ed3f5fbe0a48628bc4b9adfeb83cf5-response.json').read_text(encoding="utf-8"))['text']
    record = {'id': 'offline-describe', 'kind': 'describe', 'model_used': 'gpt-6-luna', 'cost_usd': 0.02}
    renderer = AsyncMock()
    with patch.object(figure_gen, '_plan_description', new=AsyncMock(return_value=(description, record))), patch.object(figure_gen, '_render_image', new=renderer):
        out = asyncio.run(figure_gen.generate_illustration({'source_context': SOURCE}, '/unused'))
    assert out.path is None and 'flow map' in out.error
    assert out.requests == [record] and out.cost_usd == 0.02
    renderer.assert_not_called()
