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

The script is intentionally conservative. It only edits ``server.py`` when the
target function can be located safely and the resulting file passes Python AST
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

STEP1_RETURN = '    return {"success": True, "brief": brief}'
END_ANCHOR = '\n@app.get("/api/projects/{project_id}/steps/1/result")'
LEGACY_STEP1_MARKERS = (
    'llm_api_key = get_setting("llm_api_key")',
    "client.chat.completions.create(",
    "step1_llm_success",
    "step1_llm_error",
)


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def line_start_offsets(text: str) -> list[int]:
    offsets = [0]
    for index, char in enumerate(text):
        if char == "\n":
            offsets.append(index + 1)
    return offsets


def import_article_span(text: str) -> tuple[int, int, str]:
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
    offsets = line_start_offsets(text)
    start = offsets[node.lineno - 1]
    if node.end_lineno < len(offsets):
        end = offsets[node.end_lineno]
    else:
        end = len(text)
    return start, end, "\n".join(lines[node.lineno - 1 : node.end_lineno])


def import_article_source(text: str) -> str:
    return import_article_span(text)[2]


def verify_cleaned_step1(text: str) -> bool:
    source = import_article_source(text)
    if source.count(STEP1_RETURN) != 1:
        return False
    return not any(fragment in source for fragment in LEGACY_STEP1_MARKERS)


def locate_dead_block(text: str) -> tuple[int, int] | None:
    function_start, function_end, source = import_article_span(text)
    return_count = source.count(STEP1_RETURN)
    if return_count == 0:
        raise ValueError("Step 1 success return was not found")
    if return_count != 1:
        raise ValueError(f"expected Step 1 success return exactly once, found {return_count}")

    start = function_start + source.index(STEP1_RETURN) + len(STEP1_RETURN)
    if start < len(text) and text[start] == "\n":
        start += 1
    end = function_end

    block = text[start:end]
    if not any(marker in block for marker in LEGACY_STEP1_MARKERS):
        if verify_cleaned_step1(text):
            return None
        remaining = [marker for marker in LEGACY_STEP1_MARKERS if marker in text]
        if remaining:
            raise ValueError(f"legacy Step 1 markers remain outside import_article(): {remaining}")
        raise ValueError("legacy Step 1 markers not found and import_article() is not in the cleaned state")

    missing = [fragment for fragment in LEGACY_STEP1_MARKERS if fragment not in block]
    if missing:
        raise ValueError(f"dead-code block did not contain expected fragments: {missing}")
    return start, end


def patched_text(text: str) -> str:
    location = locate_dead_block(text)
    if not location:
        return text
    start, end = location
    return text[:start] + "\n" + text[end:]


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
