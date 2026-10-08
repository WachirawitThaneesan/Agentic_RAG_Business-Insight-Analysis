from pathlib import Path
from scripts.evaluate_comprehensive import save,load


def test_windows_replace_lock_retries_without_losing_old_checkpoint(tmp_path,monkeypatch):
    path=tmp_path/'checkpoint.json';save(path,{'completed':1})
    original=Path.replace;attempts=[]
    def transient_lock(source,target):
        attempts.append(1)
        if len(attempts)<3:
            assert load(path)=={'completed':1}
            raise PermissionError('temporary Windows reader lock')
        return original(source,target)
    monkeypatch.setattr(Path,'replace',transient_lock)
    monkeypatch.setattr('scripts.evaluate_comprehensive.time.sleep',lambda _:None)
    save(path,{'completed':2})
    assert load(path)=={'completed':2}
    assert len(attempts)==3
