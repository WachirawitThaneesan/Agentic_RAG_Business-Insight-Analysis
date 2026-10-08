"""Record SDK attempts and local process resources without saving credentials."""
from __future__ import annotations
import json
import threading
import time
import shutil
import subprocess
from types import SimpleNamespace
import psutil


class ExperimentMeter:
    def __init__(self, output, *, capture_context=False):
        self.output = output
        self.capture_context = capture_context
        self.generation_trace = []
        self.phase = {'arm': 'setup', 'id': None}
        self.calls = []
        self.samples = []
        self.stop = threading.Event()
        self.gpu_tool = shutil.which('nvidia-smi')

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
                row = {**self.phase, 'model': kwargs.get('model'), 'started_at': time.time(), 'status': 'pending'}
                self.calls.append(row)
                self.save('model_calls.json', self.calls)
                start = time.perf_counter()
                try:
                    response = await raw.aio.models.generate_content(**kwargs)
                    row['status'] = 'success'
                    usage = getattr(response, 'usage_metadata', None)
                    row['usage'] = {k: getattr(usage, k, None) for k in
                                    ('prompt_token_count', 'candidates_token_count', 'thoughts_token_count')}
                    if self.capture_context:
                        self.generation_trace.append({
                            **row, 'prompt': kwargs.get('contents'),
                            'response': response.text or '',
                        })
                        self.save('generation_trace.json', self.generation_trace)
                    return response
                except BaseException as exc:
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
            if self.gpu_tool:
                try:
                    gpu = subprocess.run([self.gpu_tool,
                        '--query-gpu=memory.used,utilization.gpu', '--format=csv,noheader,nounits'],
                        capture_output=True, text=True, timeout=2,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    if gpu.returncode == 0:
                        values = [line.split(',') for line in gpu.stdout.strip().splitlines()]
                        row['gpu_total_used_mib'] = sum(float(v[0]) for v in values)
                        row['gpu_utilization_percent'] = max(float(v[1]) for v in values)
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    pass
            self.samples.append(row)
            self.stop.wait(1)

    def finish(self):
        import backend.services.llm as llm
        llm._get_genai_client = self.original
        self.stop.set(); self.thread.join(3)
        self.save('resources.json', {'total_seconds': time.perf_counter()-self.started,
                  'runner_peak_rss_mib': max((r['runner_rss_mib'] for r in self.samples), default=0),
                  'ollama_peak_rss_mib': max((r['ollama_rss_mib'] for r in self.samples), default=0),
                  'gpu_peak_total_used_mib': max((r['gpu_total_used_mib'] for r in self.samples
                      if 'gpu_total_used_mib' in r), default=None),
                  'samples': self.samples,
                  'scope': 'RSS sampled host processes only, possible shared-page double count; GPU total device usage includes other apps. No cloud inference resources or SDK-internal retries.'})
