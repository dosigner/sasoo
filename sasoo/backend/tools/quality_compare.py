"""Frozen paired quality evaluation. Preflight and dry-run never call a provider."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile

PHASE = ContextVar('quality_phase', default='unapproved')
ITEM = ContextVar('quality_item', default='stage')


class EvaluationStopped(RuntimeError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_once(path, value):
    with Path(path).open('x') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())


def append(path, row):
    with path.open('a') as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + '\n')
        handle.flush()
        os.fsync(handle.fileno())


@contextmanager
def campaign_lock(directory, *, name=".executor.lock"):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / name).open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise EvaluationStopped('Another executor owns this campaign') from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class Journal:
    """Durable reservation and issuance boundaries for one approved campaign."""
    def __init__(self, directory, manifest):
        self.directory = Path(directory)
        self.path = self.directory / 'ledger.jsonl'
        self.manifest = manifest
        self.owner = uuid.uuid4().hex
        self.lock = threading.RLock()

    def states(self):
        rows = {}; halted = False
        if not self.path.exists():
            return rows, halted
        for line in self.path.read_text().splitlines():
            row = json.loads(line)
            if row['state'] == 'halted':
                halted = True; continue
            previous = rows.get(row['id'])
            allowed = {'reserved': {'issued'}, 'issued': {'settled', 'unsettled'}}
            if (previous is None and row['state'] != 'reserved') or (previous and row['state'] not in allowed.get(previous['state'], set())):
                raise EvaluationStopped('Invalid ledger transition')
            if previous and any(previous[k] != row[k] for k in ('key', 'run_id', 'reserved_usd', 'request_hash', 'owner')):
                raise EvaluationStopped('Ledger identity changed')
            rows[row['id']] = row
        return rows, halted

    def halt(self, reason):
        with self.lock:
            append(self.path, {'state': 'halted', 'reason': reason, 'at': time.time()})

    def ready(self):
        rows, halted = self.states()
        if halted or any(r['state'] != 'settled' or r.get('mode','paid')!=self.manifest.get('mode','paid') for r in rows.values()):
            raise EvaluationStopped('Unknown, interrupted or halted campaign; do not replay')

    def reserve(self, run_id, key, request, kind):
        with self.lock:
            rows, halted = self.states()
            if halted or any(r.get('mode','paid')!=self.manifest.get('mode','paid') or r['state'] == 'unsettled' or (r['state'] != 'settled' and r['owner'] != self.owner) for r in rows.values()):
                raise EvaluationStopped('Unknown or interrupted cost blocks issuance')
            if any(r['run_id'] == run_id and r['key'] == key for r in rows.values()):
                raise EvaluationStopped('Duplicate request or automatic retry blocked')
            if len(rows) >= self.manifest['max_paid_requests'] or sum(r['run_id'] == run_id for r in rows.values()) >= self.manifest['max_requests_per_run']:
                raise EvaluationStopped('Request count cap reached')
            reserve = Decimal(str(self.manifest['reservations_usd'][kind]))
            cost = lambda r: Decimal(str(r['cost_usd'] if r['state'] == 'settled' else r['reserved_usd']))
            if sum((cost(r) for r in rows.values()), Decimal(0)) + reserve > Decimal(str(self.manifest['budget_usd'])):
                raise EvaluationStopped('Budget reservation exceeds campaign cap')
            if sum((cost(r) for r in rows.values() if r['run_id'] == run_id), Decimal(0)) + reserve > Decimal(str(self.manifest['budget_per_run_usd'])):
                raise EvaluationStopped('Budget reservation exceeds run cap')
            row = {'id': uuid.uuid4().hex, 'owner': self.owner, 'run_id': run_id, 'key': key, 'kind': kind,
                   'request_hash': digest(request), 'state': 'reserved', 'reserved_usd': str(reserve), 'mode': self.manifest.get('mode', 'paid'), 'at': time.time()}
            append(self.path, row)
            write_once(self.directory / (row['id'] + '-request.json'), compact(request))
            return row

    def issue(self, row):
        with self.lock:
            rows, halted = self.states()
            if halted or rows[row['id']]['state'] != 'reserved':
                raise EvaluationStopped('Issuance after stop or duplicate issuance blocked')
            if any(r['state'] == 'unsettled' for r in rows.values()):
                raise EvaluationStopped('Unknown cost blocks issuance')
            append(self.path, {**row, 'state': 'issued', 'at': time.time()})

    def settle(self, row, cost, **metadata):
        with self.lock:
            rows, _ = self.states()
            if rows[row['id']]['state'] != 'issued':
                raise EvaluationStopped('Settlement without issuance')
            amount = Decimal(str(cost)) if cost is not None else None
            if amount is not None and (not amount.is_finite() or amount < 0):
                amount = None
            append(self.path, {**row, **metadata, 'state': 'settled' if amount is not None else 'unsettled',
                              'cost_usd': str(amount) if amount is not None else None, 'at': time.time()})
            if amount is None or amount > Decimal(row['reserved_usd']):
                self.halt('Unknown usage or actual spend exceeded its reservation')
            rows, _ = self.states()
            spent = sum((Decimal(str(r['cost_usd'])) if r['state'] == 'settled' else Decimal(r['reserved_usd']) for r in rows.values()), Decimal(0))
            if spent > Decimal(str(self.manifest['budget_usd'])):
                self.halt('Actual spend exceeded campaign cap')


def compact(value):
    if isinstance(value, list):
        return [compact(v) for v in value]
    if isinstance(value, dict):
        return {k: {'bytes': len(v), 'sha256': hashlib.sha256(v.encode()).hexdigest()}
                if k == 'data' and isinstance(v, str) else compact(v) for k, v in value.items()}
    return value


def verify_files(root, hashes):
    root = Path(root).resolve()
    for name, expected in hashes.items():
        original = root / name
        path = original.resolve()
        if not path.is_relative_to(root) or original.is_symlink() or not path.is_file() or file_hash(path) != expected:
            raise EvaluationStopped(f'Frozen file changed: {name}')


def preflight(manifest_path):
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text())
    base = manifest_path.parent
    for spec in manifest['sources'].values():
        if file_hash(base / spec['archive']) != spec['sha256']:
            raise EvaluationStopped('Source archive changed')
        with zipfile.ZipFile(base / spec['archive']) as archive:
            if set(archive.namelist()) != set(spec['files']):
                raise EvaluationStopped('Source inventory changed')
            for name, expected in spec['files'].items():
                if Path(name).is_absolute() or '..' in Path(name).parts or hashlib.sha256(archive.read(name)).hexdigest() != expected:
                    raise EvaluationStopped('Source member changed or unsafe path')
    verify_files(base / 'inputs', manifest['input_hashes'])
    if file_hash(Path(__file__)) != manifest['runner_sha256']:
        raise EvaluationStopped('Runner changed after freeze')
    for paper in manifest['papers']:
        tools = [i['tool'] for i in paper['items']]
        if tools.count('paperbanana') != 5 or tools.count('mermaid') != 3 or tools.count('html') != 1:
            raise EvaluationStopped('Fixed workload is not 5 images, 3 Mermaid, 1 HTML')
        if len({i['id'] for i in paper['items']}) != 9 or not paper['criteria']:
            raise EvaluationStopped('Item identity or ground truth missing')
    return manifest


def validate_approval(manifest_path, approval_path, paper):
    approval = json.loads(Path(approval_path).read_text())
    manifest = preflight(manifest_path)
    if (approval.get('manifest_sha256') != file_hash(manifest_path) or paper not in approval.get('papers', [])
            or approval.get('max_paid_requests', 0) < 42 or Decimal(str(approval.get('budget_usd', 0))) < Decimal('18')
            or approval.get('authorization') != 'explicit_user_approval'):
        raise EvaluationStopped('Missing approval for this exact pair, manifest, call cap and budget')
    return manifest


async def run_variant(manifest_path, campaign, paper_key, variant, *, simulation=False):
    """Called only in a fresh subprocess with a verified source archive."""
    manifest = preflight(manifest_path); base = Path(manifest_path).resolve().parent
    paper = next(p for p in manifest['papers'] if p['key'] == paper_key)
    if not simulation:
        binding = json.loads((campaign / 'binding.json').read_text())
        if binding['manifest_sha256'] != file_hash(manifest_path):raise EvaluationStopped('Campaign binding changed')
        approval_record=campaign/'approval.json'
        if file_hash(approval_record)!=binding['approval_sha256']:raise EvaluationStopped('Approval record changed')
        validate_approval(manifest_path,approval_record,paper_key)
        limits_path=campaign / f'{paper_key}-approved-limits.json'
        limits = json.loads(limits_path.read_text())
        if limits.get('sha256') != digest({k:v for k,v in limits.items() if k!='sha256'}):raise EvaluationStopped('Approved caps changed')
        manifest.update(budget_usd=limits['budget_usd'], max_paid_requests=limits['max_paid_requests'])
    else:
        import socket
        def no_network(*args, **kwargs):raise EvaluationStopped('Network forbidden during simulation')
        socket.socket.connect = socket.socket.connect_ex = no_network
    manifest['mode'] = 'simulation' if simulation else 'paid'
    journal = Journal(campaign, manifest); journal.ready()
    run_id = f'{campaign.name}-{paper_key}-{variant}-{uuid.uuid4().hex}'
    runtime = campaign / f'{paper_key}-{variant}'
    runtime.mkdir()  # A previous run, including an interrupted run, cannot be replayed.
    source = runtime / 'source'; source.mkdir()
    spec = manifest['sources'][variant]
    with zipfile.ZipFile(base / spec['archive']) as archive:
        archive.extractall(source)
    verify_files(source, spec['files'])
    library = runtime / 'library'
    shutil.copytree(base / 'inputs' / paper['folder'], library / paper['folder'])
    os.environ['SASOO_APP_DATA_ROOT'] = str(runtime.resolve())
    sys.path.insert(0, str(source / 'sasoo/backend'))
    from models import database as db
    from services import analysis_execution as ae, model_registry, odl_parser
    from services.llm import openai_client as oc, gemini_client as gc
    from services.viz import figure_gen as fg
    from services.pricing import calc_result_cost, calc_image_cost
    from api import settings

    await db.init_db(); connection = await db.get_db()
    try:
        for table, rows in paper['rows'].items():
            for record in rows:
                record = dict(record)
                if table == 'papers':
                    record.update(status='uploaded', pdf_file_uri=None, pdf_file_expires_at=None)
                columns = ','.join(record)
                await connection.execute(f'INSERT INTO {table} ({columns}) VALUES ({",".join("?" for _ in record)})', tuple(record.values()))
        config = {**manifest['settings'], 'ai_provider': 'openai', 'image_provider': 'openai',
                  'library_path_darwin': str(library.resolve())}
        await connection.executemany('INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)', list(config.items()))
        await connection.commit(); db.invalidate_library_root_cache()
        if odl_parser.paper_artifact_readiness(library / paper['folder']) != (True, True):
            raise EvaluationStopped('Frozen parser inputs are not ready')

        raw_settings = settings._get_all_settings
        async def local_settings():
            return {**await raw_settings(), 'openai_api_key': os.environ.get('OPENAI_API_KEY', '')}
        settings._get_all_settings = ae._get_all_settings = local_settings

        async def no_refresh(*args, **kwargs):
            return None
        ae.schedule_paper_artifacts_refresh = odl_parser.schedule_paper_artifacts_refresh = no_refresh
        async def forbidden(*args, **kwargs):
            journal.halt('Unexpected provider or streaming path')
            raise EvaluationStopped('Unapproved provider path')
        gc.call_interaction = gc.stream_interaction = oc.stream_interaction = forbidden
        if not simulation:
            oc._get_client().max_retries = 0
            oc._get_client().timeout = 600.0
        spans = []; descriptions = {}; raw_call = oc.call_interaction
        if simulation:
            fixtures = json.loads((base / 'inputs' / paper['folder'] / 'offline-responses.json').read_text())
            async def fake_call(prompt, **kwargs):
                role = PHASE.get()
                text = fixtures.get(role)
                if os.environ.get('SASOO_QUALITY_SIMULATION_FAULT')=='timeout':raise TimeoutError('Simulated provider timeout')
                if role=='deep_dive':
                    shape_fixture=json.loads((base/'inputs'/manifest['papers'][0]['folder']/'offline-responses.json').read_text())
                    text=shape_fixture[role]
                if role == 'viz_image_plan':
                    target = next((i for i in paper['items'] if str(i['id'])==ITEM.get()),{})
                    text = '<input type=number value=1><output>1</output><script>console.assert(true)</script>' if target.get('tool')=='html' else 'Draw the supplied structure and preserve all given facts.'
                elif role == 'mermaid':text = 'sequenceDiagram\n participant A\n participant B\n A->>B: Input' if 'sequence' in str(prompt).lower() else 'flowchart TD\n A[Input] --> B[Output]'
                await asyncio.sleep(0)
                return {'text':text,'model':kwargs['model'],'response_model':'gpt-wrong-model' if os.environ.get('SASOO_QUALITY_SIMULATION_FAULT')=='returned-model' else kwargs['model'], 'response_status':'completed', 'usage_complete':os.environ.get('SASOO_QUALITY_SIMULATION_FAULT')!='usage',
                        'tokens_in':100,'tokens_out':10,'tokens_cached':0,'tokens_cache_write':0,'interaction_id':'simulation-'+uuid.uuid4().hex}
            raw_call = fake_call
            if os.environ.get('SASOO_QUALITY_SIMULATION_FAULT')=='model':
                model_registry._REGISTRY['openai']['screening']=model_registry.ModelChoice('gpt-unapproved-model','low')
            fg.OpenAIImageProvider.available = lambda self: True

        def frozen_gate():
            verify_files(source, spec['files'])
            verify_files(base / 'inputs', manifest['input_hashes'])
            verify_files(library, {name:expected for name,expected in manifest['input_hashes'].items() if name.startswith(paper['folder']+'/')})
            actual={str(p.relative_to(source)) for p in source.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
            if actual!=set(spec['files']):raise EvaluationStopped('Runtime source inventory changed')
            if file_hash(Path(__file__)) != manifest['runner_sha256'] or file_hash(manifest_path) != manifest['manifest_hash_at_start']:
                raise EvaluationStopped('Manifest changed during execution')

        # The file's own hash cannot be stored inside it.
        manifest['manifest_hash_at_start'] = file_hash(manifest_path)

        async def audited_call(prompt, **kwargs):
            role = PHASE.get(); item = ITEM.get(); policy = manifest['models'].get(role)
            if not policy or kwargs.get('model') != policy['model'] or kwargs.get('thinking_level') != policy['effort']:
                journal.halt('Unapproved model, effort or phase')
                raise EvaluationStopped('Model/effort contract differs')
            frozen_gate()
            kwargs.update(single_attempt=True, max_output_tokens=policy['max_output_tokens'], service_tier='default')
            row = journal.reserve(run_id, f'{role}:{item}:text', {'prompt': prompt, **kwargs}, 'text')
            journal.issue(row)
            try:
                response = await raw_call(prompt, **kwargs)
                write_once(campaign / (row['id'] + '-response.json'), response)
                cost = calc_result_cost(response) if response.get('usage_complete') is True and response.get('response_model')==policy['model'] else None
                journal.settle(row, cost, response_id=response.get('interaction_id'), model=response.get('response_model'),
                               tokens_in=response.get('tokens_in'), tokens_out=response.get('tokens_out'),
                               tokens_cached=response.get('tokens_cached'), tokens_cache_write=response.get('tokens_cache_write'))
                if response.get('response_model') != policy['model'] or response.get('response_status') != 'completed' or cost is None:
                    journal.halt('Returned model, completion or usage failed'); raise EvaluationStopped('Provider result failed')
                return response
            except BaseException as exc:
                rows, _ = journal.states()
                if rows[row['id']]['state'] == 'issued':
                    journal.settle(row, None, error=type(exc).__name__)
                journal.halt(type(exc).__name__)
                raise
        oc.call_interaction = audited_call

        raw_image = fg.OpenAIImageProvider.generate
        if simulation:
            def fake_image(provider, description):
                provider.usage = {'input_tokens':1,'output_tokens':1, 'input_tokens_details': {'text_tokens':1,'image_tokens':0}}
                return bytes.fromhex('89504e470d0a1a0a')
            raw_image = fake_image
        def audited_image(provider, description):
            frozen_gate()
            item = descriptions.get(digest(description))
            target = next((i for i in paper['items'] if str(i['id']) == item), None)
            if not target or provider._model != manifest['image']['model'] or provider._quality != target['image_quality']:
                journal.halt('Image item/model/quality differs'); raise EvaluationStopped('Unapproved image request')
            row = journal.reserve(run_id, f'image:{item}', {'model': provider._model, 'quality': provider._quality,
                                  'size': fg.IMAGE_SIZE, 'description': description}, 'image')
            journal.issue(row)
            try:
                data = raw_image(provider, description)
                write_once(campaign / (row['id'] + '-response.json'), {'usage': provider.usage, 'image_sha256': hashlib.sha256(data).hexdigest()})
                journal.settle(row, calc_image_cost(provider.cost_key, usage=provider.usage), model=provider._model)
                return data
            except BaseException as exc:
                rows, _ = journal.states()
                if rows[row['id']]['state'] == 'issued':journal.settle(row, None, error=type(exc).__name__)
                journal.halt(type(exc).__name__); raise
        fg.OpenAIImageProvider.generate = audited_image
        fg.build_providers = lambda preferred, quality, image_model=None: [fg.OpenAIImageProvider(quality, image_model or manifest['image']['model'])]

        planner = fg._plan_description
        async def describe(*args, **kwargs):
            token = PHASE.set('viz_image_plan')
            try:
                result = await planner(*args, **kwargs)
                if simulation:result = (result[0]+' Item '+ITEM.get(),result[1])
                key = digest(result[0])
                if key in descriptions and descriptions[key] != ITEM.get():
                    journal.halt('Ambiguous image identity'); raise EvaluationStopped('Ambiguous image identity')
                descriptions[key] = ITEM.get(); return result
            finally:PHASE.reset(token)
        fg._plan_description = describe

        names = {'_run_screening':'screening', '_run_citation':'citation', '_run_visual':'visual',
                 '_run_recipe':'recipe', '_run_deep_dive':'deep_dive', '_run_synthesis':'synthesis',
                 '_plan_visualizations':'viz_planning', '_generate_single_mermaid':'mermaid',
                 '_generate_single_html':'viz_image_plan', '_generate_single_paperbanana':'viz_image_plan'}
        for name, role in names.items():
            original = getattr(ae, name)
            def wrap(fn, label, phase):
                async def measured(*args, **kwargs):
                    token = PHASE.set(phase); item_token = None
                    if label.startswith('_generate_single'):
                        item = args[0] if label == '_generate_single_html' else args[1]
                        item_token = ITEM.set(str(item['id']))
                    span = {'phase': label, 'item': ITEM.get(), 'start': time.time()}; spans.append(span)
                    try:
                        result = await fn(*args, **kwargs)
                        if isinstance(result, dict) and (result.get('error') or ('text' in result and ae._is_error_result(str(result['text'])))):
                            journal.halt('Stage failed: '+label)
                        if label == '_plan_visualizations':
                            write_once(runtime / 'model-proposed-plan.json', result)
                            return paper['items']
                        return result
                    finally:
                        span['end'] = time.time();PHASE.reset(token)
                        if item_token is not None:ITEM.reset(item_token)
                return measured
            setattr(ae, name, wrap(original, name, role))
        if ae._gate_viz_items(paper['items']) != paper['items']:
            raise EvaluationStopped('Product gate changes fixed plan')
        started = time.time()
        try:
            await ae.run_full_analysis(paper['paper_id'], single_attempt=True)
            journal.ready()
            rows = await db.fetch_all('SELECT phase,result,model_used,tokens_in,tokens_out,cost_usd,input_hash FROM analysis_results WHERE paper_id=? ORDER BY id', (paper['paper_id'],))
            write_once(runtime / 'results.json', rows)
            viz = [json.loads(r['result']) for r in rows if r['phase'] == 'visualization']
            complete = bool(viz and len(viz[-1].get('items', [])) == 9 and all(i.get('status') == 'completed' for i in viz[-1]['items']))
            if not complete:
                journal.halt('Fixed workload did not complete')
            write_once(runtime / 'summary.json', {'run_id':run_id,'elapsed_seconds':time.time()-started,'spans':spans,
                       'generation_complete':complete,'execution_verified':False,'scientific_accuracy':'unverified','mode':'simulation' if simulation else 'paid'})
            # The reviewer sees these results and the PDF, without timing/model/cost labels.
            sample = {r['phase']: json.loads(r['result']) for r in rows if r['phase'] not in ('visualization', 'viz_plan')}
            write_once(runtime / 'review-input.json', sample)
            if not complete:raise EvaluationStopped('Generation did not complete')
        finally:
            await db.close_db()
    finally:
        await db.close_db()



def blind_value(value):
    if isinstance(value, list):
        return [blind_value(v) for v in value]
    if isinstance(value, dict):
        hidden = {'model_used','provider','requests','source_evidence','image_path','image_url','duration_s',
                  'image_model','image_quality','scientific_validation','run_token','prior_requests','cost_usd','known_cost_usd','unknown_request_count','tokens_in','tokens_out','interaction_id',
                  'input_hash','run_id','variant','elapsed_seconds'}
        return {k:blind_value(v) for k,v in value.items() if k not in hidden}
    return value


def blind_pair(campaign, paper, manifest_path):
    labels = [uuid.uuid4().hex[:12] for _ in range(2)]
    mapping = {}
    for variant, label in zip(paper['order'], labels):
        runtime = campaign / f"{paper['key']}-{variant}"
        rows = json.loads((runtime / 'results.json').read_text())
        folder = campaign / 'blind' / label
        folder.mkdir(parents=True)
        sample = {}
        for row in rows:
            if row['phase']=='viz_plan':continue
            payload = json.loads(row['result'])
            if row['phase']=='visualization':
                for item in payload.get('items', []):
                    if item.get('image_path'):
                        path = Path(item['image_path']).resolve()
                        if not path.is_relative_to(runtime.resolve()):raise EvaluationStopped('Image outside isolated runtime')
                        shutil.copyfile(path,folder / f"image-{item['id']}.png")
                    if item.get('html_code'):(folder / f"html-{item['id']}.html").write_text(item['html_code'])
            sample[row['phase']] = blind_value(payload)
        write_once(folder / 'analysis.json',sample)
        write_once(folder / 'criteria.json',paper['criteria'])
        mapping[label] = variant
    write_once(campaign / f"{paper['key']}-private-blind-map.json",mapping)
    hashes = {str(p.relative_to(campaign)):file_hash(p) for label in labels for p in (campaign/'blind'/label).iterdir()}
    template = {'passed':False,'reviewer_independent':False,'manifest_sha256':file_hash(manifest_path),
                'artifact_hashes':hashes,'samples':labels,
                'mode':json.loads((runtime/'summary.json').read_text())['mode'],
                'verdicts':{label:{'generation':'unverified','execution':'unverified','source_accuracy':'unverified',
                                'criteria':{c['id']:'unverified' for c in paper['criteria']}} for label in labels}}
    write_once(campaign / f"{paper['key']}-review-template.json",template)


def validate_review(campaign, manifest):
    review=json.loads((campaign/'flow-review.json').read_text())
    template=json.loads((campaign/'flow-review-template.json').read_text())
    if (template.get('mode')!='paid' or not review.get('passed') or not review.get('reviewer_independent')
            or review.get('artifact_hashes')!=template['artifact_hashes']
            or review.get('manifest_sha256')!=template['manifest_sha256']):
        raise EvaluationStopped('Independent review identity or provenance missing')
    verify_files(campaign,review['artifact_hashes'])
    # Only the revised sample must pass. Baseline failures are the comparison target.
    mapping=json.loads((campaign/'flow-private-blind-map.json').read_text())
    candidate=next(label for label,variant in mapping.items() if variant=='candidate')
    verdict=review.get('verdicts',{}).get(candidate,{})
    criteria=next(p['criteria'] for p in manifest['papers'] if p['key']=='flow')
    if (any(verdict.get(k)!='passed' for k in ('generation','execution','source_accuracy'))
            or any(verdict.get('criteria',{}).get(c['id'])!='passed' for c in criteria)):
        raise EvaluationStopped('Candidate critical criteria or independent execution remain unverified')

def execute(manifest_path, campaign, paper_key, approval_path):
    manifest = validate_approval(manifest_path, approval_path, paper_key)
    if not os.environ.get('OPENAI_API_KEY'):
        raise EvaluationStopped('Missing OpenAI credential')
    with campaign_lock(campaign):
        journal = Journal(campaign, manifest);journal.ready()
        binding = campaign / 'binding.json'
        approved = json.loads(Path(approval_path).read_text())
        selected = {'manifest_sha256':file_hash(manifest_path),'approval_sha256':file_hash(approval_path)}
        if binding.exists():
            if json.loads(binding.read_text()) != selected:raise EvaluationStopped('Campaign approval binding changed')
        else:
            write_once(binding, selected)
            with (campaign/'approval.json').open('xb') as handle:
                handle.write(Path(approval_path).read_bytes());handle.flush();os.fsync(handle.fileno())
        if paper_key != 'flow':
            validate_review(campaign, manifest)
        cap = {**manifest, 'budget_usd':min(manifest['budget_usd'],approved['budget_usd']),
               'max_paid_requests':min(manifest['max_paid_requests'],approved['max_paid_requests'])}
        cap = {k:cap[k] for k in ('budget_usd','max_paid_requests')}
        cap['sha256']=digest(cap)
        # Children receive the same approved caps without changing the frozen manifest.
        write_once(campaign / f'{paper_key}-approved-limits.json', cap)
        paper = next(p for p in manifest['papers'] if p['key'] == paper_key)
        for variant in paper['order']:
            subprocess.run([sys.executable, str(Path(__file__).resolve()), '_variant', str(manifest_path),
                            '--campaign', str(campaign.resolve()), '--paper', paper_key, '--variant', variant], check=True)
        blind_pair(campaign,paper,manifest_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['preflight','dry-run','execute','_variant','_simulation'])
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--campaign',type=Path)
    parser.add_argument('--paper',choices=['flow','uplink','survey'],default='flow')
    parser.add_argument('--variant',choices=['baseline','candidate'])
    parser.add_argument('--approval',type=Path)
    args=parser.parse_args()
    if args.command=='preflight':
        preflight(args.manifest);print('Frozen sources, inputs, workload and runner verified')
    elif args.command=='dry-run':
        if not args.campaign:parser.error('--campaign is required')
        manifest=preflight(args.manifest)
        with campaign_lock(args.campaign):
            for paper in manifest['papers']:
                for variant in paper['order']:
                    subprocess.run([sys.executable,str(Path(__file__).resolve()),'_simulation',str(args.manifest.resolve()), '--campaign',str(args.campaign.resolve()),'--paper',paper['key'],'--variant',variant],check=True)
                blind_pair(args.campaign,paper,args.manifest)
        print('Full paired pipeline simulation passed; provider calls: 0')
    elif args.command=='execute':
        if not args.campaign or not args.approval:parser.error('--campaign and --approval are required')
        execute(args.manifest,args.campaign,args.paper,args.approval)
    else:
        if not args.campaign or not args.variant:parser.error('Internal variant arguments missing')
        with campaign_lock(args.campaign,name='.worker.lock'):
            asyncio.run(run_variant(args.manifest,args.campaign,args.paper,args.variant,simulation=args.command=='_simulation'))


if __name__=='__main__':
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    main()
