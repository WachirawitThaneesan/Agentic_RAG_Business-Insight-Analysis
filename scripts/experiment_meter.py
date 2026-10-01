"""Record SDK attempts and local process resources without saving credentials."""
from __future__ import annotations
import json
import threading
import time
from types import SimpleNamespace
import psutil


class ExperimentMeter:
    def __init__(self, output):
        self.output = output
        self.phase = {'arm': 'setup', 'id': None}
        self.calls = []
        self.samples = []
        self.stop = threading.Event()

    def save(self, name, value):
        path = self.output / name
        tmp = path.with_suffix(path.suffix + '.part')
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        tmp.replace(path)

    def start(self):
        import backend.services.llm as llm
        self.original = llm._get_genai_client
        cached = None
        def client():
            nonlocal cached
            if cached is not None:
                return cached
            raw = self.original()
            async def measured(**kwargs):
                row = {**self.phase, 'model': kwargs.get('model'), 'started_at': time.time()}
                self.calls.append(row)
                start = time.perf_counter()
                try:
                    response = await raw.aio.models.generate_content(**kwargs)
                    row['status'] = 'success'
                    usage = getattr(response, 'usage_metadata', None)
                    row['usage'] = {k: getattr(usage, k, None) for k in
                                    ('prompt_token_count', 'candidates_token_count', 'thoughts_token_count')}
                    return response
                except Exception as exc:
                    row.update(status='error', error_type=type(exc).__name__, status_code=getattr(exc, 'code', None))
                    raise
                finally:
                    row['seconds'] = time.perf_counter() - start
                    self.save('model_calls.json', self.calls)
            cached = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=measured)))
            return cached
        llm._get_genai_client = client
        self.started = time.perf_counter()
        self.thread = threading.Thread(target=self._sample, daemon=True)
        self.thread.start()

    def _sample(self):
        while not self.stop.is_set():
            row = {'timestamp': time.time(), **self.phase}
            groups = {'runner': [psutil.Process()] + psutil.Process().children(recursive=True),
                      'ollama': [p for p in psutil.process_iter(['name']) if 'ollama' in (p.info['name'] or '').lower()]}
            for name, processes in groups.items():
                rss = cpu = 0
                for proc in processes:
                    try:
                        rss += proc.memory_info().rss
                        t = proc.cpu_times(); cpu += t.user + t.system
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                row[name + '_rss_mib'] = rss / 2**20
                row[name + '_cpu_seconds'] = cpu
            self.samples.append(row)
            self.stop.wait(1)

    def finish(self):
        import backend.services.llm as llm
        llm._get_genai_client = self.original
        self.stop.set(); self.thread.join(3)
        self.save('resources.json', {'total_seconds': time.perf_counter()-self.started,
                  'runner_peak_rss_mib': max((r['runner_rss_mib'] for r in self.samples), default=0),
                  'ollama_peak_rss_mib': max((r['ollama_rss_mib'] for r in self.samples), default=0),
                  'samples': self.samples,
                  'scope': 'host processes only; no cloud inference resources or SDK-internal retries'})
