"""Partial concurrent RSS/GPU observations; never claim isolated run peaks."""
import datetime
import json
from pathlib import Path
import subprocess
import time
import argparse

import psutil

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--output',type=Path,default=Path('TestFile/evaluation_completion_2026-10-07/resources_observed'))
p.add_argument('--match',default='evaluation_completion_2026-10-07')
a=p.parse_args()
root=a.output
root.mkdir(exist_ok=False)
(root/'scope.json').write_text(json.dumps({'scope':'Partial observations from observer start; concurrent/shared services are not an isolated benchmark',
    'cloud_memory':None,'provider_cost_usd':None,'gpu_scope':'whole device','cpu_time_scope':'process cumulative, not per question'},indent=2),encoding='utf-8')
while not (root/'STOP').exists():
    values=[]
    for process in psutil.process_iter(['pid','name','cmdline','memory_info','cpu_times']):
        try:
            name=(process.info['name'] or '').lower()
            owned=any(a.match in str(part) for part in process.info['cmdline'] or [])
            shared=name in ('postgres.exe','ollama.exe','ollama_llama_server.exe')
            if owned or shared:
                cpu=process.info['cpu_times']
                values.append({'pid':process.pid,'name':process.info['name'],'rss_bytes':process.info['memory_info'].rss,
                    'cpu_seconds':cpu.user+cpu.system,'role':'evaluation' if owned else 'shared_service'})
        except (psutil.Error,TypeError):pass
    gpu=None
    try:
        r=subprocess.run(['nvidia-smi','--query-gpu=index,memory.used,memory.total,utilization.gpu','--format=csv,noheader,nounits'],
            capture_output=True,text=True,timeout=10,creationflags=subprocess.CREATE_NO_WINDOW)
        if r.returncode==0:gpu=r.stdout.strip().splitlines()
    except (OSError,subprocess.SubprocessError):pass
    with (root/'samples.jsonl').open('a',encoding='utf-8') as stream:
        stream.write(json.dumps({'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'processes':values,'device_gpu_csv':gpu})+'\n')
    time.sleep(10)
