"""Budget, duplicate issuance, timeout and immutable input gates."""
from decimal import Decimal
import json
from pathlib import Path
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from tools.quality_compare import EvaluationStopped, Journal, campaign_lock, verify_files, file_hash, write_once


@pytest.fixture
def journal(tmp_path):
    return Journal(tmp_path, {'max_paid_requests':4,'max_requests_per_run':3,'budget_usd':1,'budget_per_run_usd':1,
                             'reservations_usd':{'text':'0.30','image':'0.60'}})


def settle(journal,key='a',cost='0.1'):
    row=journal.reserve('run',key,{'model':'mock'},'text');journal.issue(row);journal.settle(row,cost);return row


def test_settlement_and_duplicate_stage_without_payload_replay(journal):
    row=settle(journal)
    assert journal.states()[0][row['id']]['cost_usd']=='0.1'
    with pytest.raises(EvaluationStopped,match='Duplicate'):
        journal.reserve('run','a',{'different':'retry'},'text')
    journal.ready()


def test_concurrent_reservations_account_for_each_other(journal):
    barrier=threading.Barrier(2)
    def reserve(key):
        barrier.wait()
        try:return journal.reserve('run',key,{},'image')['id']
        except EvaluationStopped:return 'blocked'
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(reserve,['a','b']))
    assert results.count('blocked')==1
    assert len(journal.states()[0])==1


@pytest.mark.parametrize('state',['reserved','issued','unsettled'])
def test_interruption_blocks_fresh_owner_and_reissue(journal,state):
    row=journal.reserve('run','a',{},'text')
    if state!='reserved':journal.issue(row)
    if state=='unsettled':journal.settle(row,None,error='TimeoutError')
    other=Journal(journal.directory,journal.manifest)
    with pytest.raises(EvaluationStopped):other.ready()
    with pytest.raises(EvaluationStopped):other.reserve('new','b',{},'text')


def test_unknown_cost_stops_already_reserved_sibling(journal):
    a=journal.reserve('run','a',{},'text');b=journal.reserve('run','b',{},'text')
    journal.issue(a);journal.settle(a,None)
    with pytest.raises(EvaluationStopped):journal.issue(b)
    assert journal.states()[0][b['id']]['state']=='reserved'


def test_late_sibling_usage_is_preserved_after_halt(journal):
    a=journal.reserve('run','a',{},'text');b=journal.reserve('run','b',{},'text')
    journal.issue(a);journal.issue(b);journal.settle(a,None);journal.settle(b,'0.04')
    assert journal.states()[0][b['id']]['cost_usd']=='0.04'
    with pytest.raises(EvaluationStopped):journal.ready()


@pytest.mark.parametrize('cost',[None,'NaN','Infinity','-1','0.31'])
def test_unknown_or_over_reservation_cost_never_allows_next_call(journal,cost):
    settle(journal,cost=cost)
    with pytest.raises(EvaluationStopped):journal.reserve('run','next',{},'text')


def test_run_and_global_call_caps(journal):
    for key in ['a','b','c']:settle(journal,key,cost='0.01')
    with pytest.raises(EvaluationStopped,match='count cap'):journal.reserve('run','d',{},'text')
    row=journal.reserve('new','a',{},'text');journal.issue(row);journal.settle(row,'0.01')
    with pytest.raises(EvaluationStopped,match='count cap'):journal.reserve('new','b',{},'text')


def test_no_issue_before_reservation_or_double_settlement(journal):
    row=settle(journal)
    with pytest.raises(EvaluationStopped):journal.issue(row)
    with pytest.raises(EvaluationStopped):journal.settle(row,'0.1')


def test_source_hash_drift_and_symlink_are_rejected(tmp_path):
    p=tmp_path/'source.py';p.write_text('source')
    hashes={'source.py':file_hash(p)};verify_files(tmp_path,hashes)
    p.write_text('changed')
    with pytest.raises(EvaluationStopped):verify_files(tmp_path,hashes)
    link=tmp_path/'link.py';link.symlink_to(p)
    with pytest.raises(EvaluationStopped):verify_files(tmp_path,{'link.py':file_hash(p)})


def test_audit_artifacts_are_never_replaced(tmp_path):
    p=tmp_path/'artifact.json';write_once(p,{'old':1})
    with pytest.raises(FileExistsError):write_once(p,{'new':1})
    assert json.loads(p.read_text())=={'old':1}


def test_same_campaign_process_lock_blocks_second_executor(tmp_path):
    with campaign_lock(tmp_path):
        with pytest.raises(EvaluationStopped):
            with campaign_lock(tmp_path):pass


def test_blind_review_hides_execution_metadata_but_keeps_scientific_values():
    from tools.quality_compare import blind_value
    result=blind_value({'value':2.99,'model_used':'gpt-6-luna','cost_usd':0.3,
                        'parameters':[{'name':'sigma','value':0.1}], 'requests':[{'model':'gpt-6-luna'}]})
    assert result=={'value':2.99,'parameters':[{'name':'sigma','value':0.1}]}


def test_parent_lock_and_one_worker_lock_can_coexist(tmp_path):
    with campaign_lock(tmp_path):
        with campaign_lock(tmp_path,name='.worker.lock'):
            with pytest.raises(EvaluationStopped):
                with campaign_lock(tmp_path,name='.worker.lock'):pass


def test_paid_and_simulated_journals_cannot_be_mixed(journal):
    journal.manifest['mode']='simulation';settle(journal)
    paid=Journal(journal.directory,{**journal.manifest,'mode':'paid'})
    with pytest.raises(EvaluationStopped):paid.ready()
    with pytest.raises(EvaluationStopped):paid.reserve('new','b',{},'text')
