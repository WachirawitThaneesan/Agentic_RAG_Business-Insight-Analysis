"""Evaluation-only ledger for Gemini sync/async and Typhoon HTTP attempts.

Wraps actual SDK dispatches, never logs credentials or image payloads. Missing
usage remains unknown and conservatively reserves capacity for subsequent calls.
"""
import datetime
import threading
import time
import json
import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import httpx

from scripts.evaluate_comprehensive import load, save


class BudgetExhausted(RuntimeError):
    pass


class BoundedCloudMeter:
    def __init__(self, budget_path, output, *, max_new_attempts=30):
        self.budget_path = Path(budget_path)
        self.output = Path(output)
        self.lock = threading.Lock()
        with self.ledger_lock():
            self.budget = load(self.budget_path)
        self.initial = dict(self.budget)
        self.calls = []
        self.max_new_attempts = max_new_attempts
        self.phase = {'stage': 'setup'}
        self.unknown_input_reserve = self.budget.get('unknown_input_reserve',
            self.budget['failed_calls_without_complete_usage'] * 100000)
        self.unknown_output_reserve = self.budget.get('unknown_output_reserve',
            self.budget['failed_calls_without_complete_usage'] * 32768)

    @contextmanager
    def ledger_lock(self):
        """Short cross-process transaction; never hold it during an SDK call."""
        path=self.budget_path.with_suffix(self.budget_path.suffix+'.lock')
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('a+b') as f:
            if f.tell()==0:f.write(b'0');f.flush()
            deadline=time.monotonic()+30
            while True:
                try:
                    f.seek(0)
                    if os.name=='nt':
                        import msvcrt
                        msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
                    else:
                        import fcntl
                        fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic()>=deadline:raise RuntimeError('Resource ledger transaction busy')
                    time.sleep(.05)
            try:yield
            finally:
                f.seek(0)
                if os.name=='nt':msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
                else:fcntl.flock(f,fcntl.LOCK_UN)

    def refresh(self):
        self.budget=load(self.budget_path)
        self.unknown_input_reserve=self.budget.get('unknown_input_reserve',self.budget['failed_calls_without_complete_usage']*100000)
        self.unknown_output_reserve=self.budget.get('unknown_output_reserve',self.budget['failed_calls_without_complete_usage']*32768)

    def _persist_locked(self):
        self.budget['updated_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.budget['unknown_input_reserve'] = self.unknown_input_reserve
        self.budget['unknown_output_reserve'] = self.unknown_output_reserve
        temporary=self.budget_path.with_suffix(self.budget_path.suffix+f'.{os.getpid()}.tmp')
        with temporary.open('w',encoding='utf-8') as stream:
            stream.write(json.dumps(self.budget,ensure_ascii=False,indent=2)+'\n')
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(20):
            try:os.replace(temporary,self.budget_path);break
            except PermissionError:
                if attempt==19:raise
                time.sleep(.05)
        save(self.output/'model_calls.json', self.calls)
        save(self.output/'budget_checkpoint.json', self.budget)

    def persist(self):
        # Enter/exit snapshots must not overwrite another run's completed calls.
        with self.lock,self.ledger_lock():
            self.refresh()
            self._persist_locked()

    def check_capacity(self):
        """Honor explicitly removed limits while keeping complete accounting."""
        deadline = self.budget.get('deadline_local')
        if deadline and datetime.datetime.now(datetime.timezone.utc) >= datetime.datetime.fromisoformat(deadline):
            raise BudgetExhausted('Original experiment deadline reached')
        lim = self.budget['limits']
        if (self.max_new_attempts is not None and len(self.calls) >= self.max_new_attempts
            or lim.get('sdk_attempts') is not None and self.budget['sdk_attempts'] >= lim['sdk_attempts']):
            raise BudgetExhausted('Attempt budget reached')
        if (lim.get('input_tokens') is not None and
                self.budget['known_input_tokens'] + self.unknown_input_reserve + 100000 > lim['input_tokens']
            or lim.get('output_tokens') is not None and
                self.budget['known_output_tokens'] + self.unknown_output_reserve + 32768 > lim['output_tokens']):
            raise BudgetExhausted('Token budget including unknown usage reserve reached')

    def begin(self, provider, *, requested_thinking_budget=None):
        with self.lock,self.ledger_lock():
            self.refresh()
            self.check_capacity()
            lim = self.budget['limits']
            page_key = self.phase.get('ocr_page_key') if self.phase.get('stage') == 'ingestion' else None
            keys = self.budget.setdefault('paid_ocr_page_keys', [])
            new_page = page_key and page_key not in keys
            if new_page and lim.get('paid_ocr_pages') is not None and self.budget['paid_ocr_pages_new'] >= lim['paid_ocr_pages']:
                raise BudgetExhausted('Paid physical OCR page budget reached')
            row = {**self.phase, 'provider': provider, 'attempt_index': len(self.calls)+1,
                   'status': 'pending', 'input_tokens': None, 'output_tokens': None,
                   'thinking_tokens': None, 'latency_scope': 'sdk_or_http_dispatch',
                   'requested_thinking_budget': requested_thinking_budget}
            self.calls.append(row)
            if new_page:
                keys.append(page_key)
                self.budget['paid_ocr_pages_new'] += 1
            self.budget['sdk_attempts'] += 1
            self.unknown_input_reserve += 100000
            self.unknown_output_reserve += 32768
            self._persist_locked()
            return row

    def finish(self, row, start, *, usage=None, error=None):
        with self.lock,self.ledger_lock():
            self.refresh()
            row['seconds'] = time.perf_counter()-start
            row['status'] = 'error' if error else 'success'
            if error:
                row['error_type'] = type(error).__name__
                row['error_code'] = getattr(error, 'code', None)
            for key in ('input_tokens', 'output_tokens', 'thinking_tokens'):
                v = (usage or {}).get(key)
                row[key] = v if type(v) is int and v >= 0 else None
            if row['input_tokens'] is not None:
                self.unknown_input_reserve -= 100000
                self.budget['known_input_tokens'] += row['input_tokens']
            if row['output_tokens'] is not None and (row['thinking_tokens'] is not None or
                                                     row.get('requested_thinking_budget') == 0):
                self.unknown_output_reserve -= 32768
                if row['thinking_tokens'] is None:
                    row['unreported_thinking_reservation_basis'] = 'Explicit request thinking_budget=0;usage remains null'
            self.budget['known_output_tokens'] += (row['output_tokens'] or 0) + (row['thinking_tokens'] or 0)
            if row['input_tokens'] is None or row['output_tokens'] is None:
                key = 'failed_calls_without_complete_usage' if error else 'successful_calls_without_complete_usage'
                self.budget[key] = self.budget.get(key, 0) + 1
            self._persist_locked()

    def mark_ocr_page(self):
        with self.lock,self.ledger_lock():
            self.refresh()
            if self.budget['limits'].get('paid_ocr_pages') is not None and self.budget['paid_ocr_pages_new'] >= self.budget['limits']['paid_ocr_pages']:
                raise BudgetExhausted('Paid physical OCR page budget reached')
            self.budget['paid_ocr_pages_new'] += 1
            self._persist_locked()

    @staticmethod
    def gemini_usage(response):
        u = getattr(response, 'usage_metadata', None)
        return {'input_tokens': getattr(u, 'prompt_token_count', None),
                'output_tokens': getattr(u, 'candidates_token_count', None),
                'thinking_tokens': getattr(u, 'thoughts_token_count', None)}

    def __enter__(self):
        from backend.services import llm
        from backend.config import get_settings
        self.original_client = llm._get_genai_client
        self.original_post = httpx.AsyncClient.post
        host = urlparse(get_settings().TYPHOON_OCR_ENDPOINT).hostname
        cached = None

        def client():
            nonlocal cached
            if cached is not None:
                return cached
            raw = self.original_client()
            def thinking_budget(kwargs):
                config = kwargs.get('config')
                thinking = getattr(config, 'thinking_config', None)
                return getattr(thinking, 'thinking_budget', None)

            async def async_generate(**kwargs):
                row = self.begin('gemini', requested_thinking_budget=thinking_budget(kwargs)); start = time.perf_counter()
                try:
                    response = await raw.aio.models.generate_content(**kwargs)
                except BaseException as exc:
                    self.finish(row, start, error=exc)
                    raise
                self.finish(row, start, usage=self.gemini_usage(response))
                return response

            def sync_generate(**kwargs):
                row = self.begin('gemini', requested_thinking_budget=thinking_budget(kwargs)); start = time.perf_counter()
                try:
                    response = raw.models.generate_content(**kwargs)
                except BaseException as exc:
                    self.finish(row, start, error=exc)
                    raise
                self.finish(row, start, usage=self.gemini_usage(response))
                return response
            cached = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=async_generate)),
                                     models=SimpleNamespace(generate_content=sync_generate))
            return cached

        async def post(client_self, url, **kwargs):
            if client_self.base_url.host != host or str(url) != '/chat/completions':
                return await self.original_post(client_self, url, **kwargs)
            row = self.begin('typhoon'); start = time.perf_counter()
            try:
                response = await self.original_post(client_self, url, **kwargs)
                response.raise_for_status()
                u = response.json().get('usage') or {}
            except BaseException as exc:
                self.finish(row, start, error=exc)
                raise
            self.finish(row, start, usage={'input_tokens': u.get('prompt_tokens'),
                'output_tokens': u.get('completion_tokens'), 'thinking_tokens': 0})
            return response
        llm._get_genai_client = client
        httpx.AsyncClient.post = post
        self.persist()
        return self

    def __exit__(self, *_args):
        from backend.services import llm
        llm._get_genai_client = self.original_client
        httpx.AsyncClient.post = self.original_post
        self.persist()
