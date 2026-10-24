"""Agent dispatch/registry hygiene regression tests (review 2026-10-24 P2-1).

dispatch.HANDLERS 是字典字面量：重复键会被 Python 静默覆盖（历史上
connections.get 曾重复注册两次，值恰好相同而未爆雷，但后续单改一行就会
引入双通道分叉且无报警）。本文件用 AST 锁定字面量层的不变量。
"""

from __future__ import annotations

import ast
from pathlib import Path

from agent_contract.capabilities import CAPABILITIES, CapabilityStatus
from agent_contract.discovery import response_kind

REPO_ROOT = Path(__file__).resolve().parents[2]
DISPATCH_SOURCE = (REPO_ROOT / "agent_api" / "dispatch.py").read_text(encoding="utf-8")


def _literal_keys() -> list[str]:
    tree = ast.parse(DISPATCH_SOURCE)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "HANDLERS"
            for target in node.targets
        ):
            assert isinstance(node.value, ast.Dict)
            return [ast.literal_eval(key) for key in node.value.keys]
    raise AssertionError("HANDLERS literal not found in agent_api/dispatch.py")


def test_handlers_literal_has_no_duplicate_keys():
    keys = _literal_keys()
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    assert duplicates == [], f"duplicate HANDLERS keys (silently overwritten at runtime): {duplicates}"


def test_every_handler_key_is_a_registered_capability():
    from agent_api.dispatch import HANDLERS

    known = {cap.id for cap in CAPABILITIES}
    unknown = sorted(set(HANDLERS) - known)
    assert unknown == [], f"HANDLERS references unknown capabilities: {unknown}"


def test_every_invocable_capability_has_a_handler():
    """JSON 能力承诺可 invoke（invocable=true），缺 handler 会在调用时变成
    UNSUPPORTED_TRANSPORT 422——这属于注册表内部矛盾，必须在测试期发现。"""
    from agent_api.dispatch import HANDLERS

    invocable = {
        cap.id for cap in CAPABILITIES
        if cap.status != CapabilityStatus.removed and response_kind(cap) == "json"
    }
    missing = sorted(invocable - set(HANDLERS))
    assert missing == [], f"invocable capabilities without a registered handler: {missing}"
