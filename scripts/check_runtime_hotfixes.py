#!/usr/bin/env python3
"""Verify that former runtime hotfixes now live in normal source code."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class Project:
    id = "source-check"
    name = "Source check"
    description = ""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = str(run_dir)


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    try:
        assert_true(not (ROOT / "sitecustomize.py").exists(), "sitecustomize.py must stay retired")
        print("PASS Python startup no longer auto-patches subprocess or server functions")

        import server

        assert_true(
            not getattr(subprocess.run, "__ppt_pipeline_runtime_hotfix__", False),
            "subprocess.run is still monkey-patched",
        )
        with patch.object(
            server.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["demo"], 3, stderr="busy"),
        ):
            result = server.run_subprocess_bounded(["demo"], timeout_sec=3)
        assert_true(result.returncode == 124, "bounded subprocess timeout was not normalized")
        print("PASS bounded subprocess execution is source-owned")

        malformed = subprocess.CompletedProcess([], 0, "not-json", "")
        parsed = server.parse_json_process_stdout(malformed)
        assert_true("parse_warning" in parsed, "malformed validator JSON was not made safe")
        print("PASS validator JSON parsing is source-owned")

        with tempfile.TemporaryDirectory() as value:
            run_dir = Path(value)
            planning = run_dir / "planning"
            planning.mkdir()
            (planning / "visual_contract.json").write_text(
                json.dumps(
                    {
                        "slides": [
                            {
                                "slide_id": "slide_001",
                                "visual_groups": [{"id": "group_1"}],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "reveal_manifest.json").write_text(
                json.dumps({"slides": []}),
                encoding="utf-8",
            )
            changed = server.sync_reveal_manifest_to_contract(
                Project(run_dir),
                ["slide_001"],
            )
            manifest = json.loads(
                (run_dir / "reveal_manifest.json").read_text(encoding="utf-8")
            )
            assert_true(changed, "manifest reconciliation reported no change")
            assert_true(
                manifest["slides"][0]["groups"][0]["id"] == "group_1",
                "manifest groups were not reconstructed from the contract",
            )
        print("PASS Reveal Manifest reconciliation is source-owned")

        import scripts.check_source_registration_contract as registration_check

        registration_check.main()
        print("PASS explicit route registration contract is enforced")
    except Exception as exc:
        print(f"FAIL {type(exc).__name__}: {exc}")
        return 1

    print("OK source safeguard self-check passed (5 checks).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
