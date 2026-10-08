"""Trace failures, retries and task isolation without any external calls."""
import asyncio
from types import SimpleNamespace

import pytest

from backend.services import llm


class Throttle:
    _interval = 0

    async def wait(self):
        pass

    def penalise(self):
        pass

    def relax(self):
        pass


@pytest.fixture
def fake_gemini(monkeypatch):
    monkeypatch.setattr(llm, 'settings', SimpleNamespace(
        LLM_PROVIDER='gemini', GEMINI_MODEL='mock', GEMINI_THINKING_BUDGET=0,
        GEMINI_MAX_RETRIES=2, GEMINI_RETRY_BASE_DELAY=0, AGENT_TEMPERATURE=0))
    monkeypatch.setattr(llm, '_get_throttle', lambda: Throttle())

    def install(fn):
        client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=fn)))
        monkeypatch.setattr(llm, '_get_genai_client', lambda: client)
    return install


def response(usage=True):
    return SimpleNamespace(text=' answer ', usage_metadata=SimpleNamespace(
        prompt_token_count=12, candidates_token_count=3, thoughts_token_count=0) if usage else None)


def test_retry_preserves_unknown_failed_usage_and_success_tokens(fake_gemini):
    class Busy(Exception):
        code = 429
    count = 0

    async def sdk(**kwargs):
        nonlocal count
        count += 1
        if count == 1:
            raise Busy('busy')
        return response()
    fake_gemini(sdk)

    async def run():
        with llm.trace_model_calls() as calls:
            assert await llm.generate('prompt') == 'answer'
        assert llm._model_trace.get() is None
        assert llm._current_model_call.get() is None
        return calls
    calls = asyncio.run(run())
    assert len(calls) == 1
    c = calls[0]
    assert [a['status'] for a in c['attempts']] == ['error', 'success']
    assert c['attempts'][0]['input_tokens'] is None
    assert c['input_tokens'] == c['attempts'][1]['input_tokens'] == 12
    assert all(a['elapsed_seconds'] >= 0 for a in c['attempts'])
    assert c['latency_scope'] == 'generate_including_throttle_and_retry_backoff'


def test_nonretryable_failure_and_missing_usage(fake_gemini):
    async def fail(**kwargs):
        raise ValueError('invalid request')
    fake_gemini(fail)

    async def run():
        with llm.trace_model_calls() as calls:
            assert await llm.generate('bad') == ''
        assert llm._current_model_call.get() is None
        return calls
    c = asyncio.run(run())[0]
    assert c['status'] == 'error'
    assert len(c['attempts']) == 1
    assert c['input_tokens'] is None

    async def no_usage(**kwargs):
        return response(False)
    fake_gemini(no_usage)
    c = asyncio.run(run_success())[0]
    assert c['status'] == 'success'
    assert c['input_tokens'] is None
    assert c['attempts'][0]['input_tokens'] is None


async def run_success():
    with llm.trace_model_calls() as calls:
        await llm.generate('valid')
    return calls


def test_cancel_restores_nested_context_and_records_attempt(fake_gemini):
    async def cancel(**kwargs):
        raise asyncio.CancelledError()
    fake_gemini(cancel)

    async def run():
        sentinel = {'outer': True}
        token = llm._current_model_call.set(sentinel)
        try:
            with llm.trace_model_calls() as outer:
                with llm.trace_model_calls() as inner:
                    with pytest.raises(asyncio.CancelledError):
                        await llm.generate('cancel')
                    assert llm._current_model_call.get() is sentinel
                assert llm._model_trace.get() is outer
            assert not outer
            assert llm._model_trace.get() is None
            return inner
        finally:
            llm._current_model_call.reset(token)
    c = asyncio.run(run())[0]
    assert c['status'] == c['attempts'][0]['status'] == 'cancelled'
    assert c['elapsed_seconds'] >= c['attempts'][0]['elapsed_seconds'] >= 0


def test_concurrent_trace_scopes_do_not_mix_prompts(fake_gemini):
    async def sdk(**kwargs):
        await asyncio.sleep(0)
        return response()
    fake_gemini(sdk)

    async def question(prompt):
        with llm.trace_model_calls() as calls:
            await llm.generate(prompt)
        return calls

    async def run():
        return await asyncio.gather(question('one'), question('two'))
    one, two = asyncio.run(run())
    assert [c['prompt'] for c in one] == ['one']
    assert [c['prompt'] for c in two] == ['two']


def test_json_schema_is_sent_to_the_actual_sdk_and_recorded_in_trace(fake_gemini):
    from backend.services.answer_capture import SCHEMA
    captured = []
    async def sdk(**kwargs):
        captured.append(kwargs['config'])
        return response()
    fake_gemini(sdk)
    async def run():
        with llm.trace_model_calls() as calls:
            await llm.generate('Q', response_mime_type='application/json', response_schema=SCHEMA)
        return calls
    calls = asyncio.run(run())
    assert captured[0].response_mime_type == 'application/json'
    assert captured[0].response_schema is not None
    assert calls[0]['response_schema'] == SCHEMA


def test_sdk_latency_excludes_retry_backoff(fake_gemini, monkeypatch):
    now = [0.0]
    monkeypatch.setattr(llm.time, 'perf_counter', lambda: now[0])

    async def sleep(delay):
        now[0] += 10
    monkeypatch.setattr(llm.asyncio, 'sleep', sleep)
    count = 0

    async def sdk(**kwargs):
        nonlocal count
        count += 1
        now[0] += 2
        if count == 1:
            raise RuntimeError('429')
        return response()
    fake_gemini(sdk)
    c = asyncio.run(run_success())[0]
    assert [a['elapsed_seconds'] for a in c['attempts']] == [2, 2]
    assert c['elapsed_seconds'] == 14
