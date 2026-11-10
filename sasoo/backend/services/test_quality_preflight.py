"""Source selection and local review boundaries, without provider requests."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from services import analysis_execution as ae
from services.document_context import select_visual_source
from services.evidence_verifier import verify_recipe_reproduction


def test_table_continues_on_following_page():
    source = '--- Page 8 ---\nTable 1: Results\n| Model | NLL |\n| A | 3.12 |\n--- Page 9 ---\n| B | 2.99 |\nDefinitions of NLL follow.'
    out = select_visual_source({'description': 'Table 1'}, source)
    assert out['status'] == 'selected_text'
    assert '2.99' in out['text'] and 'PDF page 9' in out['text']


def test_unrelated_table_rows_do_not_verify_requested_table():
    source = '--- Page 1 ---\nTable 1: lost rows\n--- Page 2 ---\nTable 2: other data\n| value | 42 |'
    assert select_visual_source({'description': 'Table 1 Table 2'}, source)['missing_tables'] == ['1']


def test_long_equation_is_not_cut_and_oversize_is_explicit():
    source = '--- Page 7 ---\n$$f(x)=' + 'x+' * 4500 + r'0\tag{12}$$' + '\nAll variables are dimensionless.'
    out = select_visual_source({'description': 'Equation 12'}, source)
    assert out['status'] == 'selected_text' and out['text'].endswith('dimensionless.')
    out = select_visual_source({'description': 'Equation 12'}, source, limit=8000)
    assert out['status'] == 'incomplete_evidence' and out['omitted_required_pages'] == [7]


def test_equation_mention_alone_does_not_satisfy_source_gate():
    source = '--- Page 4 ---\nWe use Equation (21) for this comparison.'
    out = select_visual_source({'description': 'Equation 21'}, source)
    assert out['missing_equations'] == ['21']
    assert out['transcription_verified'] is False


@pytest.mark.parametrize('source', ['', '--- Page 1 ---\nEquation (21) was unreadable.'])
def test_unreadable_source_blocks_html_before_issuance(source):
    call = AsyncMock()
    with patch.object(ae, 'call_interaction', new=call):
        with pytest.raises(ae.VizGenerationError):
            asyncio.run(ae._generate_single_html({'description': 'Equation 21'}, source, provider='openai'))
    call.assert_not_called()


def test_raw_pdf_text_is_not_mistaken_for_transcribed_table():
    out = select_visual_source({'description': 'Table 1'}, 'Table 1. Results\nModel\nNLL\nA\n2.99')
    assert out['missing_tables'] == ['1']


def test_recipe_keeps_long_formula_and_variable_definitions():
    formula = '$$L=' + 'x+' * 4000 + '0$$'
    text = 'The regression target is a velocity.\n\n' + formula + '\n\nx is the dimensionless input.'
    out = verify_recipe_reproduction({'steps': []}, [text])
    evidence = next(i for i in out['items'] if i['topic'] == 'target_loss')['evidence']
    assert any('regression target' in e['quote'] for e in evidence)
    assert any('x+' * 4000 in e['quote'] for e in evidence)


def test_architecture_normalization_and_seed_are_not_source_conflicts():
    recipe = {'steps': ['Time sampling random seed is not reported.'], 'missing_info': ['U-Net normalization is not reported.', 'ODE solver random seed not reported.']}
    out = verify_recipe_reproduction(recipe, ['t ~ U[0,1].\n\nPixel input is normalized.\n\nODE solver tolerance rtol=1e-5.'])
    assert not any(i['conflicts'] for i in out['items'])
    assert all(c['status'] == 'absence_unverified' for c in out['missing_info_claims'])


def test_absence_in_critical_notes_is_reviewed():
    out = verify_recipe_reproduction({'critical_notes': ['Time sampling is not specified.']}, ['where t ~ U[0,1].'])
    sampling = next(i for i in out['items'] if i['topic'] == 'sampling')
    assert sampling['conflicts'][0]['path'] == 'critical_notes[0]'


def test_unreadable_pdf_never_proves_absence():
    out = verify_recipe_reproduction({'missing_info': ['Pixel preprocessing not reported.']}, ['\ufffd\ufffd\ufffd'])
    assert out['status'] == 'unverified'
    assert all(i['status'] == 'source_not_located' for i in out['items'])


def test_lossy_equation_can_use_original_pdf_without_claiming_verified_text():
    from services.llm.openai_client import load_pdf_part
    from services.test_analysis_quality_followup import BASE
    pdf = load_pdf_part(BASE / 'source.pdf')
    call = AsyncMock(return_value={'text':'<input><script>console.assert(true)</script>', 'model':'gpt-6-luna','tokens_in':1,'tokens_out':1})
    with patch.object(ae,'call_interaction',new=call):
        out=asyncio.run(ae._generate_single_html({'description':'Equation 21'}, 'Equation was lost.',provider='openai',openai_pdf_part=pdf))
    prompt=call.call_args.args[0]
    assert prompt[0]['sha256']==pdf['sha256'] and prompt[0]['data']==pdf['data']
    assert out['source_evidence']['status']=='provided_pdf'
    assert out['source_evidence']['transcription_verified'] is False
    assert out['scientific_validation']=='unverified'


def test_pdf_reaches_image_description_and_pdf_hash_changes_visual_cache():
    from services.viz import figure_gen
    from services.llm.openai_client import load_pdf_part
    from services.test_analysis_quality_followup import BASE
    pdf=load_pdf_part(BASE/'source.pdf')
    call=AsyncMock(return_value={'text':'Use the supplied PDF.', 'model':'gpt-6-luna','tokens_in':1,'tokens_out':1})
    async def generate(enriched,*args,**kwargs):
        await figure_gen._plan_description(enriched,llm_provider='openai')
        return figure_gen.FigureGenResult('/mock.png','openai',0,0,None,[])
    with patch.object(figure_gen,'generate_illustration',new=generate), patch('api.settings._get_all_settings',new=AsyncMock(return_value={})), patch('services.llm.interactions_client.call_interaction',new=call):
        out=asyncio.run(ae._generate_single_paperbanana(7,{'description':'Table 1'},'Lost table rows.','fixture','','',llm_provider='openai',openai_pdf_part=pdf))
    assert call.call_args.args[0][0]['sha256']==pdf['sha256']
    assert out['source_evidence']['status']=='provided_pdf'
    kwargs=dict(visualization_input='x',previous_results=[],recipe_result='',deep_dive_result='',image_provider='openai',image_quality='high',source_text='x')
    assert ae._visualization_cache_input(**kwargs,source_pdf_sha256='a') != ae._visualization_cache_input(**kwargs,source_pdf_sha256='b')


def test_real_truncated_html_is_rejected_with_settled_usage():
    import json
    from pathlib import Path
    live = Path(__file__).resolve().parents[3] / 'docs/validation/assets/quality-live-20261014-flow'
    rows = [json.loads(line) for line in (live / 'campaign/ledger.jsonl').read_text(encoding="utf-8").splitlines()]
    row = next(r for r in rows if r.get('key') == 'viz_image_plan:9:text'
               and 'candidate' in r['run_id'] and r['state'] == 'settled')
    response = json.loads((live / 'campaign' / (row['id'] + '-response.json')).read_text(encoding="utf-8"))
    call = AsyncMock(return_value=response)
    from services.test_analysis_quality_followup import SOURCE
    with patch.object(ae, 'call_interaction', new=call):
        with pytest.raises(ae.VizGenerationError, match='did not complete') as error:
            asyncio.run(ae._generate_single_html({'description': 'Equation 21'}, SOURCE, provider='openai'))
    assert call.call_count == 1
    assert call.call_args.kwargs['max_output_tokens'] == 8000
    assert '9,000자' in call.call_args.args[0]
    assert response['tokens_out'] == 8000
    assert error.value.requests[0]['cost_usd'] == pytest.approx(float(row['cost_usd']))


def test_flow_matching_bibliography_excludes_tables_and_appendix():
    from pathlib import Path
    from services.document_context import build_document_context_from_text
    from services.citation_analyzer import parse_references
    source = Path(__file__).resolve().parents[3] / 'docs/validation/assets/quality-preflight-20261012/inputs/2023_FlowMatching_ai_ml/FLOW_MATCHING_FOR_GENERATIVE_MODELING.md'
    refs = build_document_context_from_text(source.read_text(encoding="utf-8"))['phase_inputs']['citation_references']
    entries = parse_references(refs)
    # Independent PDF review counted 14 + 18 + 17 + 3 entries on pages 10–13.
    assert len(entries) == 52
    assert entries[0].raw_text.startswith('Michael S Albergo')
    assert entries[-1].raw_text.startswith('Qinsheng Zhang')
    assert all(word not in refs for word in ('Table 2:', 'THEOREM PROOFS', 'Adam optimizer'))
