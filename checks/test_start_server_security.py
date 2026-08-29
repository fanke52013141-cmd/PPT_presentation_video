import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from network_guard import is_loopback_host, validate_network_security


ROOT = Path(__file__).resolve().parents[1]


def test_launchers_use_the_same_python_startup_path() -> None:
    batch = (ROOT / "run_local.bat").read_text(encoding="utf-8")
    powershell = (ROOT / "run_local.ps1").read_text(encoding="utf-8")
    assert 'set "PYTHONPATH=%~dp0;%PYTHONPATH%"' in batch
    assert '$env:PYTHONPATH = "$PSScriptRoot;$env:PYTHONPATH"' in powershell


def test_loopback_hosts_are_recognized() -> None:
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("::1")
    assert is_loopback_host("localhost")
    assert not is_loopback_host("0.0.0.0")


def test_non_loopback_requires_token() -> None:
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(SystemExit):
            validate_network_security("0.0.0.0")


def test_token_allows_non_loopback() -> None:
    with patch.dict(os.environ, {"PPT_STUDIO_ACCESS_TOKEN": "test-token"}, clear=True):
        validate_network_security("0.0.0.0")


def test_start_server_import_does_not_load_composition_root() -> None:
    """守护（审查 M-04）：导入启动器不得触发 server 组合根副作用。"""
    code = (
        "import sys; import start_server; "
        "assert 'server' not in sys.modules, "
        "'start_server must not import server at module import time'"
    )
    subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        cwd=str(ROOT),
    )


def test_start_server_source_has_no_top_level_server_import() -> None:
    source = (ROOT / "start_server.py").read_text(encoding="utf-8")
    top_level = "\n".join(
        line for line in source.splitlines()
        if not line.startswith((" ", "\t"))
    )
    assert "from server import" not in top_level
    assert "import server" not in top_level


if __name__ == "__main__":
    test_launchers_use_the_same_python_startup_path()
    test_loopback_hosts_are_recognized()
    test_non_loopback_requires_token()
    test_token_allows_non_loopback()
    test_start_server_import_does_not_load_composition_root()
    test_start_server_source_has_no_top_level_server_import()
    print("start server security checks passed")
