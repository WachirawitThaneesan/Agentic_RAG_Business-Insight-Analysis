from scripts.audit_capture_run import cached_input_path
from scripts.evaluate_comprehensive import save, sha


def test_reuse_requires_the_hash_of_the_original_parent_output(tmp_path):
    parent = tmp_path/'parent'/'judge_outputs'/'row.json'
    original_input = tmp_path/'parent'/'judge_inputs'/'row.json'
    child = tmp_path/'child'/'judge_outputs'/'row.json'
    save(parent, {'judgment': {'original': True}})
    save(original_input, {'actual_answer': 'unchanged'})
    save(child, {'reused_from': str(parent), 'parent_sha256': sha(parent)})
    assert cached_input_path(child) == original_input
    save(parent, {'judgment': {'original': False}})
    assert cached_input_path(child) is None


def test_missing_or_unverified_ancestor_is_not_a_valid_input_cache(tmp_path):
    child = tmp_path/'child'/'judge_outputs'/'row.json'
    save(child, {'reused_from': str(tmp_path/'missing.json'), 'parent_sha256': '0'*64})
    assert cached_input_path(child) is None
    save(child, {'judgment': {'exists': True}})
    assert cached_input_path(child) is None
