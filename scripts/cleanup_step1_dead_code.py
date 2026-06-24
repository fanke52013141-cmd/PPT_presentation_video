#!/usr/bin/env python3
"""Safely remove the unreachable legacy Step 1 LLM ingestion block from server.py.

Why this script exists:
- The runtime tooling cannot safely replace the large ``server.py`` file in one
  operation.
- Step 1 currently writes a local ``article_brief.json`` and returns immediately.
  A legacy LLM-based article-ingestion implementation remains below that return,
  making the code misleading even though it is unreachable at runtime.

Run from the repository root:

    python scripts/cleanup_step1_dead_code.py --check
    python scripts/cleanup_step1_dead_code.py --apply

The script is intentionally conservative. It only edits ``server.py`` when all
anchor strings are found exactly once and the resulting file passes Python AST
parsing.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import shutil
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = REPO_ROOT / "server.py"

START_ANCHOR = '    return {"success": True, "brief": brief}\n        \n    # 调用 LLM 做文章提炼\n'
END_ANCHOR = '\n# ==================== 步骤 2: 分镜规划 ====================' 


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def import_article_source(text: str) -> str:
    tree = ast.parse(text, filename=str(SERVER_PATH))
    lines = text.splitlines()
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "import_article"
    ]
    if len(matches) != 1:
        raise ValueError(f"expected import_article() exactly once, found {len(matches)}")
    node = matches[0]
    if node.end_lineno is None:
        raise ValueError("Python AST did not provide import_article() end line")
    return "\n".join(lines[node.lineno - 1 : node.end_lineno])


def verify_cleaned_step1(text: str) -> bool:
    source = import_article_source(text)
    required_return = 'return {"success": True, "brief": brief}'
    if source.count(required_return) != 1:
        return False
    forbidden_fragments = (
        "llm_api_key",
        "llm_model",
        "client.chat.completions.create(",
        "step1_llm_success",
        "step1_llm_error",
    )
    return not any(fragment in source for fragment in forbidden_fragments)


def locate_dead_block(text: str) -> tuple[int, int] | None:
    start_count = text.count(START_ANCHOR)
    if start_count == 0:
        if verify_cleaned_step1(text):
            return None
        raise ValueError("START_ANCHOR was not found and import_article() is not in the cleaned state")
    if start_count != 1:
        raise ValueError(f"expected START_ANCHOR exactly once, found {start_count}")

    start = text.index(START_ANCHOR) + len('    return {"success": True, "brief": brief}\n')
    end = text.find(END_ANCHOR, start)
    if end < 0:
        raise ValueError("END_ANCHOR was not found after the Step 1 return")

    block = text[start:end]
    required_fragments = (
        "# 调用 LLM 做文章提炼",
        "client.chat.completions.create(",
        "step1_llm_success",
        "step1_llm_error",
        'return {"success": True, "brief": brief}',
    )
    missing = [fragment for fragment in required_fragments if fragment not in block]
    if missing:
        raise ValueError(f"dead-code block did not contain expected fragments: {missing}")
    return start, end


def patched_text(text: str) -> str:
    location = locate_dead_block(text)
    if not location:
        return text
    start, end = location
    replacement = "\n"
    return text[:start] + replacement + text[end:]


def ast_check(text: str) -> None:
    ast.parse(text, filename=str(SERVER_PATH))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="verify that cleanup can be applied safely")
    mode.add_argument("--apply", action="store_true", help="rewrite server.py and keep a timestamped backup")
    args = parser.parse_args()

    if not SERVER_PATH.exists():
        return fail(f"server.py not found at {SERVER_PATH}")

    original = SERVER_PATH.read_text(encoding="utf-8")
    try:
        new_text = patched_text(original)
        ast_check(new_text)
        if not verify_cleaned_step1(new_text):
            return fail("cleanup validation failed: import_article() still contains Step 1 LLM logic")
    except Exception as exc:
        return fail(f"cleanup validation failed: {type(exc).__name__}: {exc}")

    if new_text == original:
        print("OK Step 1 dead-code block already absent.")
        return 0

    removed_lines = len(original.splitlines()) - len(new_text.splitlines())
    print(f"OK cleanup is safe; would remove {removed_lines} unreachable lines from server.py.")

    if args.check:
        diff = difflib.unified_diff(
            original.splitlines(),
            new_text.splitlines(),
            fromfile="server.py",
            tofile="server.py.cleaned",
            lineterm="",
        )
        preview_lines = list(diff)[:120]
        print("\n".join(preview_lines))
        if len(preview_lines) == 120:
            print("... diff preview truncated ...")
        return 0

    backup_path = SERVER_PATH.with_suffix(f".py.bak-step1-{datetime.now().strftime('%Y%m%d%H%M%S')}")
    shutil.copy2(SERVER_PATH, backup_path)
    SERVER_PATH.write_text(new_text, encoding="utf-8")
    print(f"APPLIED removed {removed_lines} unreachable lines from server.py")
    print(f"BACKUP {backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
