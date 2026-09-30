"""Offline mode rejects cloud paths and keeps private files local."""

import subprocess
import sys
import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from backend.config import Settings


def test_offline_settings_select_local_providers_and_private_storage(tmp_path):
    settings = Settings(
        OFFLINE_MODE=True, PRIVATE_DATA_DIR=str(tmp_path),
        LLM_PROVIDER="gemini", PDF_TABLE_OCR_PROVIDER="gemini",
        TAVILY_API_KEY="configured-but-disabled",
        OLLAMA_HOST="http://127.0.0.1:11434",
    )
    assert settings.LLM_PROVIDER == "ollama"
    assert settings.OLLAMA_LLM_MODEL == settings.OFFLINE_LLM_MODEL
    assert settings.PDF_OCR_PROVIDER == "docling"
    assert settings.PDF_TABLE_OCR_PROVIDER == "docling"
    assert settings.TAVILY_API_KEY == ""
    assert settings.DUCKDB_PATH == str(tmp_path / "warehouse.duckdb")
    assert settings.APP_HOST == "127.0.0.1"


def test_offline_settings_reject_nonlocal_ollama(tmp_path):
    with pytest.raises(ValueError, match="localhost OLLAMA_HOST"):
        Settings(OFFLINE_MODE=True, PRIVATE_DATA_DIR=str(tmp_path),
                 OLLAMA_HOST="https://example.org")


def test_socket_guard_blocks_external_dns_and_allows_localhost():
    script = """
import socket
from backend.services.offline_network import install_offline_network_guard
install_offline_network_guard()
assert socket.getaddrinfo('localhost', 11434)
try:
    socket.getaddrinfo('example.org', 443)
except OSError as exc:
    assert 'OFFLINE_MODE blocked' in str(exc)
else:
    raise AssertionError('external DNS unexpectedly allowed')
try:
    with socket.socket() as sock:
        sock.connect(('1.1.1.1', 443))
except OSError as exc:
    assert 'OFFLINE_MODE blocked' in str(exc)
else:
    raise AssertionError('external IP unexpectedly allowed')
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_docling_worker_installs_network_guard_before_model_imports():
    script = """
import socket
import backend.services.local_ocr_worker
try:
    socket.getaddrinfo('example.org', 443)
except OSError as exc:
    assert 'OFFLINE_MODE blocked' in str(exc)
else:
    raise AssertionError('Docling worker allowed external DNS')
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_offline_graph_endpoint_is_disabled():
    from backend.routes.graph import require_graph_mode

    with patch("backend.routes.graph.get_settings", return_value=SimpleNamespace(OFFLINE_MODE=True)):
        with pytest.raises(HTTPException) as exc:
            require_graph_mode()
    assert exc.value.status_code == 403


def test_offline_cloud_evaluation_is_disabled():
    from backend.services.evaluation import run_evaluation

    with patch("backend.services.evaluation.settings.OFFLINE_MODE", True):
        with pytest.raises(RuntimeError, match="disabled in OFFLINE_MODE"):
            asyncio.run(run_evaluation([]))
