import os
from pathlib import Path
from unittest.mock import patch

import pytest

from start_server import _is_loopback_host, _validate_network_security


ROOT = Path(__file__).resolve().parents[1]


def test_launchers_use_the_same_python_startup_path() -> None:
    batch = (ROOT / "run_local.bat").read_text(encoding="utf-8")
    powershell = (ROOT / "run_local.ps1").read_text(encoding="utf-8")
    assert 'set "PYTHONPATH=%~dp0;%PYTHONPATH%"' in batch
    assert '$env:PYTHONPATH = "$PSScriptRoot;$env:PYTHONPATH"' in powershell


def test_loopback_hosts_are_recognized() -> None:
    assert _is_loopback_host("127.0.0.1")
    assert _is_loopback_host("::1")
    assert _is_loopback_host("localhost")
    assert not _is_loopback_host("0.0.0.0")


def test_non_loopback_requires_token() -> None:
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(SystemExit):
            _validate_network_security("0.0.0.0")


def test_token_allows_non_loopback() -> None:
    with patch.dict(os.environ, {"PPT_STUDIO_ACCESS_TOKEN": "test-token"}, clear=True):
        _validate_network_security("0.0.0.0")


if __name__ == "__main__":
    test_launchers_use_the_same_python_startup_path()
    test_loopback_hosts_are_recognized()
    test_non_loopback_requires_token()
    test_token_allows_non_loopback()
    print("start server security checks passed")
