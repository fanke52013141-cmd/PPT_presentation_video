#!/usr/bin/env python3
"""Fail when the Agent contract content changed but AGENT_API_VERSION did not.

契约指纹（contract_hash）随任何契约面内容自动变化，但版本号递增此前纯靠
人工纪律（审查 2026-10-24 G4）。本脚本对比已提交的 contract-snapshot.json
（git HEAD）与当前工作区再生成结果：契约内容变了而版本号没变即失败，
提示开发者按 AGENTS.md 同步策略在同一变更集内 bump AGENT_API_VERSION 并
重新生成快照。

局限说明：CI 在合并后的 main 上运行时 HEAD 已包含本次变更，此门禁主要在
开发者本地 run_checks（提交前）生效——这也是 AGENTS.md 规定的必跑流程。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SNAPSHOT_RELPATH = "docs/agent/contract-snapshot.json"


def _committed_snapshot() -> dict | None:
    try:
        raw = subprocess.run(
            ["git", "show", f"HEAD:{SNAPSHOT_RELPATH}"],
            capture_output=True, text=True, check=True, cwd=REPO_ROOT, encoding="utf-8",
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def main() -> int:
    from agent_contract.versions import AGENT_API_VERSION, get_contract_hash

    head = _committed_snapshot()
    if head is None:
        print("Skipping version discipline check: no committed contract snapshot available.")
        return 0
    current_hash = get_contract_hash()
    if head.get("contract_hash") == current_hash:
        print("Agent contract unchanged; version discipline OK.")
        return 0
    head_version = head.get("agent_api_version")
    if head_version == AGENT_API_VERSION:
        print(
            f"ERROR: Agent contract content changed but AGENT_API_VERSION is still "
            f"{AGENT_API_VERSION}. Bump the version (additive → minor) in "
            f"agent_contract/versions.py and regenerate docs/agent/contract-snapshot.json "
            f"in the same change set (AGENTS.md: Agent Contract Synchronization Policy)."
        )
        return 1
    print(f"Agent contract changed with version bump {head_version} -> {AGENT_API_VERSION}; OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
