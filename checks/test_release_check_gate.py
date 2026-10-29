"""Release acceptance must fail before running the full suite on incomplete coverage."""

import subprocess

import pytest

from scripts import run_checks


def test_incomplete_release_never_reaches_full_checks(monkeypatch):
    monkeypatch.setattr("sys.argv", ["run_checks.py", "--level", "full", "--require-complete"])
    calls = []

    def reject(command):
        calls.append(command)
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(run_checks, "run", reject)
    monkeypatch.setattr(run_checks, "full_checks", lambda: pytest.fail("release gate bypassed"))
    with pytest.raises(subprocess.CalledProcessError):
        run_checks.main()
    assert calls == [[run_checks.sys.executable, "scripts/check_agent_coverage.py", "--require-complete"]]


def test_complete_release_runs_full_checks_after_gate(monkeypatch):
    monkeypatch.setattr("sys.argv", ["run_checks.py", "--level", "full", "--require-complete"])
    calls = []
    monkeypatch.setattr(run_checks, "run", lambda command: calls.append("coverage"))
    monkeypatch.setattr(run_checks, "full_checks", lambda: calls.append("full"))
    assert run_checks.main() == 0
    assert calls == ["coverage", "full"]


def test_quick_cannot_claim_release_acceptance(monkeypatch):
    monkeypatch.setattr("sys.argv", ["run_checks.py", "--require-complete"])
    monkeypatch.setattr(run_checks, "quick_checks", lambda: pytest.fail("invalid flags ran checks"))
    with pytest.raises(SystemExit) as error:
        run_checks.main()
    assert error.value.code == 2
