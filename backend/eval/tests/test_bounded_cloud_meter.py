import datetime

import pytest

from scripts.bounded_cloud_meter import BoundedCloudMeter, BudgetExhausted
from scripts.evaluate_comprehensive import save, load


def meter(tmp_path):
    path = tmp_path/'budget.json'
    save(path, {'deadline_local': (datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(minutes=1)).isoformat(),
        'sdk_attempts': 94, 'known_input_tokens': 1158276, 'known_output_tokens': 81805,
        'failed_calls_without_complete_usage': 2, 'paid_ocr_pages_new': 0,
        'limits': {'sdk_attempts': 600, 'input_tokens': 2000000,
                   'output_tokens': 300000, 'paid_ocr_pages': 60}})
    return BoundedCloudMeter(path, tmp_path, max_new_attempts=2)


def test_transfer_does_not_reset_attempts_and_reported_tokens(tmp_path):
    m = meter(tmp_path)
    r = m.begin('gemini')
    m.finish(r, 0, usage={'input_tokens': 100, 'output_tokens': 30, 'thinking_tokens': 2})
    saved = load(m.budget_path)
    assert saved['sdk_attempts'] == 95
    assert saved['known_input_tokens'] == 1158376
    assert saved['known_output_tokens'] == 81837
    assert saved['unknown_input_reserve'] == 200000
    assert saved['unknown_output_reserve'] == 65536


def test_failed_unknown_usage_reserves_capacity_and_is_not_zero_cost(tmp_path):
    m = meter(tmp_path)
    r = m.begin('gemini')
    m.finish(r, 0, error=RuntimeError('failure'))
    assert r['input_tokens'] is None
    assert m.budget['failed_calls_without_complete_usage'] == 3
    assert m.unknown_input_reserve == 300000
    assert m.unknown_output_reserve == 98304


def test_attempt_limit_blocks_before_dispatch(tmp_path):
    m = meter(tmp_path)
    for _ in range(2):
        r = m.begin('gemini')
        m.finish(r, 0, usage={'input_tokens': 1, 'output_tokens': 1, 'thinking_tokens': 0})
    with pytest.raises(BudgetExhausted):
        m.begin('gemini')
    assert m.budget['sdk_attempts'] == 96


def test_explicitly_removed_limits_keep_cumulative_accounting(tmp_path):
    m = meter(tmp_path)
    m.budget['deadline_local'] = None
    m.budget['limits'] = {k: None for k in m.budget['limits']}
    m.max_new_attempts = None
    m.budget['known_input_tokens'] = 3000000
    save(m.budget_path,m.budget)
    for _ in range(3):
        r = m.begin('gemini')
        m.finish(r, 0, usage={'input_tokens': 100, 'output_tokens': 30, 'thinking_tokens': 0})
    assert m.budget['sdk_attempts'] == 97
    assert m.budget['known_input_tokens'] == 3000300
    assert m.unknown_input_reserve == 200000


def test_deadline_and_token_envelope_block_without_changing_ledger(tmp_path):
    m = meter(tmp_path)
    m.budget['deadline_local'] = '2020-01-01T00:00:00+00:00'
    save(m.budget_path,m.budget)
    with pytest.raises(BudgetExhausted, match='deadline'):
        m.begin('typhoon')
    assert m.budget['sdk_attempts'] == 94
    m.budget['deadline_local'] = '2100-01-01T00:00:00+00:00'
    m.budget['known_input_tokens'] = 1950000
    save(m.budget_path,m.budget)
    with pytest.raises(BudgetExhausted, match='Token'):
        m.begin('typhoon')
    assert m.budget['sdk_attempts'] == 94


def test_paid_page_limit_is_preserved(tmp_path):
    m = meter(tmp_path)
    m.budget['paid_ocr_pages_new'] = 60
    save(m.budget_path,m.budget)
    with pytest.raises(BudgetExhausted, match='page'):
        m.mark_ocr_page()


def test_disabled_thinking_releases_reserve_but_does_not_fabricate_usage(tmp_path):
    m = meter(tmp_path)
    r = m.begin('gemini', requested_thinking_budget=0)
    m.finish(r, 0, usage={'input_tokens': 10, 'output_tokens': 9})
    assert r['thinking_tokens'] is None
    assert m.unknown_output_reserve == 65536
    r = m.begin('gemini')
    m.finish(r, 0, usage={'input_tokens': 10, 'output_tokens': 9})
    assert m.unknown_output_reserve == 98304


def test_only_dispatched_unique_ocr_pages_consume_page_budget(tmp_path):
    m = meter(tmp_path)
    m.phase = {'stage': 'ingestion', 'ocr_page_key': 'hash:1'}
    for _ in range(2):
        r = m.begin('typhoon')
        m.finish(r, 0, usage={'input_tokens': 1, 'output_tokens': 1, 'thinking_tokens': 0})
    assert m.budget['paid_ocr_pages_new'] == 1
    m.phase['ocr_page_key'] = 'hash:2'
    with pytest.raises(BudgetExhausted):
        m.begin('typhoon')
    assert m.budget['paid_ocr_pages_new'] == 1


def test_interleaved_runs_and_stale_exit_preserve_all_usage_and_pending_reserves(tmp_path):
    first=meter(tmp_path)
    second=BoundedCloudMeter(first.budget_path,tmp_path/'second',max_new_attempts=None)
    a=first.begin('gemini')
    b=second.begin('typhoon')
    second.finish(b,0,usage={'input_tokens':20,'output_tokens':4,'thinking_tokens':0})
    first.finish(a,0,usage={'input_tokens':10,'output_tokens':3,'thinking_tokens':0})
    # These exit snapshots used to silently replace the other run's totals.
    second.persist();first.persist()
    result=load(first.budget_path)
    assert result['sdk_attempts']==96
    assert result['known_input_tokens']==1158306
    assert result['known_output_tokens']==81812
    assert result['unknown_input_reserve']==200000
    assert result['unknown_output_reserve']==65536


def concurrent_worker(path,out):
    m=BoundedCloudMeter(path,out,max_new_attempts=None)
    for i in range(10):
        row=m.begin('synthetic_test')
        if i%5==0:m.finish(row,0,error=RuntimeError('synthetic failure'))
        else:m.finish(row,0,usage={'input_tokens':10,'output_tokens':3,'thinking_tokens':0})
    m.persist()


def test_cross_process_ledger_transactions_do_not_lose_calls_or_unknown_usage(tmp_path):
    import multiprocessing
    m=meter(tmp_path)
    m.budget['deadline_local']=None;m.budget['limits']={k:None for k in m.budget['limits']}
    save(m.budget_path,m.budget)
    ctx=multiprocessing.get_context('spawn')
    workers=[ctx.Process(target=concurrent_worker,args=(m.budget_path,tmp_path/f'worker{i}')) for i in range(6)]
    for worker in workers:worker.start()
    for worker in workers:
        worker.join(30)
        assert worker.exitcode==0
    result=load(m.budget_path)
    assert result['sdk_attempts']==154
    assert result['known_input_tokens']==1158756
    assert result['known_output_tokens']==81949
    assert result['failed_calls_without_complete_usage']==14
    assert result['unknown_input_reserve']==1400000
    assert result['unknown_output_reserve']==458752
